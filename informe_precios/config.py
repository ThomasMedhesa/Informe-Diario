"""Configuración central del generador de informe de precios diarios."""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent                 # carpeta informe_precios
RAIZ = BASE_DIR.parent                                    # carpeta "Informe Diario"

DATOS_DIR = BASE_DIR / "datos"
OMIE_DIR = DATOS_DIR / "omie"
OMIP_ELEC_DIR = DATOS_DIR / "omip_elec"
OMIP_GAS_DIR = DATOS_DIR / "omip_gas"
MIBGAS_DIR = DATOS_DIR / "mibgas"

SALIDA_DIR = RAIZ / "salida"

# Históricos Excel existentes (para importación inicial)
HIST_ELEC_XLSX = RAIZ / "Historico_Precios_Cierre_Mercado_Futuros_Energía Eléctrica.xlsx"
HIST_GAS_XLSX = RAIZ / "Historico_Precios_Mercado_Futuros_Gas Natural.xlsx"
HIST_MIBGAS_XLSX = RAIZ / "Historico_Precios_Mercado_MIBGAS.xlsx"

# Archivos CSV de acumulación local
CSV_OMIE = OMIE_DIR / "historico_omie_precios_horarios.csv"
CSV_OMIP_ELEC = OMIP_ELEC_DIR / "historico_omip_electricidad.csv"
CSV_OMIP_GAS = OMIP_GAS_DIR / "historico_omip_gas.csv"
CSV_MIBGAS = MIBGAS_DIR / "historico_mibgas.csv"

# ---------------------------------------------------------------------------
# URLs de las fuentes (públicas, sin login)
# ---------------------------------------------------------------------------
OMIE_BASE = "https://www.omie.es/en/file-download"
OMIE_PARENTS = "marginalpdbc"          # file type: precio marginal

# Reintentos de OMIE: el fichero del día siguiente se publica a hora variable
# (13:20-14:30 aprox.), así que se reintenta tras fallos transitorios.
OMIE_REINTENTOS = 6                    # intentos adicionales tras el primero
OMIE_ESPERA_SEG = 600                  # 10 min entre intentos (~60 min total)

OMIP_BASE = "https://www.omip.pt/en/dados-mercado"

MIBGAS_ANUAL_XLSX = (
    "https://www.mibgas.es/en/file-access/MIBGAS_Data_{year}.xlsx?path=AGNO_{year}/XLS"
)

# ---------------------------------------------------------------------------
# Contratos de futuros OMIP a mostrar (electricidad y gas)
# ---------------------------------------------------------------------------
# Cada contrato: (etiqueta_para_tabla, codigo_madurez_OMIP, columna_historico)
# codigo_madurez_OMIP es el texto que identifica la madurez en el HTML de OMIP
# (p. ej. "M Oct-26", "Q4-26", "Q1-27", "YR-27"). Se busca como substring.
CONTRATOS_ELEC = [
    ("Base Octubre - 2026",   "M Oct-26", "BASE_M_Oct-26"),
    ("Base Noviembre - 2026", "M Nov-26", "BASE_M_Nov-26"),
    ("Base Diciembre - 2026", "M Dec-26", "BASE_M_Dec-26"),
    ("Base 4\u00ba Trim. - 2026", "Q4-26", "BASE_Q4_2026"),
    ("Base 1\u00ba Trim. - 2027", "Q1-27", "BASE_Q1_2027"),
    ("Base 2\u00ba Trim. - 2027", "Q2-27", "BASE_Q2_2027"),
    ("Base A\u00f1o - 2027",  "YR-27",  "BASE_YEAR_2027"),
    ("Base A\u00f1o - 2028",  "YR-28",  "BASE_YEAR_2028"),
    ("Base A\u00f1o - 2029",  "YR-29",  "BASE_YEAR_2029"),
]

CONTRATOS_GAS = [
    ("Base Octubre - 2026",   "M Oct-26", "BASE_M_Oct-26"),
    ("Base Noviembre - 2026", "M Nov-26", "BASE_M_Nov-26"),
    ("Base Diciembre - 2026", "M Dec-26", "BASE_M_Dec-26"),
    ("Base 4\u00ba Trim. - 2026", "Q4-26", "BASE_Q4_2026"),
    ("Base 1\u00ba Trim. - 2027", "Q1-27", "BASE_Q1_2027"),
    ("Base 2\u00ba Trim. - 2027", "Q2-27", "BASE_Q2_2027"),
    ("Base A\u00f1o - 2027",  "YR-27",  "BASE_YEAR_2027"),
    ("Base A\u00f1o - 2028",  "YR-28",  "BASE_YEAR_2028"),
]

# Períodos para los gráficos de evolución (página 3 y 5):
# (título, lista_columnas, color_linea). Cada gráfico usa la primera columna
# de la lista que tenga datos suficientes.
# Orden en pantalla: 1º sup.izq (quarter actual) -> 2º sup.der (siguiente)
#                    -> 3º inf.izq (subsiguiente) -> 4º inf.der (próximo año).
# Electricidad y gas comparten la misma paleta de colores.
_GRAF_COLORES = ["#1a5276", "#c0392b", "#8e44ad", "#d68910"]

GRAFICOS_ELEC = [
    ("EVOLUCI\u00d3N PRECIO Q4 (4\u00ba TRIMESTRE 2026)",
     ["BASE_Q4_2026"], _GRAF_COLORES[0]),
    ("EVOLUCI\u00d3N PRECIO Q1 (1\u00ba TRIMESTRE 2027)",
     ["BASE_Q1_2027"], _GRAF_COLORES[1]),
    ("EVOLUCI\u00d3N PRECIO Q2 (2\u00ba TRIMESTRE 2027)",
     ["BASE_Q2_2027"], _GRAF_COLORES[2]),
    ("EVOLUCI\u00d3N PRECIO ANUAL (2027)",
     ["BASE_YEAR_2027"], _GRAF_COLORES[3]),
]

GRAFICOS_GAS = [
    ("EVOLUCI\u00d3N PRECIO Q4 (4\u00ba TRIMESTRE 2026)",
     ["BASE_Q4_2026"], _GRAF_COLORES[0]),
    ("EVOLUCI\u00d3N PRECIO Q1 (1\u00ba TRIMESTRE 2027)",
     ["BASE_Q1_2027"], _GRAF_COLORES[1]),
    ("EVOLUCI\u00d3N PRECIO Q2 (2\u00ba TRIMESTRE 2027)",
     ["BASE_Q2_2027"], _GRAF_COLORES[2]),
    ("EVOLUCI\u00d3N PRECIO ANUAL (2027)",
     ["BASE_YEAR_2027"], _GRAF_COLORES[3]),
]

# ---------------------------------------------------------------------------
# Identificadores de producto/país para OMIP
# ---------------------------------------------------------------------------
OMIP_PRODUCT_ELEC = "EL"
OMIP_PRODUCT_GAS = "NG"
OMIP_ZONE = "ES"
OMIP_INSTRUMENT_ELEC = "FTB"
OMIP_INSTRUMENT_GAS = "FGF"

# ---------------------------------------------------------------------------
# Nombres de empresa (para portada)
# ---------------------------------------------------------------------------
EMPRESA = ""
TITULO_INFORME = "INFORME DIARIO DE PRECIOS ENERG\u00c9TICOS"

# ---------------------------------------------------------------------------
# Contactos / env\u00edo de correo
# ---------------------------------------------------------------------------
CONTACTOS_XLSX = RAIZ / "Contactos Envio Diario.xlsx"
CONTACTOS_HOJA = "Hoja1"
CONTACTOS_COL = 2
CONTACTOS_FILA_INICIO = 5

CUENTA_ENVIO = "atencionalcliente@medhesa.es"
ASUNTO = "Informe Precio Mercados Energ\u00e9ticos"
CUERPO = (
    '<span style="font-family:Calibri; font-size:11pt; color:#002060;">'
    "Adjuntamos informe de precios de mercados energ\u00e9ticos de hoy "
    "(de aplicaci\u00f3n para ma\u00f1ana)."
    '</span>'
)
NOMBRE_FIRMA = "Atenci\u00f3n al Cliente (atencionalcliente@medhesa.es)"
FIRMAS_DIR = Path(os.environ["APPDATA"]) / "Microsoft" / "Signatures"

# ---------------------------------------------------------------------------
# Env\u00edo programado (tarea de Windows creada desde la web)
# ---------------------------------------------------------------------------
TAREA_WINDOWS_NOMBRE = "Informe Diario ENVIO"
HORA_ENVIO = "14:05"

# ---------------------------------------------------------------------------
# Control de calidad del informe / alertas
# ---------------------------------------------------------------------------
ALERTA_DESTINO = "tbrellenthin@medhesa.es"
ASUNTO_ALERTA = "ALERTA: Informe diario NO enviado (datos incompletos)"
ULTIMO_ESTADO_JSON = SALIDA_DIR / "ultimo_estado.json"

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def asegurar_dirs():
    for d in (DATOS_DIR, OMIE_DIR, OMIP_ELEC_DIR, OMIP_GAS_DIR, MIBGAS_DIR, SALIDA_DIR):
        d.mkdir(parents=True, exist_ok=True)
