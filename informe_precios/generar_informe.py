"""Script principal del informe diario de precios energéticos.

Uso:
    python generar_informe.py                # con fecha de hoy (entrega mañana)
    python generar_informe.py --fecha 2026-09-08   # fecha concreta
"""

import argparse
import logging
import os
import sys
from datetime import datetime

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


def ejecutar(fecha=None, enviar=False):
    """Genera el informe y (si ``enviar``) lo manda por correo.

    Devuelve la ruta del PDF generado. Con ``enviar=False`` (usado por la
    interfaz web y --no-enviar) solo se genera el PDF para revisión.
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
        h = hist_mibgas[hist_mibgas["fecha"] <= pd.Timestamp(fecha_hoy)].sort_values("fecha")
        if not h.empty:
            precio_mibgas = round(h.iloc[-1]["precio"], 2)
            if len(h) > 1:
                precio_mibgas_ant = round(h.iloc[-2]["precio"], 2)
            log.info("Precio MIBGAS hoy (%s): %s", h.iloc[-1]["fecha"].date(), precio_mibgas)

    futuros_elec = _actuales_desde_historico(hist_elec, config.CONTRATOS_ELEC)
    futuros_gas = _actuales_desde_historico(hist_gas, config.CONTRATOS_GAS)

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
    if not enviar:
        log.info("Envío desactivado: solo generación (revisión previa)")
    elif not enviar_correo.es_dia_laborable():
        log.info("Hoy no es día laborable (lunes a viernes), se omite el envío")
    elif os.name != "nt":
        log.info("Plataforma no Windows, se omite el envío vía Outlook")
    else:
        contactos = enviar_correo.leer_contactos()
        if not contactos:
            log.warning("Sin destinatarios, se omite el envío")
        else:
            enviados = enviar_correo.enviar_informe(destino, contactos)
            log.info("Informe enviado a %d destinatarios", enviados)

    return destino


def main():
    parser = argparse.ArgumentParser(description="Genera el informe diario de precios")
    parser.add_argument("--fecha", type=str, default=None,
                        help="Fecha 'hoy' en formato YYYY-MM-DD (por defecto: hoy)")
    parser.add_argument("--enviar", dest="enviar", action="store_true", default=True,
                        help="Envía el informe por correo tras generarlo (por defecto)")
    parser.add_argument("--no-enviar", dest="enviar", action="store_false",
                        help="Genera el PDF sin enviarlo por correo")
    args = parser.parse_args()

    ejecutar(args.fecha, args.enviar)
    return 0


if __name__ == "__main__":
    sys.exit(main())