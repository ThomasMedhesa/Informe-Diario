"""Descarga del precio spot de gas PVB (MIBGAS) y acumulación de histórico.

Fuente: fichero XLSX anual público de MIBGAS:
  https://www.mibgas.es/en/file-access/MIBGAS_Data_<YYYY>.xlsx?path=AGNO_<YYYY>/XLS

El precio diario que usa el informe es el **Last Price** (precio indexado) del
producto **day-ahead (`GDAES_D+N`)** en PVB/ES, asociado a la **fecha de entrega**
(First Day Delivery). Ejemplo: el día 08/09 corresponde al GDAES_D+1 con
delivery 08/09 (fijado el día hábil anterior).
"""

import io
import logging

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _descargar_xlsx(anio):
    url = config.MIBGAS_ANUAL_XLSX.format(year=anio)
    log.info("Descargando MIBGAS anual %s (%s)", anio, url)
    resp = requests.get(url, timeout=180, headers=HEADERS)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"MIBGAS XLSX {anio} no disponible (HTTP {resp.status_code})"
        )
    if len(resp.content) < 10000:
        raise ValueError(f"MIBGAS XLSX {anio} con contenido insuficiente")
    return resp.content


def _extraer_precios_diarios(contenido_xlsx):
    """Devuelve DataFrame [fecha, precio] con el precio day-ahead PVB por día de entrega."""
    df = pd.read_excel(io.BytesIO(contenido_xlsx), sheet_name="Trading Data PVB&VTP")
    df.columns = [str(c).split("\n")[0].strip() for c in df.columns]

    prod = df["Product"].astype(str)
    pod = df["Place of delivery"].astype(str)
    es_dayahead = prod.str.startswith("GDAES") & (pod == "PVB")

    sub = df[es_dayahead].copy()
    sub["fecha"] = pd.to_datetime(sub["First Day Delivery"], errors="coerce")
    sub["precio"] = pd.to_numeric(sub["Last Price"], errors="coerce")
    sub = sub.dropna(subset=["fecha", "precio"])

    # Si un mismo día de entrega tiene varios productos GDAES_*, quedarse con el más cercano
    sub = sub.sort_values(["fecha", "Last Day Delivery"])
    sub = sub.drop_duplicates(subset=["fecha"], keep="first")

    out = sub[["fecha", "precio"]].sort_values("fecha").reset_index(drop=True)
    return out


def _leer_csv():
    csv = config.CSV_MIBGAS
    if csv.exists():
        hist = pd.read_csv(csv, parse_dates=["fecha"])
        return hist
    return pd.DataFrame(columns=["fecha", "precio"])


def acumular(anio=None):
    """Descarga el XLSX anual (del año actual o indicado) y actualiza el histórico CSV.

    El histórico se regenera a partir del XLSX anual (que contiene todos los días
    del año hasta la fecha) y se combina con el CSV previo sin duplicados, de modo
    que los años anteriores cargados manualmente se conservan.

    Devuelve el DataFrame histórico [fecha, precio].
    """
    if anio is None:
        anio = pd.Timestamp.now().year

    contenido = _descargar_xlsx(anio)
    actual = _extraer_precios_diarios(contenido)

    previo = _leer_csv()
    # mantiene datos de otros años que no estén en el fichero anual actual
    anios_actuales = set(actual["fecha"].dt.year)
    previo_otros = previo[~previo["fecha"].dt.year.isin(anios_actuales)]

    combo = pd.concat([previo_otros, actual], ignore_index=True)
    combo = combo.drop_duplicates(subset=["fecha"], keep="last")
    combo = combo.sort_values("fecha").reset_index(drop=True)
    combo.to_csv(config.CSV_MIBGAS, index=False)
    log.info("MIBGAS actualizado: %d filas (%s)", len(combo), anio)
    return combo

