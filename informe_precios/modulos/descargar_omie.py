"""Descarga del precio marginal horario (day-ahead) de OMIE.

Fuente: archivo de texto publico marginalpdbc_YYYYMMDD.1
URL: https://www.omie.es/en/file-download?parents=marginalpdbc&filename=marginalpdbc_YYYYMMDD.1

Formato (semicolon-separated, primera linea = tipo, ultima = '*'):
    AAAA;MM;DD;periodo;precioPT;precioES;
"""

import io
import logging
import time

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)


def _url_dia(ano, mes, dia):
    fname = f"marginalpdbc_{ano:04d}{mes:02d}{dia:02d}.1"
    return f"{config.OMIE_BASE}?parents={config.OMIE_PARENTS}&filename={fname}"


def descargar_dia(fecha, reintentos=None, espera_seg=None):
    """Devuelve DataFrame con columnas [fecha, hora, precio_es, precio_pt] para `fecha`.

    - hora: 1..24 (agrupa los periodos de 15 min en horas)
    - precio_es: precio marginal del sistema espanol (EUR/MWh)
    - precio_pt: precio marginal del sistema portugues (EUR/MWh)

    OMIE publica el fichero del día de entrega el día anterior a hora variable;
    si aún no está disponible (HTTP 404, error de red o archivo vacio), se
    reintenta ``reintentos`` veces esperando ``espera_seg`` segundos entre ellas.
    Agotados los reintentos, se propaga el error.
    """
    if reintentos is None:
        reintentos = config.OMIE_REINTENTOS
    if espera_seg is None:
        espera_seg = config.OMIE_ESPERA_SEG

    fecha = pd.Timestamp(fecha).normalize()
    url = _url_dia(fecha.year, fecha.month, fecha.day)
    total = reintentos + 1
    for intento in range(1, total + 1):
        try:
            return _descargar_dia_intento(fecha, url)
        except (requests.HTTPError, requests.RequestException, ValueError) as e:
            if intento >= total:
                raise
            log.warning(
                "OMIE %s no disponible (intento %d/%d): %s. Reintentando en %ds",
                fecha.date(), intento, total, e, espera_seg,
            )
            time.sleep(espera_seg)


def _descargar_dia_intento(fecha, url):
    """Un único intento de descarga y parseo del archivo OMIE."""
    log.info("Descargando OMIE %s (%s)", fecha.date(), url)
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"OMIE no disponible para {fecha.date()} (HTTP {resp.status_code})"
        )
    if not resp.text.strip():
        raise ValueError(f"OMIE archivo vacio para {fecha.date()}")

    df = pd.read_csv(
        io.StringIO(resp.text), sep=";", header=None,
        skiprows=1, names=["anio", "mes", "dia", "periodo", "pt", "es", "x"],
        dtype=str,
    )
    df = df[df["periodo"].notna() & df["periodo"].str.isdigit()]
    df["periodo"] = df["periodo"].astype(int)
    df["es"] = pd.to_numeric(df["es"].str.replace(",", "."), errors="coerce")
    df["pt"] = pd.to_numeric(df["pt"].str.replace(",", "."), errors="coerce")

    # Agrupar periodos de 15 min en horas (1..96 -> 1..24)
    df["hora"] = ((df["periodo"] - 1) // 4) + 1
    agg = df.groupby("hora")[["es", "pt"]].mean().reset_index()
    agg = agg.rename(columns={"es": "precio_es", "pt": "precio_pt"})
    agg["fecha"] = pd.Timestamp(fecha.date())
    return agg[["fecha", "hora", "precio_es", "precio_pt"]]


def acumular(fecha):
    """Descarga y acumula el dia en el CSV historico. Devuelve None si no hay datos."""
    fecha = pd.Timestamp(fecha).normalize()
    csv = config.CSV_OMIE

    if csv.exists():
        existente = pd.read_csv(csv)
        existente["fecha"] = pd.to_datetime(existente["fecha"])
        fechas = set(existente["fecha"].dt.date)
        if fecha.date() in fechas:
            log.info("OMIE ya tiene datos para %s", fecha.date())
            return existente
    else:
        existente = pd.DataFrame()

    try:
        nuevo = descargar_dia(fecha)
    except (requests.HTTPError, requests.RequestException, ValueError) as e:
        log.warning("No se acumulo OMIE: %s", e)
        return existente if not existente.empty else None

    combo = pd.concat([existente, nuevo], ignore_index=True)
    combo = combo.drop_duplicates(subset=["fecha", "hora"], keep="last")
    combo = combo.sort_values(["fecha", "hora"]).reset_index(drop=True)
    combo.to_csv(csv, index=False)
    log.info("OMIE acumulado: %d filas (dia %s)", len(combo), fecha.date())
    return combo