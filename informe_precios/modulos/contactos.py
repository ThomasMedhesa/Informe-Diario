"""Gestión de la lista de contactos de envío (Excel "Contactos Envio Diario.xlsx").

El Excel es la fuente de verdad: hoja config.CONTACTOS_HOJA, columna B (índice
config.CONTACTOS_COL), cabecera en la fila 4 y destinatarios desde la fila
config.CONTACTOS_FILA_INICIO hacia abajo.
"""

import logging

import openpyxl

import config

log = logging.getLogger(__name__)


def _normalizar_correo(valor):
    """Limpia un valor de celda a su forma de correo o None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    return texto.lower()


def leer_contactos():
    """Lee los correos de la hoja de contactos (columna B desde la fila 5)."""
    ruta = config.CONTACTOS_XLSX
    if not ruta.exists():
        log.warning("No existe %s, no hay destinatarios", ruta.name)
        return []

    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    ws = wb[config.CONTACTOS_HOJA]

    contactos = []
    for fila in ws.iter_rows(min_row=config.CONTACTOS_FILA_INICIO,
                             max_col=config.CONTACTOS_COL):
        correo = _normalizar_correo(fila[config.CONTACTOS_COL - 1].value)
        if correo and correo not in contactos:
            contactos.append(correo)

    wb.close()
    log.info("Destinatarios (%d): %s", len(contactos), ", ".join(contactos))
    return contactos


def _ultima_fila_datos(ws):
    """Última fila con contenido en la columna de contactos (desde la inicial)."""
    ultima = config.CONTACTOS_FILA_INICIO - 1
    for fila in ws.iter_rows(min_row=config.CONTACTOS_FILA_INICIO,
                             max_col=config.CONTACTOS_COL):
        valor = _normalizar_correo(fila[config.CONTACTOS_COL - 1].value)
        if valor:
            ultima = fila[0].row
    return ultima


def guardar_contactos(emails):
    """Sobrescribe la lista de destinatarios en el Excel.

    Conserva la cabecera (fila 4) y el resto del libro. Limpia los sobrantes
    de guardados anteriores. Devuelve la lista normalizada final.
    """
    emails = _depurar_emails(emails)
    ruta = config.CONTACTOS_XLSX

    wb = openpyxl.load_workbook(ruta)
    ws = wb[config.CONTACTOS_HOJA]
    col = config.CONTACTOS_COL

    # Limpiar celdas sobrantes (guardados previos con más filas)
    ultima = _ultima_fila_datos(ws)
    for fila in range(config.CONTACTOS_FILA_INICIO + len(emails), ultima + 1):
        ws.cell(row=fila, column=col).value = None

    for i, correo in enumerate(emails):
        ws.cell(row=config.CONTACTOS_FILA_INICIO + i, column=col).value = correo

    wb.save(ruta)
    log.info("Guardados %d destinatarios en %s", len(emails), ruta.name)
    return emails


def _depurar_emails(emails):
    """Normaliza, elimina vacíos y duplicados de una lista de correos."""
    vistos = []
    for v in emails:
        correo = _normalizar_correo(v)
        if correo and correo not in vistos:
            vistos.append(correo)
    return vistos