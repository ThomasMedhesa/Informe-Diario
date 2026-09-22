"""Ensamblado del informe PDF (layout limpio, 5 paginas A4).

NOTA: este archivo usa exclusivamente caracteres ASCII con escapes unicode
(literal \\uXXXX) para evitar problemas de codificacion en otros entornos.
"""

import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import config

log = logging.getLogger(__name__)

AZUL = colors.HexColor("#1a5276")
AZUL_CLARO = colors.HexColor("#2980b9")
CELESTE = colors.HexColor("#007fcc")
NARANJA = colors.HexColor("#d35400")
VERDE = colors.HexColor("#1e8449")
GRIS = colors.HexColor("#566573")
GRIS_CLARO = colors.HexColor("#f2f3f4")
GRIS_BORDE = colors.HexColor("#d5d8dc")
LINEA = colors.HexColor("#d5d8dc")
FILA_PAR = colors.HexColor("#f8f9f9")
FILA_IMPAR = colors.white

MARGEN = 18 * mm
W = A4[0]
H = A4[1]

# Registro de fuentes Calibri (del sistema Windows)
pdfmetrics.registerFont(TTFont("Calibri", r"C:\Windows\Fonts\calibri.ttf"))
pdfmetrics.registerFont(TTFont("Calibri-Bold", r"C:\Windows\Fonts\calibrib.ttf"))
pdfmetrics.registerFont(TTFont("Calibri-Italic", r"C:\Windows\Fonts\calibrii.ttf"))

FONT = "Calibri"
FONT_BOLD = "Calibri-Bold"

# Logo de empresa (esquina superior derecha de cada pagina)
RUTA_LOGO = config.RAIZ / "LOGO-MEDHESA.jpg"
ALTO_LOGO = 10 * mm
ANCHO_LOGO = ALTO_LOGO * (1018 / 293)          # mantiene proporcion del JPEG (3.47:1)
SEP_LOGO = 10 * mm                             # separacion con el borde superior

# ---------------------------------------------------------------------------
# Estilos / fuentes
# ---------------------------------------------------------------------------
def _estilos():
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("normal", parent=ss["Normal"], fontName=FONT,
                            fontSize=10, leading=14, textColor=colors.HexColor("#2c3e50"))
    titulo = ParagraphStyle("titulo", parent=ss["Title"], fontName=FONT_BOLD,
                            fontSize=20, leading=26, textColor=AZUL, alignment=TA_CENTER,
                            spaceBefore=0, spaceAfter=2)
    subtitulo = ParagraphStyle("subtitulo", parent=ss["Normal"], fontName=FONT,
                               fontSize=11, leading=15, textColor=GRIS, alignment=TA_CENTER)
    seccion = ParagraphStyle("seccion", parent=ss["Heading2"], fontName=FONT_BOLD,
                             fontSize=13, leading=17, textColor=NARANJA,
                             spaceBefore=10, spaceAfter=4)
    seccion_verde = ParagraphStyle("seccion_verde", parent=seccion, textColor=VERDE)
    seccion_celeste = ParagraphStyle("seccion_celeste", parent=seccion, textColor=CELESTE)
    parrafo_kpi = ParagraphStyle("kpi", parent=normal, fontSize=12, leading=17)
    celda_tabla = ParagraphStyle("celda", parent=normal, fontSize=9.5, leading=12)
    celda_h = ParagraphStyle("celdah", parent=celda_tabla, fontName=FONT_BOLD,
                             textColor=colors.white, alignment=TA_CENTER)
    celda_num = ParagraphStyle("celdanum", parent=celda_tabla, alignment=TA_RIGHT)
    celda_num_h = ParagraphStyle("celdanumh", parent=celda_h, alignment=TA_CENTER)
    return dict(normal=normal, titulo=titulo, subtitulo=subtitulo, seccion=seccion,
                seccion_verde=seccion_verde, seccion_celeste=seccion_celeste,
                kpi=parrafo_kpi,
                celda=celda_tabla, celda_h=celda_h, celda_num=celda_num,
                celda_num_h=celda_num_h)


# ---------------------------------------------------------------------------
# Pie de pagina
# ---------------------------------------------------------------------------
def _pintar_logo(canvas):
    """Dibuja el logo de la empresa en la esquina superior derecha."""
    if not RUTA_LOGO.exists():
        return
    x = W - MARGEN - ANCHO_LOGO
    y = H - ALTO_LOGO - SEP_LOGO
    canvas.drawImage(str(RUTA_LOGO), x, y, ANCHO_LOGO, ALTO_LOGO,
                     mask=None, preserveAspectRatio=True)


def _pagina_con_logo(canvas, doc):
    _pintar_logo(canvas)
    _on_page(canvas, doc)


def _on_page(canvas, doc):
    _pintar_logo(canvas)
    canvas.saveState()
    canvas.setFont("Calibri", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawCentredString(W / 2, 9 * mm, f"P\u00e1gina {doc.page}")
    canvas.setStrokeColor(GRIS_BORDE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGEN, 13 * mm, W - MARGEN, 13 * mm)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _num(valor, decimal=2, signo=False):
    """Formatea un número con coma decimal y punto como separador de miles
    (p. ej. 1234.5 -> "1.234,50"). ``signo`` fuerza el signo '+' en positivos."""
    if signo:
        s = f"{valor:+,.{decimal}f}"
    else:
        s = f"{valor:,.{decimal}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(valor, decimal=2):
    return _num(valor, decimal) if valor is not None else "n.d."


def _filtrar_contratos(datos):
    """Filtra contratos que no tengan precio (None) para las tablas."""
    return [(nombre, precio) for nombre, precio in datos if precio is not None]


def _tabla_futuros(datos, estilo, color_cabecera=AZUL, con_orden=True):
    """Tabla de futuros. ``con_orden`` incluye/excluye la columna ORDEN."""
    datos_visibles = _filtrar_contratos(datos)
    if not datos_visibles:
        return Paragraph("No hay datos de precios disponibles.", estilo["normal"])

    cabecera = [
        Paragraph("BASE", estilo["celda_h"]),
        Paragraph("PRECIO [EUR/MWh]", estilo["celda_num_h"]),
    ]
    if con_orden:
        cabecera.append(Paragraph("ORDEN", estilo["celda_num_h"]))
    filas = [cabecera]
    for i, (nombre, precio) in enumerate(datos_visibles, start=1):
        fila = [
            Paragraph(str(nombre), estilo["celda"]),
            Paragraph(_fmt(precio), estilo["celda_num"]),
        ]
        if con_orden:
            fila.append(Paragraph(str(i), estilo["celda_num"]))
        filas.append(fila)

    ancho_tabla = W - 2 * MARGEN
    ancho_precio = 45 * mm
    if con_orden:
        col_anchos = [110 * mm, 45 * mm, ancho_tabla - 155 * mm]
    else:
        col_anchos = [ancho_tabla - ancho_precio, ancho_precio]
    t = Table(filas, colWidths=col_anchos, hAlign="LEFT")
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), color_cabecera),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS_BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(filas)):
        bg = FILA_PAR if i % 2 == 0 else FILA_IMPAR
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))

    t.setStyle(TableStyle(style_cmds))
    return t


# ---------------------------------------------------------------------------
# Paginas
# ---------------------------------------------------------------------------
def _portada(historia, estilo, fecha_entrega, fecha_hoy, precio_omie, precio_mibgas,
             futuros_elec, futuros_gas, precio_mibgas_ant, precio_omie_ant=None):
    # --- Titulo ---
    fecha_texto = Paragraph(
        f"Informe generado el {fecha_hoy:%d/%m/%Y} \u00b7 Datos de entrega {fecha_entrega:%d/%m/%Y}",
        estilo["subtitulo"],
    )
    historia.append(Paragraph(config.TITULO_INFORME, estilo["titulo"]))
    historia.append(Spacer(1, 1 * mm))
    historia.append(fecha_texto)
    historia.append(Spacer(1, 5 * mm))

    # --- Seccion Electricidad ---
    historia.append(Paragraph("ENERG\u00cdA EL\u00c9CTRICA \u2014 Precios futuros OMIP", estilo["seccion_celeste"]))

    if precio_omie is not None:
        camb = ""
        if precio_omie_ant:
            dif = precio_omie - precio_omie_ant
            camb = f" ({_num(dif, 2, signo=True)} \u20ac/MWh vs d\u00eda anterior)"
        historia.append(Paragraph(
            f"<b>Precio medio OMIE para ma\u00f1ana ({fecha_entrega:%d/%m/%Y}):</b> "
            f"<font color='#007fcc'><b>{_fmt(precio_omie)} \u20ac/MWh</b></font>{camb}",
            estilo["kpi"],
        ))
    else:
        historia.append(Paragraph(
            f"Precio medio OMIE para ma\u00f1ana ({fecha_entrega:%d/%m/%Y}): no disponible.",
            estilo["kpi"],
        ))
    historia.append(Spacer(1, 2 * mm))
    historia.append(_tabla_futuros(futuros_elec, estilo, color_cabecera=CELESTE,
                                   con_orden=False))
    historia.append(Spacer(1, 5 * mm))

    # --- Seccion Gas ---
    historia.append(Paragraph("GAS NATURAL \u2014 Precios futuros OMIP", estilo["seccion_verde"]))

    if precio_mibgas is not None:
        camb = ""
        if precio_mibgas_ant:
            dif = precio_mibgas - precio_mibgas_ant
            camb = f" ({_num(dif, 2, signo=True)} \u20ac/MWh vs d\u00eda anterior)"
        historia.append(Paragraph(
            f"<b>Precio de MIBGAS para ma\u00f1ana ({fecha_entrega:%d/%m/%Y}):</b> "
            f"<font color='#1e8449'><b>{_fmt(precio_mibgas)} \u20ac/MWh</b></font>{camb}",
            estilo["kpi"],
        ))
    else:
        historia.append(Paragraph(
            "Precio de MIBGAS: dato a\u00fan no disponible.",
            estilo["kpi"],
        ))
    historia.append(Spacer(1, 2 * mm))
    historia.append(_tabla_futuros(futuros_gas, estilo, color_cabecera=VERDE,
                                   con_orden=False))
    historia.append(PageBreak())


def _con_graficos(historia, estilo, graficos, titulo):
    historia.append(Paragraph(titulo, estilo["titulo"]))
    historia.append(Spacer(1, 4 * mm))
    val = [g for g in graficos if g is not None]
    if not val:
        historia.append(Paragraph("No hay datos suficientes para mostrar gr\u00e1ficos.", estilo["normal"]))
    else:
        grafos_por_pagina = 4
        for pagina_idx in range(0, len(val), grafos_por_pagina):
            bloque = val[pagina_idx:pagina_idx + grafos_por_pagina]
            filas = []
            fila = []
            for g in bloque:
                fila.append(Image(g, width=(W - 2 * MARGEN - 6 * mm) / 2.0,
                                  height=72 * mm))
                if len(fila) == 2:
                    filas.append(fila)
                    fila = []
            if fila:
                filas.append(fila)
            for idx_f, f in enumerate(filas):
                historia.append(Table([f],
                                      colWidths=[(W - 2 * MARGEN) / 2.0] * len(f),
                                      hAlign="CENTER"))
                if idx_f < len(filas) - 1:
                    historia.append(Spacer(1, 5 * mm))
    historia.append(PageBreak())


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def generar_pdf(destino, params):
    """params: dict con datos y rutas de graficos."""
    historia = []
    estilo = _estilos()

    _portada(
        historia, estilo,
        fecha_entrega=params["fecha_entrega"], fecha_hoy=params["fecha_hoy"],
        precio_omie=params["precio_omie"], precio_mibgas=params["precio_mibgas"],
        futuros_elec=params["futuros_elec"], futuros_gas=params["futuros_gas"],
        precio_mibgas_ant=params.get("precio_mibgas_ant"),
        precio_omie_ant=params.get("precio_omie_ant"),
    )

    # Pagina 2: curva horaria
    historia.append(Paragraph("MERCADO DIARIO ELECTRICIDAD (OMIE)", estilo["titulo"]))
    historia.append(Spacer(1, 4 * mm))
    if params.get("grafico_horario"):
        historia.append(Image(params["grafico_horario"],
                              width=W - 2 * MARGEN, height=155 * mm))
    else:
        historia.append(Paragraph("Sin datos horarios disponibles.", estilo["normal"]))
    historia.append(PageBreak())

    # Pagina 3: evolucion futuros electricidad
    _con_graficos(historia, estilo, params["graficos_elec"],
                  "EVOLUCI\u00d3N PRECIO MERCADO FUTUROS ELECTRICIDAD OMIP")

    # Pagina 4: evolucion MIBGAS
    historia.append(Paragraph("EVOLUCI\u00d3N PRECIO GAS NATURAL MIBGAS", estilo["titulo"]))
    historia.append(Spacer(1, 4 * mm))
    if params.get("grafico_mibgas"):
        historia.append(Image(params["grafico_mibgas"],
                              width=W - 2 * MARGEN, height=155 * mm))
    else:
        historia.append(Paragraph("Sin datos MIBGAS disponibles.", estilo["normal"]))
    historia.append(PageBreak())

    # Pagina 5: evolucion futuros gas
    _con_graficos(historia, estilo, params["graficos_gas"],
                  "EVOLUCI\u00d3N PRECIO MERCADO FUTUROS GAS NATURAL OMIP")

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=str(destino.parent))
    os.close(tmp_fd)
    try:
        doc = SimpleDocTemplate(tmp_path, pagesize=A4,
                                leftMargin=MARGEN, rightMargin=MARGEN,
                                topMargin=32 * mm, bottomMargin=18 * mm,
                                title="Informe Precio Diario",
                                author="Sistema Automatico de Precios Energeticos")
        doc.build(historia, onFirstPage=_pagina_con_logo, onLaterPages=_on_page)
        os.replace(tmp_path, str(destino))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    log.info("PDF generado: %s", destino)
    return destino
