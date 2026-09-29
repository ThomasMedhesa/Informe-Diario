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
from modulos import contratos_omip

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


def _acumular_csv(csv, mercado, producto, instrumento, fecha):
    """Descarga y anade la fila del dia al CSV de historicos.

    La ventana de contratos se deduce de lo que publica OMIP ese dia (ver
    modulos/contratos_omip.py); si no se puede consultar, se reutiliza la
    ultima ventana guardada y todos sus contratos quedaran sin precio, de modo
    que el control de calidad los marque como faltantes.

    Devuelve (dataframe_historico, dict valor_actual_por_etiqueta,
    lista_de_contratos).
    """
    fecha = pd.Timestamp(fecha).normalize()
    if csv.exists():
        hist = pd.read_csv(csv)
        hist["fecha"] = pd.to_datetime(hist["fecha"])
        fechas = set(hist["fecha"].dt.date)
    else:
        hist = pd.DataFrame()

    cache = contratos_omip.cargar_cache()
    ventana_cache = cache.get(mercado, [])
    ya_acumulado = fecha.date() in fechas

    # Si la fecha ya estaba acumulada y la ventana esta guardada no hace falta
    # volver a preguntar a OMIP. Si falta la ventana guardada (primera
    # ejecucion tras un cambio, o cache borrada) se consulta igualmente: hace
    # falta para saber que contratos mostrar y para no arrastrar una ventana
    # obsoleta.
    consulta_omip = not (ya_acumulado and ventana_cache)
    precios = None
    if consulta_omip:
        try:
            precios = _precios_fecha(producto, instrumento, fecha)
        except (requests.HTTPError, ValueError) as e:
            log.warning("No se acumulo OMIP %s %s: %s", producto, instrumento, e)

    if precios:
        contratos = contratos_omip.resolver(precios)
        contratos_omip.guardar_ventana(mercado, contratos, cache)
    else:
        if not ventana_cache:
            ventana_cache = contratos_omip.ventana_desde_historico(hist)
        if not ventana_cache:
            raise ValueError(
                f"No hay datos de OMIP para {fecha.date()} ni ventana de "
                f"contratos guardada para {mercado}"
            )
        contratos = list(ventana_cache)
        if ya_acumulado and not consulta_omip:
            log.info("OMIP %s: la fecha %s ya estaba acumulada", mercado, fecha.date())
        else:
            # Sin la fila de hoy no hay precio de hoy para ningun contrato: se
            # dejan todos a None para que el control de calidad bloquee el
            # envio, en vez de mandar precios de un dia anterior.
            log.warning(
                "OMIP %s: sin datos para %s; se bloquea el envio. Ventana "
                "mantenida con %d contratos", mercado, fecha.date(), len(contratos)
            )

    if precios:
        fila = {"fecha": pd.Timestamp(fecha.date())}
        for etiqueta, codigo, col in contratos:
            precio = _precio_contrato(precios, codigo)
            fila[col] = precio
            log.info("OMIP %s: %s = %s", mercado, etiqueta,
                     precio if precio is not None else "n.d.")
        nuevo = pd.DataFrame([fila])
        hist = pd.concat([hist, nuevo], ignore_index=True)
        hist = hist.drop_duplicates(subset=["fecha"], keep="last")
        hist = hist.sort_values("fecha").reset_index(drop=True)
        hist.to_csv(csv, index=False)

    # Valores actuales. Solo son validos si la fila de hoy (recien descargada o
    # ya acumulada) contiene los precios de la ventana vigente.
    precios_de_hoy = bool(precios) or (ya_acumulado and not consulta_omip)
    actuales = {}
    if precios_de_hoy:
        ultima = hist.iloc[-1] if len(hist) > 0 else None
        for etiqueta, _, col in contratos:
            v = None if ultima is None else ultima.get(col)
            actuales[etiqueta] = float(v) if pd.notna(v) else None
    else:
        for etiqueta, _, _ in contratos:
            actuales[etiqueta] = None
    return hist, actuales, contratos


def acumular_electricidad(fecha):
    """Acumula futuros electricos.

    Devuelve (historico, valores_actuales, contratos_de_la_ventana).
    """
    return _acumular_csv(
        config.CSV_OMIP_ELEC, "electricidad",
        config.OMIP_PRODUCT_ELEC, config.OMIP_INSTRUMENT_ELEC, fecha,
    )


def acumular_gas(fecha):
    """Acumula futuros de gas.

    Devuelve (historico, valores_actuales, contratos_de_la_ventana).
    """
    return _acumular_csv(
        config.CSV_OMIP_GAS, "gas",
        config.OMIP_PRODUCT_GAS, config.OMIP_INSTRUMENT_GAS, fecha,
    )