"""Script principal del informe diario de precios energéticos.

Uso:
    python generar_informe.py                # con fecha de hoy (entrega mañana)
    python generar_informe.py --fecha 2026-09-08   # fecha concreta
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from modulos import (
    cargar_historicos,
    descargar_mibgas,
    descargar_omie,
    descargar_omip,
    enviar_correo,
    generar_pdf,
    graficos,
)
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("informe")


@dataclass
class Resultado:
    """Resultado de una generación: PDF, campos faltantes y estado del envío."""
    pdf: object
    faltan: list
    enviado: bool
    motivo: str
    fecha_hoy: object


def _leer_historico(csv):
    if csv.exists() and csv.stat().st_size > 0:
        return pd.read_csv(csv, parse_dates=["fecha"])
    return None


def _actuales_desde_historico(hist, contratos):
    """Extrae los valores de la última fila del histórico para cada contrato."""
    salida = []
    if hist is None or hist.empty:
        return [(etiqueta, None) for etiqueta, _, _ in contratos]
    ultima = hist.iloc[-1]
    for etiqueta, _, col in contratos:
        v = ultima.get(col)
        salida.append((etiqueta, float(v) if pd.notna(v) else None))
    return salida


def _faltantes_contratos(contratos, actuales):
    """Faltantes de una tabla de futuros (un ítem por contrato sin precio)."""
    faltan = []
    for (etiqueta, precio), (_, _, col) in zip(actuales, contratos):
        if precio is None:
            faltan.append({"clave": col, "nombre": etiqueta})
    return faltan


def _datos_faltantes(precio_omie, precio_mibgas, futuros_elec, futuros_gas):
    """Devuelve la lista de datos imprescindibles que faltan para el envío.

    Cualquier valor ausente (precio OMIE, MIBGAS o un contrato de futuros
    concreto) bloquea el envío automático del informe.
    """
    faltan = []
    if precio_omie is None:
        faltan.append({"clave": "omie", "nombre": "Precio medio OMIE (mañana)"})
    if precio_mibgas is None:
        faltan.append({"clave": "mibgas", "nombre": "Precio MIBGAS (mañana)"})
    faltan += _faltantes_contratos(config.CONTRATOS_ELEC, futuros_elec)
    faltan += _faltantes_contratos(config.CONTRATOS_GAS, futuros_gas)
    return faltan


def _override_num(manual, clave, actual):
    """Sustituye un valor KPI por el manual si viene bien formado."""
    if clave not in manual or manual[clave] in (None, ""):
        return actual
    return float(manual[clave])


def _resumen_manual(manual):
    """Texto breve de los datos manuales aplicados (para el log)."""
    futuros = manual.get("futuros") or {}
    partes = [k for k in ("precio_omie", "precio_mibgas") if manual.get(k)]
    partes += [f"{k}={v}" for k, v in futuros.items()]
    return ", ".join(partes) or "ninguno"


def _escribir_estado(fecha_hoy, resultado):
    """Guarda en salida/ultimo_estado.json el estado de la última ejecución.

    La web lo lee para mostrar la alerta si el envío automático quedó
    bloqueado por datos incompletos.
    """
    try:
        config.ULTIMO_ESTADO_JSON.write_text(
            json.dumps({
                "fecha": f"{fecha_hoy:%Y-%m-%d}",
                "fecha_entrega": f"{(fecha_hoy + pd.Timedelta(days=1)):%Y-%m-%d}",
                "pdf": Path(str(resultado.pdf)).name,
                "enviado": resultado.enviado,
                "motivo": resultado.motivo,
                "faltan": resultado.faltan,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        log.exception("No se pudo escribir el estado de la ejecución")


def ejecutar(fecha=None, enviar=False, manual=None):
    """Genera el informe y (si ``enviar``) lo manda por correo.

    ``manual`` es un dict opcional con valores introducidos a mano cuando
    faltan datos: {"precio_omie": float, "precio_mibgas": float,
    "futuros": {codigo_columna: float}}. Se aplica solo a esta generación.

    Devuelve un ``Resultado`` con el PDF generado, la lista de datos
    faltantes y si el envío se realizó. Si faltan datos, el envío se bloquea
    (no se manda) y se registra la alerta.
    """
    config.asegurar_dirs()

    if fecha:
        fecha_hoy = pd.Timestamp(fecha).normalize()
    else:
        fecha_hoy = pd.Timestamp(datetime.now().date())
    fecha_entrega = fecha_hoy + pd.Timedelta(days=1)

    # 1) Importar históricos existentes (solo la primera vez)
    cargar_historicos.importar_historicos()

    # 2) Datos
    log.info("=== Fecha de informe: %s (entrega mañana: %s) ===", fecha_hoy, fecha_entrega)

    hist_elec = hist_gas = hist_mibgas = hist_omie = None
    actuales_elec = actuales_gas = {}

    # OMIE
    try:
        hist_omie = descargar_omie.acumular(fecha_entrega)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIE: %s", e)

    # OMIP electricidad
    try:
        hist_elec, actuales_elec = descargar_omip.acumular_electricidad(fecha_entrega)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIP electricidad: %s", e)
        hist_elec = _leer_historico(config.CSV_OMIP_ELEC)
        actuales_elec = dict(_actuales_desde_historico(hist_elec, config.CONTRATOS_ELEC))

    # OMIP gas
    try:
        hist_gas, actuales_gas = descargar_omip.acumular_gas(fecha_entrega)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIP gas: %s", e)
        hist_gas = _leer_historico(config.CSV_OMIP_GAS)
        actuales_gas = dict(_actuales_desde_historico(hist_gas, config.CONTRATOS_GAS))

    # MIBGAS
    try:
        hist_mibgas = descargar_mibgas.acumular()
    except Exception as e:  # noqa: BLE001
        log.error("Error MIBGAS: %s", e)
        hist_mibgas = _leer_historico(config.CSV_MIBGAS)

    # 3) KPIs para portada
    precio_omie = None
    precio_omie_ant = None
    if hist_omie is not None and not hist_omie.empty:
        dia = hist_omie[hist_omie["fecha"].dt.date == fecha_entrega.date()]
        if not dia.empty:
            precio_omie = round(dia["precio_es"].mean(), 2)
            log.info("Precio medio OMIE mañana (%s): %s", fecha_entrega, precio_omie)
            ant = hist_omie[hist_omie["fecha"].dt.date < fecha_entrega.date()]
            if not ant.empty:
                ultima = ant["fecha"].dt.date.max()
                precio_omie_ant = round(ant[ant["fecha"].dt.date == ultima]["precio_es"].mean(), 2)

    precio_mibgas = None
    precio_mibgas_ant = None
    if hist_mibgas is not None and not hist_mibgas.empty:
        dia = hist_mibgas[hist_mibgas["fecha"] == pd.Timestamp(fecha_entrega.date())]
        if not dia.empty:
            precio_mibgas = round(dia.iloc[0]["precio"], 2)
            ant = hist_mibgas[hist_mibgas["fecha"] < pd.Timestamp(fecha_entrega.date())]
            if not ant.empty:
                precio_mibgas_ant = round(ant["precio"].iloc[-1], 2)
            log.info("Precio MIBGAS mañana (%s): %s", fecha_entrega.date(), precio_mibgas)

    futuros_elec = _actuales_desde_historico(hist_elec, config.CONTRATOS_ELEC)
    futuros_gas = _actuales_desde_historico(hist_gas, config.CONTRATOS_GAS)

    # 3b) Datos manuales (solo si el operador los introduce en la web)
    if manual:
        precio_omie = _override_num(manual, "precio_omie", precio_omie)
        precio_mibgas = _override_num(manual, "precio_mibgas", precio_mibgas)
        futuros_manual = manual.get("futuros") or {}
        futuros_elec = [
            (et, futuros_manual.get(col, precio))
            for (et, precio), (_, _, col)
            in zip(futuros_elec, config.CONTRATOS_ELEC)
        ]
        futuros_gas = [
            (et, futuros_manual.get(col, precio))
            for (et, precio), (_, _, col)
            in zip(futuros_gas, config.CONTRATOS_GAS)
        ]
        log.info("Datos manuales aplicados: %s", _resumen_manual(manual))

    # 3c) Control de calidad: datos imprescindibles presentes
    faltan = _datos_faltantes(precio_omie, precio_mibgas, futuros_elec, futuros_gas)

    # 4) Gráficos
    carpeta = config.DATOS_DIR
    grafico_horario = graficos.grafico_horario_omie(hist_omie, fecha_entrega) \
        if hist_omie is not None else None
    graficos_elec = graficos.graficos_electricidad(hist_elec, carpeta)
    graficos_gas = graficos.graficos_gas_futuros(hist_gas, carpeta)
    grafico_mibgas = graficos.grafico_mibgas_largo(hist_mibgas, carpeta)

    # 5) PDF
    nombre = f"Informe Precio Diario {fecha_hoy:%d.%m.%Y}.pdf"
    destino = config.SALIDA_DIR / nombre
    generar_pdf.generar_pdf(destino, {
        "fecha_hoy": fecha_hoy,
        "fecha_entrega": fecha_entrega,
        "precio_omie": precio_omie,
        "precio_omie_ant": precio_omie_ant,
        "precio_mibgas": precio_mibgas,
        "precio_mibgas_ant": precio_mibgas_ant,
        "futuros_elec": futuros_elec,
        "futuros_gas": futuros_gas,
        "grafico_horario": grafico_horario,
        "graficos_elec": graficos_elec,
        "graficos_gas": graficos_gas,
        "grafico_mibgas": grafico_mibgas,
    })

    log.info("=== Informe completado: %s ===", destino)

    # 6) Envío por correo (solo si se pide explícitamente)
    enviado = False
    motivo = "sin_datos" if faltan else ""
    if not enviar:
        motivo = "solo_generacion"
        log.info("Envío desactivado: solo generación (revisión previa)")
    elif faltan:
        nombres = ", ".join(f["nombre"] for f in faltan)
        log.warning("Datos incompletos, NO se envía el informe. Faltan: %s", nombres)
        if os.name == "nt" and enviar_correo.es_dia_laborable():
            try:
                enviar_correo.enviar_alerta_datos_faltantes(fecha_hoy, faltan)
                motivo = "bloqueado_por_datos"
            except Exception as e:  # noqa: BLE001
                log.exception("No se pudo enviar la alerta de datos incompletos")
    elif not enviar_correo.es_dia_laborable():
        motivo = "no_laborable"
        log.info("Hoy no es día laborable (lunes a viernes), se omite el envío")
    elif os.name != "nt":
        motivo = "no_windows"
        log.info("Plataforma no Windows, se omite el envío vía Outlook")
    else:
        contactos = enviar_correo.leer_contactos()
        if not contactos:
            motivo = "sin_contactos"
            log.warning("Sin destinatarios, se omite el envío")
        else:
            enviados = enviar_correo.enviar_informe(destino, contactos)
            enviado = True
            motivo = "ok"
            log.info("Informe enviado a %d destinatarios", enviados)

    resultado = Resultado(pdf=destino, faltan=faltan, enviado=enviado,
                          motivo=motivo, fecha_hoy=fecha_hoy)
    _escribir_estado(fecha_hoy, resultado)
    return resultado


def _activar_log_archivo():
    if _activar_log_archivo.hecho:
        return
    _activar_log_archivo.hecho = True
    ruta = config.SALIDA_DIR / "generar_informe.log"
    fh = logging.FileHandler(ruta, encoding="utf-8", delay=True)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("Log de ejecución: %s", ruta)


_activar_log_archivo.hecho = False


def main():
    _activar_log_archivo()
    parser = argparse.ArgumentParser(description="Genera el informe diario de precios")
    parser.add_argument("--fecha", type=str, default=None,
                        help="Fecha 'hoy' en formato YYYY-MM-DD (por defecto: hoy)")
    parser.add_argument("--enviar", dest="enviar", action="store_true", default=True,
                        help="Envía el informe por correo tras generarlo (por defecto)")
    parser.add_argument("--no-enviar", dest="enviar", action="store_false",
                        help="Genera el PDF sin enviarlo por correo")
    args = parser.parse_args()

    resultado = ejecutar(args.fecha, args.enviar, None)
    if resultado.faltan:
        log.warning("Informe generado con %d datos faltantes; envío: %s.",
                    len(resultado.faltan),
                    "enviado" if resultado.enviado else "bloqueado")
    return 0


if __name__ == "__main__":
    sys.exit(main())