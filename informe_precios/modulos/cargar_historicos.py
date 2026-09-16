"""Importación inicial de los históricos existentes (Excel actuales) a CSVs locales.

Se ejecuta una única vez (la primera ejecución) para que los gráficos de evolución
ya tengan datos históricos desde el primer día. Si el CSV destino ya existe con
datos, se conserva (no se sobrescribe).
"""

import logging
import re

import pandas as pd

import config

log = logging.getLogger(__name__)


def _importar_futuros_omip(xlsx_ruta, csv_destino, tipo):
    """Importa un Excel de históricos de futuros de OMIP.

    Estructura: hojas con columnas Fecha | Periodo | Entrega | Precio.
    Cada hoja corresponde a un contrato distinto. La columna "Entrega"
    identifica el contrato (p.ej. "Trim 4 -26" = Q4-2026, "Año -27" = YR-27).
    """
    if csv_destino.exists() and csv_destino.stat().st_size > 0:
        log.info("Ya existe %s, se omite importacion de %s", csv_destino.name, tipo)
        return

    if not xlsx_ruta.exists():
        log.warning("No existe %s, no se puede importar %s", xlsx_ruta.name, tipo)
        return

    hojas = pd.read_excel(xlsx_ruta, sheet_name=None, header=0)
    frames = []
    for nombre, df in hojas.items():
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        col_fecha = next((c for c in df.columns if "echa" in c), None)
        col_precio = next((c for c in df.columns if "recio" in c), None)
        col_entrega = next((c for c in df.columns if "ntrega" in c), None)
        if not col_fecha or not col_precio:
            log.debug("Hoja %s de %s: columnas %s (omitida)", nombre, tipo, df.columns.tolist())
            continue
        sub = df[[col_fecha, col_precio] + ([col_entrega] if col_entrega else [])].copy()
        sub.columns = ["fecha", "precio"] + (["entrega"] if col_entrega else [])
        sub = sub.dropna(subset=["fecha", "precio"])
        sub["fecha"] = pd.to_datetime(sub["fecha"], errors="coerce")
        sub["precio"] = pd.to_numeric(sub["precio"], errors="coerce")
        sub = sub.dropna(subset=["fecha", "precio"])
        if col_entrega:
            sub["entrega"] = sub["entrega"].astype(str).str.strip()
            sub["col_clave"] = sub["entrega"].apply(_entrega_a_columna)
        else:
            sub["col_clave"] = _entrega_a_columna(nombre)
        frames.append(sub[["fecha", "precio", "col_clave"]])

    if not frames:
        log.warning("No se encontraron datos validos en %s", xlsx_ruta.name)
        return

    todo = pd.concat(frames, ignore_index=True)
    tab = todo.pivot_table(index="fecha", columns="col_clave", values="precio", aggfunc="last")
    tab = tab.sort_index()
    tab = tab.reset_index()
    tab["fecha"] = tab["fecha"].dt.date
    tab.to_csv(csv_destino, index=False)
    log.info("Importado %s -> %s (%d filas, columnas: %s)",
             xlsx_ruta.name, csv_destino.name, len(tab),
             [c for c in tab.columns if c != "fecha"])


def _entrega_a_columna(texto):
    """Convierte texto de 'Entrega' o nombre de hoja a clave de columna config.

    Ejemplos:
        "Trim 4 -26" -> "BASE_Q4_2026"
        "Trim 1 -27" -> "BASE_Q1_2027"
        "Trim 2 -27" -> "BASE_Q2_2027"
        "Trim 4 -27" -> "BASE_Q4_2027"
        "Año -27"    -> "BASE_YEAR_2027"
        "Año -28"    -> "BASE_YEAR_2028"
    """
    s = str(texto).strip()
    # Trimestral: "Trim X -YY"
    m = re.search(r"Trim\s+(\d)\s*-\s*(\d{2})", s)
    if m:
        q = int(m.group(1))
        yr = int(m.group(2))
        return f"BASE_Q{q}_{2000 + yr}"
    # Anual: "Año -YY" or "Anual -YY"  (ñ o n)
    m = re.search(r"[Aa][nñ](?:o|ual)\s*-\s*(\d{2})", s)
    if m:
        yr = int(m.group(1))
        return f"BASE_YEAR_{2000 + yr}"
    return s


def _importar_mibgas():
    csv = config.CSV_MIBGAS
    if csv.exists() and csv.stat().st_size > 0:
        log.info("Ya existe %s, se omite importación de MIBGAS historico", csv.name)
        return
    if not config.HIST_MIBGAS_XLSX.exists():
        log.warning("No existe %s", config.HIST_MIBGAS_XLSX.name)
        return
    df = pd.read_excel(config.HIST_MIBGAS_XLSX)
    df.columns = [str(c).strip() for c in df.columns]
    col_f = next((c for c in df.columns if "echa" in c), None)
    col_p = next((c for c in df.columns if "recio" in c), None)
    if not col_f or not col_p:
        log.warning("Estructura no reconocida en %s", config.HIST_MIBGAS_XLSX.name)
        return
    out = df[[col_f, col_p]].copy()
    out.columns = ["fecha", "precio"]
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out["precio"] = pd.to_numeric(out["precio"], errors="coerce")
    out = out.dropna().sort_values("fecha").reset_index(drop=True)
    out["fecha"] = out["fecha"].dt.date
    out.to_csv(csv, index=False)
    log.info("Importado MIBGAS -> %s (%d filas)", csv.name, len(out))


def importar_historicos():
    """Importa los históricos de los Excel actuales (una única vez)."""
    config.asegurar_dirs()
    _importar_futuros_omip(config.HIST_ELEC_XLSX, config.CSV_OMIP_ELEC, "electricidad")
    _importar_futuros_omip(config.HIST_GAS_XLSX, config.CSV_OMIP_GAS, "gas")
    _importar_mibgas()

