"""Descarga de precios de cierre (settlement/referencia) de futuros OMIP.

Fuente: pagina publica 'dados-mercado' de OMIP (sin login).
- Electricidad: https://www.omip.pt/en/dados-mercado?date=YYYY-MM-DD&product=EL&zone=ES&instrument=FTB
- Gas:         https://www.omip.pt/en/dados-mercado?date=YYYY-MM-DD&product=NG&zone=ES&instrument=FGF

El HTML contiene varias tablas (una por tipo de madurez: D, WE, Wk, BoM, M, Q, SS, YR, PPA...).
Cada fila tiene en la columna 0 la informacion del contrato (donde el nombre, p.ej. 'FTB Q4-26',
aparece como sufijo) y en la columna 'Reference prices.1' el precio de referencia D del dia.
"""

import io
import logging
import re

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _url(producto, instrumento, fecha):
    return (
        f"{config.OMIP_BASE}?date={fecha:%Y-%m-%d}"
        f"&product={producto}&zone={config.OMIP_ZONE}&instrument={instrumento}"
    )


def _precios_fecha(producto, instrumento, fecha):
    """Devuelve dict {madurez: precio} para una fecha dada, parseando el HTML."""
    url = _url(producto, instrumento, fecha)
    log.info("Descargando OMIP %s %s (%s)", producto, instrumento, fecha.date())
    resp = requests.get(url, timeout=90, headers=HEADERS)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"OMIP no disponible para {fecha.date()} (HTTP {resp.status_code})"
        )

    try:
        tablas = pd.read_html(io.StringIO(resp.text))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"No se pudieron parsear las tablas OMIP: {e}")

    resultado = {}
    re_contrato = re.compile(rf"{instrumento}\s+([\w\-/ ]+?)$")
    for tabla in tablas:
        if "Unnamed: 0" not in tabla.columns or "Reference prices.1" not in tabla.columns:
            continue
        contratos = tabla["Unnamed: 0"].astype(str)
        precios = tabla["Reference prices.1"]
        for idx in range(len(contratos)):
            raw = contratos.iloc[idx]
            if not isinstance(raw, str):
                continue
            texto = raw.strip()
            if not texto:
                continue
            m = re_contrato.search(texto)
            if not m:
                continue
            madurez = m.group(1).strip()
            precio = precios.iloc[idx]
            if isinstance(precio, (int, float)) or _es_numero(str(precio)):
                try:
                    resultado[madurez] = float(str(precio).replace(",", "."))
                except ValueError:
                    pass
    return resultado


def _es_numero(s):
    s = s.strip().strip("\u20ac").strip()
    if s in ("n.a.", "nan", "", "None"):
        return False
    return bool(re.match(r"^-?\d+(\.\d+)?$", s.replace(",", ".")))


def _precio_contrato(precios, codigo_madurez):
    """Busca el codigo de madurez (p. ej. 'Q4-26') en el dict de precios.

    Devuelve el precio o None.
    """
    if codigo_madurez is None:
        return None
    if codigo_madurez in precios:
        return precios[codigo_madurez]
    # fallback: coincidencia parcial
    for k, v in precios.items():
        if codigo_madurez.replace("/", "") == k.replace("/", ""):
            return v
    return None


def _acumular_csv(csv, contratos, producto, instrumento, fecha):
    """Descarga y anade la fila del dia al CSV de historicos.

    Devuelve (dataframe_historico, dict valor_actual_por_contrato).
    """
    fecha = pd.Timestamp(fecha).normalize()
    if csv.exists():
        hist = pd.read_csv(csv)
        hist["fecha"] = pd.to_datetime(hist["fecha"])
        fechas = set(hist["fecha"].dt.date)
    else:
        hist = pd.DataFrame()

    precios = None
    if fecha.date() not in fechas:
        try:
            precios = _precios_fecha(producto, instrumento, fecha)
        except (requests.HTTPError, ValueError) as e:
            log.warning("No se acumulo OMIP %s %s: %s", producto, instrumento, e)

    if precios is not None:
        fila = {"fecha": pd.Timestamp(fecha.date())}
        for etiqueta, codigo, col in contratos:
            fila[col] = _precio_contrato(precios, codigo)
            act = _precio_contrato(precios, codigo)
            log.info(
                "OMIP %s %s: %s = %s", producto, instrumento, etiqueta,
                act if act is not None else "n.d.",
            )
        nuevo = pd.DataFrame([fila])
        hist = pd.concat([hist, nuevo], ignore_index=True)
        hist = hist.drop_duplicates(subset=["fecha"], keep="last")
        hist = hist.sort_values("fecha").reset_index(drop=True)
        hist.to_csv(csv, index=False)

    # valores actuales (ultima fecha con datos)
    actuales = {}
    if len(hist) > 0:
        ultima = hist.iloc[-1]
        for etiqueta, codigo, col in contratos:
            v = ultima.get(col)
            actuales[etiqueta] = float(v) if pd.notna(v) else None
    else:
        for etiqueta, codigo, col in contratos:
            actuales[etiqueta] = None
    return hist, actuales


def acumular_electricidad(fecha):
    """Acumula futuros electricos y devuelve (historico, actuales)."""
    return _acumular_csv(
        config.CSV_OMIP_ELEC, config.CONTRATOS_ELEC,
        config.OMIP_PRODUCT_ELEC, config.OMIP_INSTRUMENT_ELEC, fecha,
    )


def acumular_gas(fecha):
    """Acumula futuros de gas y devuelve (historico, actuales)."""
    return _acumular_csv(
        config.CSV_OMIP_GAS, config.CONTRATOS_GAS,
        config.OMIP_PRODUCT_GAS, config.OMIP_INSTRUMENT_GAS, fecha,
    )