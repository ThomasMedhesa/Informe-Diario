"""Gestión de la tarea programada de Windows que genera y envía el informe.

La tarea se crea con ``schtasks`` para que se ejecute a diario a una hora
configurable (por defecto 14:00). Ejecuta ``generar_informe.py`` con
``pythonw.exe`` (sin ventana de consola); el propio script ignora sábados y
domingos y lanza Outlook vía COM con la sesión del usuario.
"""

import logging
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import config

log = logging.getLogger(__name__)

RUTA_SCRIPT = Path(__file__).resolve().parents[1] / "generar_informe.py"

_HORA_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")


def _normalizar(texto):
    """Minúsculas y sin acentos para comparar claves de cualquier locale."""
    texto = unicodedata.normalize("NFD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", texto.strip().lower())


def _ruta_pythonw():
    """pythonw.exe si existe (sin consola), si no el python en curso."""
    exe = Path(sys.executable)
    alt = exe.with_name("pythonw.exe")
    return alt if alt.exists() else exe


def _valor_tr():
    """Comando que ejecutará la tarea: pythonw generar_informe.py."""
    return f'"{_ruta_pythonw()}" "{RUTA_SCRIPT}"'


def _run(args):
    """Ejecuta schtasks y devuelve (returncode, salida decodificada)."""
    try:
        proc = subprocess.run(
            ["schtasks", *args],
            capture_output=True, timeout=30,
        )
    except FileNotFoundError as e:
        raise RuntimeError("No se encontró 'schtasks' en el sistema.") from e
    raw = (proc.stdout or b"") + (proc.stderr or b"")
    salida = _decodificar(raw).strip()
    if proc.returncode != 0 and salida:
        log.warning("schtasks %s -> %d: %s", args[0], proc.returncode, salida)
    return proc.returncode, salida


def _decodificar(raw):
    """Decodifica la salida de schtasks intentando varias codificaciones.

    schtasks es una aplicación de consola: escribe con la codepage OEM del
    sistema (en este equipo cp850), no con la ANSI (cp1252).
    """
    for codif in ("cp850", "cp1252", "utf-8"):
        try:
            return raw.decode(codif)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def normalizar_hora(hora):
    """Valida y normaliza una hora a formato HH:MM de 24 h."""
    m = _HORA_RE.match(str(hora or ""))
    if not m:
        raise ValueError("Hora no válida (usa formato HH:MM, p. ej. 14:00)")
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        raise ValueError("Hora no válida (usa formato HH:MM, p. ej. 14:00)")
    return f"{hh:02d}:{mm:02d}"


def crear_tarea(hora):
    """Crea (o recrea) la tarea diaria a la hora indicada."""
    hora = normalizar_hora(hora)
    cod, sal = _run([
        "/Create",
        "/TN", config.TAREA_WINDOWS_NOMBRE,
        "/TR", _valor_tr(),
        "/SC", "DAILY",
        "/ST", hora,
        "/F",
    ])
    if cod != 0:
        raise RuntimeError(sal or "No se pudo crear la tarea")
    log.info("Tarea creada: %s a las %s", config.TAREA_WINDOWS_NOMBRE, hora)


def cambiar_hora(hora):
    """Cambia la hora de ejecución de la tarea existente."""
    hora = normalizar_hora(hora)
    cod, sal = _run(["/Change", "/TN", config.TAREA_WINDOWS_NOMBRE, "/ST", hora])
    if cod != 0:
        raise RuntimeError(sal or "No se pudo cambiar la hora de la tarea")
    log.info("Tarea actualizada a las %s", hora)


def activar():
    """Habilita la tarea (se puede ejecutar)."""
    cod, sal = _run(["/Change", "/TN", config.TAREA_WINDOWS_NOMBRE, "/ENABLE"])
    if cod != 0:
        raise RuntimeError(sal or "No se pudo activar la tarea")


def desactivar():
    """Deshabilita la tarea (conserva la configuración pero no se ejecuta)."""
    cod, sal = _run(["/Change", "/TN", config.TAREA_WINDOWS_NOMBRE, "/DISABLE"])
    if cod != 0:
        raise RuntimeError(sal or "No se pudo desactivar la tarea")


def eliminar_tarea():
    """Elimina la tarea. Devuelve True si existía y se pudo borrar."""
    cod, sal = _run(["/Delete", "/TN", config.TAREA_WINDOWS_NOMBRE, "/F"])
    if cod == 0:
        log.info("Tarea eliminada: %s", config.TAREA_WINDOWS_NOMBRE)
        return True
    return False


def estado_tarea():
    """Consulta el estado de la tarea. Devuelve un dict o None si no existe.

    El texto de schtasks depende del idioma del Windows; se parsean las
    claves en inglés y en español.
    """
    cod, sal = _run(["/Query", "/TN", config.TAREA_WINDOWS_NOMBRE,
                     "/FO", "LIST", "/V"])
    if cod != 0:
        return None

    datos = {}
    for linea in sal.splitlines():
        clave, sep, valor = linea.partition(":")
        if not sep:
            continue
        c = _normalizar(clave)
        v = valor.strip()
        if c in ("taskname", "nombre de tarea"):
            datos["nombre"] = v
        elif c == "status" or (c == "estado" and "estado" not in datos):
            datos["estado"] = v
        elif c in ("next run time", "hora proxima ejecucion",
                   "proxima ejecucion"):
            datos["proxima"] = v
        elif c in ("start time", "hora de inicio"):
            datos["hora"] = v
        elif c in ("scheduled task state", "estado de tarea programada",
                   "estado de la tarea programada"):
            datos["estado_tarea"] = v

    estado = (datos.get("estado_tarea") or datos.get("estado") or "").lower()
    desactiva = estado.startswith(("disabled", "deshabilit", "no habilit"))
    datos["activa"] = bool(estado) and not desactiva
    if "nombre" not in datos:
        datos["nombre"] = config.TAREA_WINDOWS_NOMBRE
    return datos


def configurar(hora, habilitado):
    """Aplica la configuración deseada creando/actualizando la tarea."""
    if estado_tarea() is None:
        crear_tarea(hora)
        if not habilitado:
            desactivar()
    else:
        cambiar_hora(hora)
        if habilitado:
            activar()
        else:
            desactivar()
    return estado_tarea()