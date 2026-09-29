"""Resolucion dinamica de los contratos de futuros OMIP que se muestran.

La ventana de contratos (meses, trimestres y anos) NO esta escrita en el
codigo: se deduce cada dia de las maturidades que OMIP publica realmente, de
forma que los contratos que caducan desaparecen solos y los nuevos entran sin
que haya que editar nada.

Regla: de cada tipo de madurez se toman las N primeras que publique OMIP
(3 meses, 3 trimestres y 3 anos por defecto). El gas solo publica 2 anos, asi
que se muestran los 2.

Los nombres de columna se generan con el mismo esquema que las columnas ya
existentes en los CSV de historico (BASE_M_Oct-26, BASE_Q4_2026,
BASE_YEAR_2027...), de modo que el historico de cada contrato sigue
acumulandose en su columna.

Los 4 minigraficos de evolucion muestran los 3 trimestres mas recientes que ya
tienen historico suficiente, del mas antiguo al mas reciente, y el ano mas
cercano. Como un trimestre recien incorporado aun no tiene historico, hasta
reunir OMIP_PUNTOS_MINIMOS sesiones ocupa su lugar el trimestre que acaba de
caducar: la pagina mantiene asi 3 trimestres en orden cronologico y sin huecos.

NOTA: este archivo usa escapes unicode (\\uXXXX) en las etiquetas, igual que
config.py, para evitar problemas de codificacion en otros entornos.
"""

import json
import logging
import re

import pandas as pd

import config

log = logging.getLogger(__name__)

# Codigos de madurez tal y como aparecen en el HTML de OMIP.
RE_MES = re.compile(r"^M\s+([A-Za-z]{3})-(\d{2})$")
RE_TRIM = re.compile(r"^Q([1-4])-(\d{2})$")
RE_ANIO = re.compile(r"^YR-(\d{2})$")

# Nombre del mes tal y como lo escribe OMIP, y como se ve en el informe.
MESES = {
    "Jan": "Enero", "Feb": "Febrero", "Mar": "Marzo", "Apr": "Abril",
    "May": "Mayo", "Jun": "Junio", "Jul": "Julio", "Aug": "Agosto",
    "Sep": "Septiembre", "Oct": "Octubre", "Nov": "Noviembre", "Dec": "Diciembre",
}

# Paleta compartida por los 4 minigraficos de evolucion (paginas 3 y 5).
COLORES = ("#1a5276", "#c0392b", "#8e44ad", "#d68910")

# Cuantos trimestres hacia atras se buscan como reserva del 1er minigrafico.
MAX_TRIMESTRES_RERESERVA = 8

ORDEN_TIPOS = (("mes", "OMIP_N_MENSUALES"),
               ("trimestre", "OMIP_N_TRIMESTRES"),
               ("anio", "OMIP_N_ANUALES"))


# ---------------------------------------------------------------------------
# Etiquetas, titulos y claves de columna
# ---------------------------------------------------------------------------

def _etiqueta(tipo, anio, mes=None, trimestre=None):
    if tipo == "mes":
        return f"Base {MESES[mes]} - {anio}"
    if tipo == "trimestre":
        return f"Base {trimestre}\u00ba Trim. - {anio}"
    return f"Base A\u00f1o - {anio}"


def _titulo(tipo, anio, trimestre=None):
    if tipo == "trimestre":
        return f"EVOLUCI\u00d3N PRECIO Q{trimestre} ({trimestre}\u00ba TRIMESTRE {anio})"
    return f"EVOLUCI\u00d3N PRECIO ANUAL ({anio})"


def _columna(tipo, anio, mes=None, trimestre=None):
    if tipo == "mes":
        return f"BASE_M_{mes}-{anio % 100:02d}"
    if tipo == "trimestre":
        return f"BASE_Q{trimestre}_{anio}"
    return f"BASE_YEAR_{anio}"


def trimestre_anterior(codigo):
    """Codigo del trimestre inmediatamente anterior (Q1-27 -> Q4-26)."""
    m = RE_TRIM.match(codigo or "")
    if not m:
        return None
    trimestre, anio = int(m.group(1)), 2000 + int(m.group(2))
    if trimestre == 1:
        return f"Q4-{(anio - 1) % 100:02d}"
    return f"Q{trimestre - 1}-{anio % 100:02d}"


def _trimestre(codigo):
    """Partes de un codigo de trimestre: (codigo, etiqueta, columna, titulo)."""
    m = RE_TRIM.match(codigo or "")
    if not m:
        return None
    trimestre, anio = int(m.group(1)), 2000 + int(m.group(2))
    return (codigo,
            _etiqueta("trimestre", anio, trimestre=trimestre),
            _columna("trimestre", anio, trimestre=trimestre),
            _titulo("trimestre", anio, trimestre=trimestre))


# ---------------------------------------------------------------------------
# Ventana de contratos
# ---------------------------------------------------------------------------

def _candidatos(precios, tipo):
    """Maturidades de un tipo, de mas cercana a mas lejana.

    Devuelve [(codigo, etiqueta, columna, orden)].
    """
    salida = []
    for codigo in precios:
        if tipo == "mes":
            m = RE_MES.match(codigo)
            if m:
                mes = m.group(1).title()
                anio = 2000 + int(m.group(2))
                salida.append((codigo, _etiqueta("mes", anio, mes=mes),
                               _columna("mes", anio, mes=mes),
                               anio * 100 + list(MESES).index(mes)))
        elif tipo == "trimestre":
            m = RE_TRIM.match(codigo)
            if m:
                trimestre, anio = int(m.group(1)), 2000 + int(m.group(2))
                salida.append((codigo, _etiqueta("trimestre", anio, trimestre=trimestre),
                               _columna("trimestre", anio, trimestre=trimestre),
                               anio * 10 + trimestre))
        else:
            m = RE_ANIO.match(codigo)
            if m:
                anio = 2000 + int(m.group(1))
                salida.append((codigo, _etiqueta("anio", anio),
                               _columna("anio", anio), anio))
    salida.sort(key=lambda x: x[3])
    return salida


def resolver(precios):
    """Ventana de contratos a partir del dict de precios de OMIP.

    ``precios`` es el dict {codigo_madurez: precio} que devuelve
    ``descargar_omip._precios_fecha``. Solo se consideran los codigos con
    precio: una madurez que OMIP publica pero no cotiza no entra en la
    ventana y por tanto no bloquea el envio.

    Devuelve [(etiqueta, codigo, columna)] en orden meses -> trimestres -> anos.
    """
    ventana = []
    for tipo, ajuste in ORDEN_TIPOS:
        cuantos = getattr(config, ajuste)
        for codigo, etiqueta, columna, _ in _candidatos(precios, tipo)[:cuantos]:
            ventana.append((etiqueta, codigo, columna))
    return ventana


# ---------------------------------------------------------------------------
# Minigraficos de evolucion
# ---------------------------------------------------------------------------

def _con_datos(columna, hist):
    """True si la columna tiene suficientes sesiones con precio."""
    if hist is None or hist.empty or columna not in hist.columns:
        return False
    return int(hist[columna].notna().sum()) >= config.OMIP_PUNTOS_MINIMOS


def _trimestres_cronologicos(trimestres):
    """Trimestres en orden cronologico, empezando por el mas antiguo.

    Delante de la ventana se encadena el trimestre que acaba de caducar (y los
    anteriores, por si tampoco tuvieran historico), porque el recien incorporado
    aun no lo tiene.
    """
    if not trimestres:
        return []
    anteriores = []
    anterior = trimestre_anterior(trimestres[0][1])
    for _ in range(MAX_TRIMESTRES_RERESERVA):
        if anterior is None:
            break
        partes = _trimestre(anterior)
        if partes:
            anteriores.append(partes)
        anterior = trimestre_anterior(anterior)
    anteriores.reverse()
    ventana = [p for p in (_trimestre(c[1]) for c in trimestres) if p]
    return anteriores + ventana


def series_graficos(contratos, hist):
    """Series definitivas de los 4 minigraficos de evolucion.

    Los 3 primeros son los trimestres mas recientes que ya tienen historico
    suficiente, del mas antiguo al mas reciente, y el 4o el ano mas cercano.

    El trimestre recien incorporado no tiene historico, asi que hasta reunir
    OMIP_PUNTOS_MINIMOS sesiones sigue entrando en su lugar el trimestre que
    acaba de caducar. De ese modo la pagina muestra siempre 3 trimestres, en
    orden cronologico, sin huecos ni repeticiones.

    Devuelve [(titulo, columna, color)].
    """
    trimestres = [c for c in contratos if RE_TRIM.match(c[1] or "")]
    anios = [c for c in contratos if RE_ANIO.match(c[1] or "")]

    con_datos = [p for p in _trimestres_cronologicos(trimestres)
                 if _con_datos(p[2], hist)][-3:]

    series = [(titulo, columna) for _, _, columna, titulo in con_datos]

    if anios:
        anio = 2000 + int(RE_ANIO.match(anios[0][1]).group(1))
        columna = _columna("anio", anio)
        if _con_datos(columna, hist):
            series.append((_titulo("anio", anio), columna))

    return [(titulo, columna, COLORES[i])
            for i, (titulo, columna) in enumerate(series)]


def desde_columna(columna):
    """Codigo de madurez de una clave de columna historico (inverso de _columna)."""
    m = re.match(r"^BASE_M_([A-Za-z]{3})-(\d{2})$", columna or "")
    if m:
        return f"M {m.group(1)}-{m.group(2)}"
    m = re.match(r"^BASE_Q([1-4])_(\d{4})$", columna or "")
    if m:
        return f"Q{m.group(1)}-{int(m.group(2)) % 100:02d}"
    m = re.match(r"^BASE_YEAR_(\d{4})$", columna or "")
    if m:
        return f"YR-{int(m.group(1)) % 100:02d}"
    return None


def ventana_desde_historico(hist):
    """Ultima ventana deducida de las columnas del propio historico.

    Recurso extremo para cuando no hay cache guardada y OMIP no responde: se
    toman las columnas con precio en la ultima fila que tenga alguno. Los
    precios saldran todos a None, de modo que el envio se bloquea, pero el
    informe sigue sabiendo de que contratos hablar.
    """
    if hist is None or len(hist) == 0:
        return []
    con_datos = hist.iloc[::-1].dropna(axis=1, how="all")
    if len(con_datos) == 0:
        return []
    ultima = con_datos.iloc[0]
    precios = {}
    for columna in ultima.index:
        if columna == "fecha" or pd.isna(ultima[columna]):
            continue
        codigo = desde_columna(columna)
        if codigo:
            precios[codigo] = float(ultima[columna])
    return resolver(precios)


# ---------------------------------------------------------------------------
# Cache de la ultima ventana resuelta
# ---------------------------------------------------------------------------
# Si un dia OMIP no esta disponible no se puede resolver la ventana. En ese
# caso se reutiliza la ultima buena (asi el informe sigue hablando de los
# mismos contratos) y, como no hay precios nuevos, todos los contratos de la
# ventana quedan marcados como faltantes: la alerta seguira saltando.


def cargar_cache():
    """Dict {producto: [(etiqueta, codigo, columna)]} de la ultima ejecucion."""
    ruta = config.OMIP_CONTRATOS_JSON
    if not ruta.exists():
        return {}
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("No se pudo leer la ventana de contratos OMIP: %s", ruta.name)
        return {}
    salida = {}
    for producto, filas in (crudo or {}).items():
        limpio = [tuple(f) for f in filas if isinstance(f, list) and len(f) == 3]
        if limpio:
            salida[producto] = limpio
    return salida


def guardar_cache(cache):
    """Persiste la ventana resuelta de hoy (sobrescribe, sin historico)."""
    try:
        config.OMIP_CONTRATOS_JSON.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        log.exception("No se pudo guardar la ventana de contratos OMIP")


def guardar_ventana(mercado, ventana, cache=None):
    """Guarda la ventana de un mercado ('electricidad'/'gas') y la devuelve."""
    destino = dict(cache) if cache else cargar_cache()
    destino[mercado] = [list(c) for c in ventana]
    guardar_cache(destino)
    return destino


def valor_manual(manual, clave, mercado, actual):
    """Valor manual de un contrato, con clave 'ELEC:'/'GAS:' o sin prefijo.

    Sin prefijo se aplica a los dos mercados (compatibilidad con introduce las
    claves antiguas). Con prefijo, solo al mercado indicado.
    """
    if clave in manual:
        return manual[clave]
    clave_mercado = f"{mercado}:{clave}"
    if clave_mercado in manual:
        return manual[clave_mercado]
    return actual
