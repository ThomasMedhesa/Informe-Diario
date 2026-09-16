"""Envío del informe diario por correo vía Outlook COM (pywin32).

Usa la cuenta autenticada en Outlook (sin contraseña) y envía un correo por
destinatario a la lista de contactos definida en config.
"""

import logging
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

import config
from modulos.contactos import leer_contactos  # noqa: F401 (re-export)

log = logging.getLogger(__name__)


def _normalizar_correo(valor):
    """Limpia un valor de celda a su forma de correo o None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    return texto.lower()


def _imagenes_locales(html):
    """Lista de rutas absolutas de las imagenes locales que referencia la firma.

    Las firmas de Outlook guardan las imagenes con rutas relativas
    (p. ej. "Atenci\u00f3n%20al%20Cliente..._archivos/image001.jpg") respecto a
    config.FIRMAS_DIR. Devuelve listas unicas con la ruta absoluta a cada una.
    """
    rutas = []
    for match in re.finditer(r'(src|background)\s*=\s*"([^"]*)"', html, re.I):
        valor = match.group(2)
        if _es_recurso_externo(valor):
            continue
        ruta = Path(urllib.parse.unquote(valor))
        if not ruta.is_absolute():
            ruta = config.FIRMAS_DIR / ruta
        if ruta.exists() and ruta not in rutas:
            rutas.append(ruta)
    return rutas


def _es_recurso_externo(valor):
    """True si el recurso no es un archivo local relativo (URL, cid, ancla...)."""
    v = valor.strip().lower()
    if not v:
        return True
    if v.startswith(("http:", "https:", "cid:", "file:", "data:", "//", "#")):
        return True
    return False


_PROPTAG_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"


def _incrustar_imagenes(mail, html, imagenes):
    """Adjunta las imagenes como inline (Content-ID) y devuelve el HTML con cid:.

    Debe llamarse antes de asignar mail.HTMLBody: Outlook enlaza las referencias
    ``cid:`` con los adjuntos que ya tengan su Content-ID asignado.
    """
    cuerpo = html
    for i, ruta in enumerate(imagenes):
        cid = f"firma_img_{i}"
        adj = mail.Attachments.Add(str(ruta))
        adj.PropertyAccessor.SetProperty(_PROPTAG_CONTENT_ID, cid)
        cuerpo = re.sub(
            r'(src|background)\s*=\s*"([^"]*)"',
            lambda m, n=cid, ruta_local=ruta: f'{m.group(1)}="cid:{n}"'
            if ruta_local == _resolver_local(m.group(2)) else m.group(0),
            cuerpo,
            flags=re.IGNORECASE,
        )
    return cuerpo


def _resolver_local(valor):
    ruta = Path(urllib.parse.unquote(valor))
    if not ruta.is_absolute():
        ruta = config.FIRMAS_DIR / ruta
    return ruta


def _firma_html():
    """Devuelve el HTML de la firma de Outlook o una cadena vacía."""
    nombre = config.NOMBRE_FIRMA + ".htm"
    ruta = config.FIRMAS_DIR / nombre
    if not ruta.exists():
        log.warning("No existe la firma %s", nombre)
        return ""

    datos = ruta.read_bytes()
    # El HTML firmado por Outlook suele ser UTF-8; fallback a windows-1252
    for codif in ("utf-8", "windows-1252"):
        try:
            html = datos.decode(codif)
            break
        except UnicodeDecodeError:
            continue
    else:
        log.warning("No se pudo decodificar la firma %s", nombre)
        return ""

    return html


def es_dia_laborable():
    """True de lunes a viernes (0-4)."""
    return datetime.today().weekday() < 5


def enviar_informe(pdf, contactos):
    """Envía el PDF adjunto a cada destinatario con la cuenta configurada."""
    import win32com.client  # import tardío: solo en Windows con Outlook

    if not contactos:
        log.warning("No hay destinatarios, se omite el envío")
        return 0

    app = win32com.client.Dispatch("Outlook.Application")
    ns = app.GetNamespace("MAPI")

    cuenta = None
    for acc in ns.Accounts:
        if acc.SmtpAddress.lower() == config.CUENTA_ENVIO.lower():
            cuenta = acc
            break
    if cuenta is None:
        log.warning("Cuenta %s no encontrada, se usará la cuenta por defecto",
                    config.CUENTA_ENVIO)

    firma = _firma_html()
    imagenes = _imagenes_locales(firma)
    if imagenes:
        log.info("Imágenes de la firma (%d): %s", len(imagenes),
                 ", ".join(p.name for p in imagenes))
    adjunto = Path(pdf)
    enviados = 0

    for correo in contactos:
        mail = app.CreateItem(0)  # 0 = olMailItem
        if cuenta is not None:
            mail.SendUsingAccount = cuenta
        mail.To = correo
        mail.Subject = config.ASUNTO
        cuerpo = _incrustar_imagenes(mail, config.CUERPO + "<br><br>" + firma,
                                     imagenes)
        mail.HTMLBody = cuerpo
        mail.Attachments.Add(str(adjunto))
        mail.Send()
        enviados += 1
        log.info("Enviado a %s", correo)

    return enviados