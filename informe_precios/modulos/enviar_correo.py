"""Envío del informe diario por correo vía Outlook COM (pywin32).

Usa la cuenta autenticada en Outlook (sin contraseña) y envía un correo por
destinatario a la lista de contactos definida en config.

Pensado para listas largas (cientos de destinatarios): el envío va por lotes
para no chocar con los límites de mensajes por minuto del servidor, un
destinatario que falle no impide que el resto reciba el informe, y al terminar
se avisa por correo de a quién no le llegó.
"""

import logging
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import config
from modulos.contactos import leer_contactos  # noqa: F401 (re-export)

log = logging.getLogger(__name__)

# Comprobación barata de que una dirección tiene forma de correo. No consulta
# el directorio ni Exchange: solo evita que una fila corrupta del Excel llegue a
# Outlook, que al no resolverla puede dejar una ventana de error abierta.
_RE_CORREO = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


@dataclass
class ResultadoEnvio:
    """Resultado de un envío: quién ha recibido el informe y quién no."""

    total: int
    enviados: int
    fallidos: list = field(default_factory=list)

    @property
    def completo(self):
        return not self.fallidos


def _abrir_outlook():
    """Instancia de Outlook con la que se construyen y mandan los mensajes.

    No hay forma de desactivar los avisos de Outlook por COM (``Application``
    no tiene ``DisplayAlerts``, esa propiedad es de Word y Excel). El envío
    automatizado no abre ventanas de error: si un destinatario falla, ``Send``
    lanza una excepción y el envío continua con el siguiente. El único aviso
    interactivo que queda es el de "destinatario externo" de la configuracion
    de confianza de Outlook, que se desactiva a mano en
    Archivo > Opciones > Centro de confianza de Microsoft Office > Contenido
    externo (solo salta si la lista incluye direcciones de fuera).
    """
    import win32com.client  # import tardío: solo en Windows con Outlook

    return win32com.client.Dispatch("Outlook.Application")


def _cuenta(ns):
    """Cuenta de envío configurada, o None si no está en el perfil de Outlook."""
    for acc in ns.Accounts:
        if acc.SmtpAddress.lower() == config.CUENTA_ENVIO.lower():
            return acc
    log.warning("Cuenta %s no encontrada, se usará la cuenta por defecto",
                config.CUENTA_ENVIO)
    return None


def _descartar(mail):
    """Borra un mensaje a medio construir para que no quede en borradores."""
    if mail is None:
        return
    try:
        mail.Delete()
    except Exception:  # noqa: BLE001
        pass


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


def enviar_alerta_datos_faltantes(fecha_hoy, faltan):
    """Envía un correo de aviso interno cuando el informe no se envió por
    tener datos incompletos. Devuelve True si se envió."""

    lineas = "<br>".join(f"&bull; <b>{f['nombre']}</b>" for f in faltan)
    cuerpo = (
        "<p>El informe del d\u00eda <b>{fecha:%d/%m/%Y}</b> NO se ha enviado "
        "autom\u00e1ticamente porque faltan datos:</p>"
        "<p>{lineas}</p>"
        "<p>Completa los datos manualmente desde la aplicaci\u00f3n web y "
        "env\u00eda el informe.</p>"
    ).format(fecha=fecha_hoy, lineas=lineas)

    app = _abrir_outlook()
    cuenta = _cuenta(app.GetNamespace("MAPI"))

    mail = app.CreateItem(0)  # 0 = olMailItem
    if cuenta is not None:
        mail.SendUsingAccount = cuenta
    mail.To = config.ALERTA_DESTINO
    mail.Subject = config.ASUNTO_ALERTA
    mail.HTMLBody = cuerpo
    mail.Send()
    log.info("Alerta enviada a %s (%d faltantes)",
             config.ALERTA_DESTINO, len(faltan))
    return True


def enviar_alerta_envio_fallidos(fecha, fallidos):
    """Avisa al responsable de que el informe no llegó a ciertos destinatarios.

    El aviso lo manda el propio envío (no el que lo llama) para que las dos
    vías de envío, la programada y la manual, avisen igual. Devuelve True si se
    envió.
    """
    if not fallidos:
        return False

    fecha = fecha if fecha is not None else datetime.now()
    lineas = "<br>".join(f"&bull; {c}" for c in fallidos)
    cuerpo = (
        "<p>El informe del d\u00eda <b>{fecha:%d/%m/%Y}</b> se ha generado y "
        "enviado, pero <b>no ha llegado</b> a estos destinatarios:</p>"
        "<p>{lineas}</p>"
        "<p>Revisa que las direcciones sigan siendo correctas. Si el fallo es "
        "de car\u00e1cter temporal (el servidor de correo rechazando env\u00edos "
        "o la direcci\u00f3n en lista de bloqueados), reenv\u00eda el informe "
        "desde la aplicaci\u00f3n web.</p>"
    ).format(fecha=fecha, lineas=lineas)

    app = _abrir_outlook()
    cuenta = _cuenta(app.GetNamespace("MAPI"))

    mail = app.CreateItem(0)  # 0 = olMailItem
    if cuenta is not None:
        mail.SendUsingAccount = cuenta
    mail.To = config.ALERTA_DESTINO
    mail.Subject = config.ASUNTO_ALERTA_ENVIO
    mail.HTMLBody = cuerpo
    mail.Send()
    log.info("Aviso de destinatarios fallidos enviado a %s (%d): %s",
             config.ALERTA_DESTINO, len(fallidos), ", ".join(fallidos))
    return True


def enviar_informe(pdf, contactos, fecha=None):
    """Envía el PDF adjunto a cada destinatario con la cuenta configurada.

    El envío es secuencial y se hace por lotes (``config.ENVIO_LOTE``) con una
    pausa entre ellos, para no superar el límite de mensajes por minuto del
    servidor de correo. Antes de mandar nada se comprueba que la dirección tenga
    formato de correo; los destinatarios que no lo tienen se saltan sin llamar a
    Outlook. Un destinatario que falle no corta el envío de los demás: se anota
    y al final se avisa por correo.

    ``fecha`` solo se usa para el aviso de destinatarios fallidos.

    Devuelve un ``ResultadoEnvio``.
    """
    if not contactos:
        log.warning("No hay destinatarios, se omite el envío")
        return ResultadoEnvio(total=0, enviados=0)

    app = _abrir_outlook()
    cuenta = _cuenta(app.GetNamespace("MAPI"))

    firma = _firma_html()
    imagenes = _imagenes_locales(firma)
    if imagenes:
        log.info("Imágenes de la firma (%d): %s", len(imagenes),
                 ", ".join(p.name for p in imagenes))
    adjunto = Path(pdf)
    total = len(contactos)
    enviados = 0
    fallidos = []
    lote = max(1, int(config.ENVIO_LOTE or 1))
    pausa = max(0.0, float(config.ENVIO_PAUSA or 0))

    for n, correo in enumerate(contactos, start=1):
        if pausa and n > 1 and (n - 1) % lote == 0:
            log.info("Pausa de %.0fs tras %d destinatarios (lote de %d)",
                     pausa, n - 1, lote)
            time.sleep(pausa)
        if not _RE_CORREO.match(correo or ""):
            # Dirección mal formada: se salta sin pedirle nada a Outlook.
            log.error("Dirección con formato incorrecto, no se envía: %r", correo)
            fallidos.append(correo)
            continue
        mail = None
        try:
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
        except Exception as e:  # noqa: BLE001
            # Un fallo puntual (dirección inválida, error temporal del servidor)
            # no debe impedir el envío al resto de la lista.
            log.error("No se pudo enviar a %s: %s", correo, e)
            fallidos.append(correo)
            _descartar(mail)
            continue
        enviados += 1
        log.info("Enviado a %s (%d/%d)", correo, n, total)

    log.info("Envío terminado: %d de %d destinatarios", enviados, total)
    if fallidos:
        log.error("Destinatarios sin informe (%d): %s", len(fallidos),
                  ", ".join(fallidos))
        try:
            enviar_alerta_envio_fallidos(fecha, fallidos)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo avisar de los destinatarios fallidos")
    return ResultadoEnvio(total=total, enviados=enviados, fallidos=fallidos)
