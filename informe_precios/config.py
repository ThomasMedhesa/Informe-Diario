"""Configuración central del generador de informe de precios diarios."""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
# BASE_DIR: carpeta donde se resuelve el paquete. Con el ejecutable
# compilado es la carpeta _MEIPASS de PyInstaller, que es donde se empaqueta
# la plantilla web de la interfaz.
BASE_DIR = Path(__file__).resolve().parent

# Archivos que identifican la carpeta de datos del proyecto. Sirven para que el
# ejecutable compilado encuentre la raiz aunque se mueva de sitio.
MARCADORES_RAIZ = (
    "informe_precios/config.py",
    "Contactos Envio Diario.xlsx",
    "salida/ultimo_estado.json",
)


def _buscar_raiz():
    """Localiza la carpeta "Informe Diario" con la que se trabaja.

    Orden de busqueda:
      1. Variable de entorno INFORME_DIARIO_RAIZ (instalaciones moviles).
      2. Desde el codigo fuente: la carpeta padre del paquete.
      3. Desde el .exe: la carpeta del ejecutable y sus dos padre, buscando
         un archivo marcador del proyecto.
      4. Si no hay ninguno, la propia carpeta del ejecutable (copia portable
         que guarda sus datos al lado).
    """
    env = os.environ.get("INFORME_DIARIO_RAIZ")
    if env:
        return Path(env).expanduser().resolve()

    if not getattr(sys, "frozen", False):
        return BASE_DIR.parent

    carpeta = Path(sys.executable).resolve().parent
    for candidata in (carpeta, carpeta.parent, carpeta.parent.parent):
        if any((candidata / m).exists() for m in MARCADORES_RAIZ):
            return candidata
    return carpeta


RAIZ = _buscar_raiz()

DATOS_DIR = RAIZ / "informe_precios" / "datos"
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

# Fallback: pagina publica de resultados (acepta GET con fecha) y TXT que la
# propia pagina enlaza en su atributo data-path.
OMIE_PAGINA = "https://www.omie.es/es/market-results/daily/daily-market/day-ahead-price"
OMIE_HEADERS = {"User-Agent": "Mozilla/5.0"}

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
# La ventana de contratos no se escribe aqui: se deduce cada dia de las
# maturidades que OMIP publica realmente (ver modulos/contratos_omip.py).
# Estos son los limites de cuantos contratos se muestran de cada tipo.
# El gas solo publica 2 contratos anuales, asi que se muestran los 2.
OMIP_N_MENSUALES = 3
OMIP_N_TRIMESTRES = 3
OMIP_N_ANUALES = 3

# Sesiones con precio que necesita un contrato para tener su propio
# minigrafico. Un trimestre recien incorporado tarda estos dias en tener
# historico; hasta entonces su grafico muestra el trimestre anterior.
OMIP_PUNTOS_MINIMOS = 2

# Ultima ventana de contratos resuelta, para poder reutilizarla si un dia
# OMIP no esta disponible.
OMIP_CONTRATOS_JSON = SALIDA_DIR / "omip_contratos.json"

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
FIRMAS_DIR = Path(os.environ.get("APPDATA", str(RAIZ))) / "Microsoft" / "Signatures"

# ---------------------------------------------------------------------------
# Aplicacion de escritorio (lanzador)
# ---------------------------------------------------------------------------
SERVIDOR_HOST = "127.0.0.1"
SERVIDOR_PUERTO = 8000

# ---------------------------------------------------------------------------
# Env\u00edo programado (tarea de Windows creada desde la web)
# ---------------------------------------------------------------------------
TAREA_WINDOWS_NOMBRE = "Informe Diario ENVIO"
HORA_ENVIO = "14:00"

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
