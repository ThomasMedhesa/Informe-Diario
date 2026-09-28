# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de la aplicación de escritorio del informe diario.

Genera una carpeta portable "aplicacion/InformeDiario/InformeDiario.exe"
sin ventana de consola. Se compila con:

    pyinstaller InformeDiario.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

RAIZ = Path(SPECPATH).resolve()
PAQUETE = RAIZ / "informe_precios"
ICONO = RAIZ / "informe_precios" / "web" / "informe_diario.ico"

# La plantilla Jinja de la web viaja como dato. En el ejecutable los módulos
# se resuelven en la raíz de _MEIPASS, así que la carpeta debe quedar ahí.
datas = [(str(PAQUETE / "web"), "web")]
binaries = []
hiddenimports = [
    "config",
    "generar_informe",
    "servidor_web",
    "lanzador",
    "modulos",
    "modulos.cargar_historicos",
    "modulos.contactos",
    "modulos.descargar_mibgas",
    "modulos.descargar_omie",
    "modulos.descargar_omip",
    "modulos.enviar_correo",
    "modulos.generar_pdf",
    "modulos.graficos",
    "modulos.programar_tarea",
    "jinja2",
    "werkzeug.serving",
    "encodings.idna",
    # Kaleido v1 delega en choreographer, que se discovery por import normal
    # pero necesita que PyInstaller lo declare para el ejecutable.
    "kaleido",
    "kaleido.executable.kaleido",
    "kaleido.executable.sync_server",
    "kaleido._kaleido_tab",
    "kaleido._utils",
    "choreographer",
    "choreographer.chromium",
    "choreographer.browser_sync",
    "choreographer.protocol",
]

if sys.platform == "win32":
    hiddenimports += [
        "win32com",
        "win32com.client",
        "pythoncom",
        "pywintypes",
    ]

# Plotly trae plantillas de exportacion y kaleido un .js de arranque que no
# se detectan solos.
datas += collect_data_files("plotly")
datas += collect_data_files("kaleido")

a = Analysis(
    [str(PAQUETE / "lanzador.py")],
    pathex=[str(PAQUETE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # El informe solo usa Plotly para exportar PNG: torch, torchvision y scipy
    # son dependencias opcionales que añaden unos 350 MB sin usarse.
    excludes=[
        "matplotlib",
        "pytest",
        "IPython",
        "notebook",
        "torch",
        "torchvision",
        "torchaudio",
        "triton",
        "scipy",
        "numba",
        "PIL.ImageQt",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InformeDiario",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICONO) if ICONO.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InformeDiario",
)
