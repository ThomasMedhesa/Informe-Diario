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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from modulos import (
    cargar_historicos,
    contratos_omip,
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
    fallidos_envio: list = field(default_factory=list)


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


def _faltantes_contratos(mercado, contratos, actuales):
    """Faltantes de una tabla de futuros (un ítem por contrato sin precio).

    ``clave`` lleva el mercado ("ELEC:"/"GAS:") porque electricidad y gas
    comparten columna historico: sin el, un unico campo manual sobrescribiria
    el precio de los dos mercados a la vez.
    """
    faltan = []
    for (etiqueta, precio), (_, _, col) in zip(actuales, contratos):
        if precio is None:
            faltan.append({
                "clave": f"{mercado}:{col}",
                "nombre": f"{etiqueta} ({mercado.lower()})",
            })
    return faltan


def _datos_faltantes(precio_omie, precio_mibgas, futuros_elec, contratos_elec,
                     futuros_gas, contratos_gas):
    """Devuelve la lista de datos imprescindibles que faltan para el envío.

    Solo se consideran los contratos que OMIP publica ese día: los que han
    caducado se retiran de la ventana y no bloquean nada (ver
    modulos/contratos_omip.py). Cualquier valor ausente entre los vigentes
    (precio OMIE, MIBGAS o un contrato concreto) sí bloquea el envío.
    """
    faltan = []
    if precio_omie is None:
        faltan.append({"clave": "omie", "nombre": "Precio medio OMIE (mañana)"})
    if precio_mibgas is None:
        faltan.append({"clave": "mibgas", "nombre": "Precio MIBGAS (hoy)"})
    faltan += _faltantes_contratos("ELEC", contratos_elec, futuros_elec)
    faltan += _faltantes_contratos("GAS", contratos_gas, futuros_gas)
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


def _avisar_manual_no_aplicado(manual, contratos_elec, contratos_gas):
    """Avisa en el log de los datos manuales que no corresponden a nada.

    Pasa cuando el operador completa un contrato que ya ha caducado o cuyo
    nombre no existe: el valor se ignora en silencio, asi que sin este aviso
    creeria haberselo aplicado.
    """
    futuros = manual.get("futuros") or {}
    if not futuros:
        return
    columnas = {c[2] for c in contratos_elec} | {c[2] for c in contratos_gas}
    validas = columnas | {f"{m}:{col}" for m in ("ELEC", "GAS") for col in columnas}
    ignorados = [k for k in futuros if k not in validas]
    if ignorados:
        log.warning(
            "Datos manuales ignorados, no corresponden a ningún contrato vigente: %s",
            ", ".join(ignorados),
        )


def _escribir_estado(fecha_hoy, resultado):
    """Guarda en salida/ultimo_estado.json el estado de la última ejecución.

    La web lo lee para mostrar la alerta si el envío automático quedó
    bloqueado por datos incompletos, o si algún destinatario no recibió el
    informe (``fallidos_envio``).
    """
    estado = {
        "fecha": f"{fecha_hoy:%Y-%m-%d}",
        "fecha_entrega": f"{(fecha_hoy + pd.Timedelta(days=1)):%Y-%m-%d}",
        "pdf": Path(str(resultado.pdf)).name,
        "enviado": resultado.enviado,
        "motivo": resultado.motivo,
        "faltan": resultado.faltan,
    }
    if resultado.fallidos_envio:
        estado["fallidos_envio"] = resultado.fallidos_envio
    try:
        config.ULTIMO_ESTADO_JSON.write_text(
            json.dumps(estado, ensure_ascii=False, indent=2),
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
    contratos_elec = contratos_gas = []
    ventana_cache = contratos_omip.cargar_cache()

    # OMIE
    try:
        hist_omie = descargar_omie.acumular(fecha_entrega)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIE: %s", e)

    # OMIP electricidad. OJO: a OMIP se le pregunta por la sesion de HOY, no por
    # la de manana (que es lo que se le pregunta a OMIE). La pagina de una
    # sesion que aun no ha ocurrido sale con la tira de contratos recortada por
    # su "Trading last day", asi que al preguntar por manana desaparece el mes
    # que caduca hoy y el informe lo daria como dato faltante.
    try:
        hist_elec, _, contratos_elec = descargar_omip.acumular_electricidad(fecha_hoy)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIP electricidad: %s", e)
        hist_elec = _leer_historico(config.CSV_OMIP_ELEC)
        contratos_elec = list(ventana_cache.get("electricidad", []))

    # OMIP gas (sesion de hoy, igual que electricidad)
    try:
        hist_gas, _, contratos_gas = descargar_omip.acumular_gas(fecha_hoy)
    except Exception as e:  # noqa: BLE001
        log.error("Error OMIP gas: %s", e)
        hist_gas = _leer_historico(config.CSV_OMIP_GAS)
        contratos_gas = list(ventana_cache.get("gas", []))

    log.info("Ventana de contratos electricidad: %s",
             ", ".join(c[1] for c in contratos_elec) or "ninguno")
    log.info("Ventana de contratos gas: %s",
             ", ".join(c[1] for c in contratos_gas) or "ninguno")

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
        h = hist_mibgas[hist_mibgas["fecha"] <= pd.Timestamp(fecha_hoy)].sort_values("fecha")
        if not h.empty:
            precio_mibgas = round(h.iloc[-1]["precio"], 2)
            if len(h) > 1:
                precio_mibgas_ant = round(h.iloc[-2]["precio"], 2)
            log.info("Precio MIBGAS hoy (%s): %s", h.iloc[-1]["fecha"].date(), precio_mibgas)

    futuros_elec = _actuales_desde_historico(hist_elec, contratos_elec)
    futuros_gas = _actuales_desde_historico(hist_gas, contratos_gas)

    # 3b) Datos manuales (solo si el operador los introduce en la web)
    if manual:
        precio_omie = _override_num(manual, "precio_omie", precio_omie)
        precio_mibgas = _override_num(manual, "precio_mibgas", precio_mibgas)
        futuros_manual = manual.get("futuros") or {}
        futuros_elec = [
            (et, contratos_omip.valor_manual(futuros_manual, col, "ELEC", precio))
            for (et, precio), (_, _, col) in zip(futuros_elec, contratos_elec)
        ]
        futuros_gas = [
            (et, contratos_omip.valor_manual(futuros_manual, col, "GAS", precio))
            for (et, precio), (_, _, col) in zip(futuros_gas, contratos_gas)
        ]
        log.info("Datos manuales aplicados: %s", _resumen_manual(manual))
        _avisar_manual_no_aplicado(manual, contratos_elec, contratos_gas)

    # 3c) Control de calidad: datos imprescindibles presentes
    faltan = _datos_faltantes(precio_omie, precio_mibgas,
                              futuros_elec, contratos_elec,
                              futuros_gas, contratos_gas)

    # 4) Gráficos
    carpeta = config.DATOS_DIR
    grafico_horario = graficos.grafico_horario_omie(hist_omie, fecha_entrega) \
        if hist_omie is not None else None
    graficos_elec = graficos.graficos_electricidad(hist_elec, carpeta, contratos_elec)
    graficos_gas = graficos.graficos_gas_futuros(hist_gas, carpeta, contratos_gas)
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
    fallidos_envio = []
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
            # El envío es a destinatario: unos pueden fallar sin que eso quite
            # el informe a los demás, así que se distingue el envío completo
            # del parcial y del total.
            envio = enviar_correo.enviar_informe(destino, contactos, fecha=fecha_hoy)
            fallidos_envio = list(envio.fallidos)
            enviado = envio.enviados > 0
            if envio.completo:
                motivo = "ok"
                log.info("Informe enviado a %d destinatarios", envio.enviados)
            elif enviado:
                motivo = "envio_parcial"
                log.warning("Informe enviado solo a %d de %d destinatarios. "
                            "Sin informe: %s", envio.enviados, envio.total,
                            ", ".join(envio.fallidos))
            else:
                motivo = "error_envio"
                log.error("No se pudo enviar el informe a ningún destinatario "
                          "de %d", envio.total)

    resultado = Resultado(pdf=destino, faltan=faltan, enviado=enviado,
                          motivo=motivo, fecha_hoy=fecha_hoy,
                          fallidos_envio=fallidos_envio)
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