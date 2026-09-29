"""Generacion de graficos (Plotly + Kaleido) usados por el informe PDF.

NOTA: este archivo usa caracteres ASCII con escapes unicode (\\uXXXX) para
evitar problemas de codificacion en otros entornos.
"""

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import config
from modulos import contratos_omip

log = logging.getLogger(__name__)


def _num(valor, decimal=1):
    """Numero con coma decimal y punto como separador de miles."""
    s = f"{valor:,.{decimal}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

COLOR_PRINCIPAL = "#1a5276"
COLOR_SECUNDARIO = "#c0392b"
COLOR_GAS = "#1e8449"
COLOR_TERCIARIO = "#8e44ad"
COLOR_CUARTO = "#d68910"

FUENTE = "Calibri"
GRIS_TEXTO = "#2c3e50"
GRIS_GRILLA = "#d5d8dc"
FONDO_PLOT = "#fafbfc"
RELLENO_AZUL = "rgba(26,82,118,0.10)"
RELLENO_VERDE = "rgba(30,132,73,0.08)"

# Aspectos de exportacion (coinciden con la insercion en el PDF)
ANCHO_GRANDE, ALTO_GRANDE = 1050, 935       # paginas 2 y 4 (a proporca 1.12)
ANCHO_MIN, ALTO_MIN = 760, 651             # minigraficos paginas 3 y 5 (1.17)
ESCALA = 2


def _aplicar_layout(fig, titulo, color, ancho, alto, xlabel=None,
                    ylabel=None, eje_fechas=False, dtick_ms=None,
                    tam_titulo=22, tam_texto=16):
    """Aplica el tema corporativo comun a un grafico de Plotly."""
    xaxis = dict(gridcolor=GRIS_GRILLA, gridwidth=0.6, zeroline=False,
                 linecolor=GRIS_GRILLA, showline=True, ticks="outside",
                 tickcolor=GRIS_GRILLA, ticklen=4,
                 title=dict(text=xlabel or "", font=dict(size=tam_texto + 1)),
                 tickfont=dict(size=tam_texto - 2),
                 automargin=True)
    yaxis = dict(gridcolor=GRIS_GRILLA, gridwidth=0.6, zeroline=False,
                 linecolor=GRIS_GRILLA, showline=True, ticks="outside",
                 tickcolor=GRIS_GRILLA, ticklen=4,
                 title=dict(text=ylabel or "", font=dict(size=tam_texto + 1)),
                 tickfont=dict(size=tam_texto - 2),
                 automargin=True)
    if eje_fechas:
        xaxis["tickformat"] = "%d/%m/%Y"
        if dtick_ms:
            xaxis["tickmode"] = "linear"
            xaxis["dtick"] = dtick_ms
    fig.update_layout(
        template="none",
        title=dict(text=titulo, x=0.5, font=dict(size=tam_titulo, color=color,
                                                  family=FUENTE)),
        font=dict(family=FUENTE, size=tam_texto, color=GRIS_TEXTO),
        paper_bgcolor="white",
        plot_bgcolor=FONDO_PLOT,
        margin=dict(l=60, r=30, t=60, b=55),
        width=ancho,
        height=alto,
        xaxis=xaxis,
        yaxis=yaxis,
    )


def _guardar(fig, ruta, ancho, alto):
    """Exporta la figura a PNG de alta resolucion via Kaleido."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(str(ruta), width=ancho, height=alto, scale=ESCALA)
    log.info("Grafico generado: %s", ruta)
    return ruta


def grafico_horario_omie(df_omie, fecha_entrega):
    """Curva de precio marginal horario (sistema espanol) de un dia."""
    fecha_entrega = pd.Timestamp(fecha_entrega)
    dia = df_omie[df_omie["fecha"].dt.date == fecha_entrega.date()]
    if dia.empty:
        log.warning("Sin datos horarios OMIE para %s", fecha_entrega.date())
        return None

    horas = dia["hora"].astype(int).values
    precios = dia["precio_es"].values
    media = float(np.mean(precios))
    idx_max = int(np.argmax(precios))
    idx_min = int(np.argmin(precios))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=horas, y=precios, mode="lines+markers",
        name="Precio marginal ES",
        line=dict(color=COLOR_PRINCIPAL, width=3),
        marker=dict(size=7, color=COLOR_PRINCIPAL,
                    line=dict(color="white", width=1.5)),
        fill="tozeroy", fillcolor=RELLENO_AZUL,
        hovertemplate="Hora %{x}:00<extra></extra>%{y:.2f} \u20ac/MWh",
    ))
    fig.add_hline(
        y=media, line=dict(color=COLOR_SECUNDARIO, width=1.2, dash="dash"),
        annotation_text=f"Media: {_num(media)} \u20ac/MWh",
        annotation_position="top right",
    )
    fig.add_annotation(
        x=int(horas[idx_max]), y=float(precios[idx_max]),
        text=_num(float(precios[idx_max])), showarrow=False, yshift=14,
        font=dict(size=18, color=COLOR_SECUNDARIO, family=FUENTE),
        bgcolor="white", bordercolor=COLOR_SECUNDARIO,
        borderwidth=1.2, borderpad=2,
    )
    fig.add_annotation(
        x=int(horas[idx_min]), y=float(precios[idx_min]),
        text=_num(float(precios[idx_min])), showarrow=False, yshift=-16,
        font=dict(size=18, color=COLOR_PRINCIPAL, family=FUENTE),
        bgcolor="white", bordercolor=COLOR_PRINCIPAL,
        borderwidth=1.2, borderpad=2,
    )
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 25)),
                     range=[0.5, 24.5])
    _aplicar_layout(
        fig,
        f"Precio horario del mercado diario de electricidad \u2014 "
        f"{fecha_entrega.date():%d/%m/%Y}",
        COLOR_PRINCIPAL, ANCHO_GRANDE, ALTO_GRANDE,
        xlabel="Hora", ylabel="Precio (\u20ac/MWh)",
        tam_titulo=28, tam_texto=18,
    )
    ruta = config.DATOS_DIR / "grafico_horario_omie.png"
    return _guardar(fig, ruta, ANCHO_GRANDE, ALTO_GRANDE)


def grafico_evolucion(hist, columnas, titulo, ruta, color=COLOR_PRINCIPAL):
    """Evolucion temporal de una serie de precios (linea + marcadores).

    ``columnas`` puede ser una lista de nombres de columna. Se dibuja la
    primera que tenga al menos 2 valores no nulos en el historico. El color
    recibido se aplica tanto a la linea como al titulo del minigrafico.
    """
    if hist is None or hist.empty:
        log.warning("Sin historico para %s", titulo)
        return None

    if isinstance(columnas, str):
        columnas = [columnas]

    fig = go.Figure()
    dibujado = False
    for col in columnas:
        if col not in hist.columns:
            continue
        serie = hist[["fecha", col]].dropna()
        if serie.empty or len(serie) < 2:
            continue
        fig.add_trace(go.Scatter(
            x=serie["fecha"], y=serie[col], mode="lines+markers",
            name=col,
            line=dict(color=color, width=2.8),
            marker=dict(size=7, color=color,
                        line=dict(color="white", width=1.5)),
            hovertemplate="%{x|%d/%m/%Y}<extra></extra>%{y:.2f} \u20ac/MWh",
        ))
        dibujado = True

    if not dibujado:
        log.warning("Sin datos suficientes para grafico: %s", titulo)
        return None

    fechas = fig.data[0].x
    dias = (fechas.max() - fechas.min()) / np.timedelta64(1, "D")
    dtick_ms = dias * 86400000 / 7

    _aplicar_layout(fig, titulo, color, ANCHO_MIN, ALTO_MIN,
                    xlabel="Fecha", ylabel="Precio \u20ac/MWh", eje_fechas=True,
                    dtick_ms=dtick_ms,
                    tam_titulo=24, tam_texto=16)
    return _guardar(fig, ruta, ANCHO_MIN, ALTO_MIN)


def graficos_electricidad(hist_elec, carpeta, contratos):
    """Lista de rutas PNG, una por grafico de evolucion de electricidad.

    ``contratos`` es la ventana de contratos activa (ver contratos_omip.py).
    El orden de la lista coincide con la colocacion en el PDF:
    sup.izq, sup.der, inf.izq, inf.der.
    """
    return _mini_graficos(hist_elec, carpeta, contratos, "evol_elec_")


def graficos_gas_futuros(hist_gas, carpeta, contratos):
    """Lista de rutas PNG, una por grafico de evolucion de gas."""
    return _mini_graficos(hist_gas, carpeta, contratos, "evol_gas_")


def _mini_graficos(hist, carpeta, contratos, prefijo):
    """Dibuja los minigraficos de la ventana y devuelve sus rutas."""
    rutas = []
    for i, (titulo, columna, color) in enumerate(contratos_omip.series_graficos(contratos, hist)):
        ruta = carpeta / f"{prefijo}{i}.png"
        imagen = grafico_evolucion(hist, columna, titulo, ruta, color=color)
        if imagen:
            rutas.append(imagen)
    return rutas


def grafico_mibgas_largo(hist_mibgas, carpeta):
    """Evolucion del precio de gas MIBGAS: ultimos 5 anos."""
    if hist_mibgas is None or hist_mibgas.empty:
        return None

    corte = hist_mibgas["fecha"].max() - pd.DateOffset(years=5)
    df = hist_mibgas[hist_mibgas["fecha"] >= corte].copy()
    if df.empty:
        df = hist_mibgas.copy()

    ruta = carpeta / "evol_mibgas.png"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["fecha"], y=df["precio"], mode="lines",
        name="Precio MIBGAS",
        line=dict(color=COLOR_GAS, width=2),
        fill="tozeroy", fillcolor=RELLENO_VERDE,
        hovertemplate="%{x|%d/%m/%Y}<extra></extra>%{y:.2f} \u20ac/MWh",
    ))
    _aplicar_layout(
        fig,
        "Evoluci\u00f3n del precio del gas natural MIBGAS (PVB)",
        COLOR_GAS, ANCHO_GRANDE, ALTO_GRANDE,
        xlabel="Fecha", ylabel="Precio \u20ac/MWh", eje_fechas=True,
        tam_titulo=28, tam_texto=18,
    )
    return _guardar(fig, ruta, ANCHO_GRANDE, ALTO_GRANDE)