"""Descarga del precio marginal horario (day-ahead) de OMIE.

Fuentes (en orden, cada intento las prueba todas):
1. Archivo publico marginalpdbc_YYYYMMDD.1
   URL: https://www.omie.es/en/file-download?parents=marginalpdbc&filename=marginalpdbc_YYYYMMDD.1
   Formato (semicolon-separated, primera linea = tipo, ultima = '*'):
       AAAA;MM;DD;periodo;precioPT;precioES;
2. Pagina de resultados "Precio del mercado diario" (data-chart del grafico).
3. TXT enlazado por esa misma pagina (atributo data-path).
"""

import io
import json
import logging
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

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
    En cada intento, si el archivo falla se intenta la pagina de OMIE y luego el
    TXT que esa pagina enlaza. Agotados los reintentos, se propaga el error.
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
    """Un único intento: archivo marginalpdbc, luego pagina, luego TXT."""
    try:
        return _descargar_dia_archivo(fecha, url)
    except (requests.HTTPError, requests.RequestException, ValueError) as e:
        error = e
        log.warning(
            "OMIE %s: archivo marginalpdbc no disponible (%s); probando pagina",
            fecha.date(), e,
        )

    chart = None
    try:
        chart = _obtener_pagina(fecha)
    except (requests.HTTPError, requests.RequestException, ValueError) as e:
        log.warning("OMIE %s: pagina no disponible: %s", fecha.date(), e)

    if chart is not None:
        try:
            df = _df_desde_chart(chart, fecha)
            log.info("OMIE %s obtenido de la pagina omie.es", fecha.date())
            return df
        except (requests.RequestException, ValueError) as e:
            log.warning("OMIE %s: grafico de la pagina invalido: %s", fecha.date(), e)
        try:
            df = _df_desde_txt(chart, fecha)
            log.info("OMIE %s obtenido del TXT enlazado por la pagina", fecha.date())
            return df
        except (requests.RequestException, ValueError) as e:
            log.warning("OMIE %s: TXT enlazado no disponible: %s", fecha.date(), e)

    raise error


def _descargar_dia_archivo(fecha, url):
    """Descarga y parsea el archivo marginalpdbc."""
    log.info("Descargando OMIE %s (%s)", fecha.date(), url)
    resp = requests.get(url, timeout=60, headers=config.OMIE_HEADERS)
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


def _obtener_pagina(fecha):
    """Devuelve el div del grafico (con data-chart y data-path) de la pagina OMIE."""
    url = config.OMIE_PAGINA
    params = {
        "date": f"{fecha:%Y-%m-%d}",
        "scope": "daily",
        "period": "60",
        "op": "Buscar",
    }
    log.info("Descargando OMIE pagina %s (%s %s)", fecha.date(), url, params)
    resp = requests.get(url, params=params, timeout=60, headers=config.OMIE_HEADERS)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"OMIE pagina no disponible para {fecha.date()} (HTTP {resp.status_code})"
        )
    soup = BeautifulSoup(resp.text, "lxml")
    chart = soup.find("div", class_="charts-highchart")
    if chart is None or not chart.get("data-chart"):
        raise ValueError(f"OMIE pagina sin grafico para {fecha.date()}")
    return chart


def _df_desde_chart(chart, fecha):
    """Construye el DataFrame horario a partir del JSON de data-chart."""
    cfg = json.loads(chart["data-chart"])
    series = {s.get("name"): s.get("data") for s in cfg.get("series", [])}
    nombres = {"es": "Precio marginal español", "pt": "Precio marginal portugués"}
    precios = {}
    for clave, nombre in nombres.items():
        datos = series.get(nombre)
        if not datos or len(datos) != 24 or any(v is None for v in datos):
            raise ValueError(
                f"OMIE grafico sin serie '{nombre}' completa para {fecha.date()}"
            )
        precios[clave] = [float(v) for v in datos]

    df = pd.DataFrame({
        "hora": range(1, 25),
        "precio_es": precios["es"],
        "precio_pt": precios["pt"],
    })
    df["fecha"] = pd.Timestamp(fecha.date())
    return df[["fecha", "hora", "precio_es", "precio_pt"]]


def _df_desde_txt(chart, fecha):
    """Descarga el TXT enlazado en data-path y construye el DataFrame horario."""
    txt_url = chart.get("data-path")
    if not txt_url:
        raise ValueError(f"OMIE pagina sin data-path para {fecha.date()}")
    log.info("Descargando OMIE TXT %s (%s)", fecha.date(), txt_url)
    resp = requests.get(txt_url, timeout=60, headers=config.OMIE_HEADERS)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"OMIE TXT no disponible para {fecha.date()} (HTTP {resp.status_code})"
        )
    if not resp.content.strip():
        raise ValueError(f"OMIE TXT vacio para {fecha.date()}")

    texto = resp.content.decode("latin-1", errors="replace")
    filas = {}
    for linea in texto.splitlines():
        partes = linea.split(";")
        etiqueta = partes[0].strip().lower()
        if etiqueta.startswith("precio marginal en el sistema espa"):
            filas.setdefault("es", partes[1:])
        elif etiqueta.startswith("precio marginal en el sistema portu"):
            filas.setdefault("pt", partes[1:])
    if "es" not in filas or "pt" not in filas:
        raise ValueError(f"OMIE TXT sin precios marginales para {fecha.date()}")

    return _montar_df_horario(
        _series_a_horas(filas["es"], fecha, "español"),
        _series_a_horas(filas["pt"], fecha, "portugués"),
        fecha,
    )


def _series_a_horas(valores, fecha, sistema):
    """Convierte la serie de periodos (24 u 96) en 24 precios horarios."""
    nums = []
    for v in valores:
        v = v.strip()
        if not v or v == "*":
            continue
        nums.append(float(v.replace(",", ".")))
    if len(nums) == 96:
        nums = [sum(nums[i:i + 4]) / 4 for i in range(0, 96, 4)]
    elif len(nums) != 24:
        raise ValueError(
            f"OMIE TXT sistema {sistema}: {len(nums)} periodos "
            f"(se esperaban 24 o 96) para {fecha.date()}"
        )
    return nums


def _montar_df_horario(precio_es, precio_pt, fecha):
    df = pd.DataFrame({
        "hora": range(1, 25),
        "precio_es": precio_es,
        "precio_pt": precio_pt,
    })
    df["fecha"] = pd.Timestamp(pd.Timestamp(fecha).date())
    return df[["fecha", "hora", "precio_es", "precio_pt"]]


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
