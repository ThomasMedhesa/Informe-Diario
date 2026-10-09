"""Servidor web local de revisión y envío del informe diario.

Arranque (desde la raíz del proyecto):
    python informe_precios\\servidor_web.py

Abre en el navegador: http://127.0.0.1:8000
"""

import json
import logging
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from flask import Flask, jsonify, render_template, request, send_file
from modulos import contactos, enviar_correo, programar_tarea

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder=str(config.BASE_DIR / "web"))

_lock = threading.Lock()

_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_HORA_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")


def _hora_corta(valor):
    """Reduce una hora de schtasks (14:00:00) a HH:MM para el input de la web."""
    m = _HORA_RE.match(str(valor or ""))
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _com_init():
    """Inicializa COM en el hilo actual (Outlook) sin errores si ya está."""
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception as e:  # noqa: BLE001
        log.debug("CoInitialize ignorado: %s", e)


def _nombre_valido(nombre):
    """Controla que `nombre` sea el de un PDF dentro de salida/ (sin rutas)."""
    if not nombre:
        return False
    base = Path(nombre).name
    if base != nombre or base.lower().endswith(".pdf") is False:
        return False
    ruta = (config.SALIDA_DIR / base).resolve()
    return ruta.parent == config.SALIDA_DIR.resolve() and ruta.exists()


def _listar_pdfs():
    pdfs = []
    for p in sorted(config.SALIDA_DIR.glob("*.pdf"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        pdfs.append({
            "nombre": p.name,
            "fecha": p.stem.replace("Informe Precio Diario ", ""),
            "tam_kb": round(p.stat().st_size / 1024, 1),
        })
    return pdfs


@app.route("/")
def inicio():
    return render_template("revision.html")


@app.route("/api/pdfs")
def api_pdfs():
    return jsonify({"pdfs": _listar_pdfs()})


@app.route("/pdf/<path:nombre>")
def servir_pdf(nombre):
    if not _nombre_valido(nombre):
        return "PDF no encontrado", 404
    return send_file(
        config.SALIDA_DIR / nombre,
        mimetype="application/pdf",
        as_attachment=False,
    )


@app.route("/api/contactos", methods=["GET", "POST"])
def api_contactos():
    if request.method == "POST":
        datos = request.get_json(silent=True) or {}
        emails = datos.get("emails", [])
        lista = [str(e).strip() for e in emails if str(e).strip()]
        invalidos = [e for e in lista if not _RE_CORREO.match(e)]
        if invalidos:
            return jsonify({"error": "Correos no válidos",
                            "invalidos": invalidos}), 400
        try:
            finales = contactos.guardar_contactos(lista)
        except PermissionError:
            return jsonify({"error": "No se puede escribir en el Excel: "
                                     "ciérralo si está abierto en Excel."}), 409
        except Exception as e:  # noqa: BLE001
            log.exception("Error guardando contactos")
            return jsonify({"error": f"Error guardando contactos: {e}"}), 500
        return jsonify({"contactos": finales})
    return jsonify({"contactos": contactos.leer_contactos()})


@app.route("/api/contactos/anadir", methods=["POST"])
def api_anadir_contactos():
    datos = request.get_json(silent=True) or {}
    emails = [str(e).strip() for e in datos.get("emails", []) if str(e).strip()]
    invalidos = [e for e in emails if not _RE_CORREO.match(e)]
    if invalidos:
        return jsonify({"error": "Correos no válidos",
                        "invalidos": invalidos}), 400
    try:
        finales = contactos.anadir_contactos(emails)
    except PermissionError:
        return jsonify({"error": "No se puede escribir en el Excel: "
                                 "ciérralo si está abierto en Excel."}), 409
    except Exception as e:  # noqa: BLE001
        log.exception("Error añadiendo contactos")
        return jsonify({"error": f"Error añadiendo contactos: {e}"}), 500
    return jsonify({"contactos": finales})


@app.route("/api/contactos/eliminar", methods=["POST"])
def api_eliminar_contactos():
    datos = request.get_json(silent=True) or {}
    emails = [str(e).strip() for e in datos.get("emails", []) if str(e).strip()]
    if not emails:
        return jsonify({"error": "Indica al menos un correo a eliminar"}), 400
    try:
        finales = contactos.eliminar_contactos(emails)
    except PermissionError:
        return jsonify({"error": "No se puede escribir en el Excel: "
                                 "ciérralo si está abierto en Excel."}), 409
    except Exception as e:  # noqa: BLE001
        log.exception("Error eliminando contactos")
        return jsonify({"error": f"Error eliminando contactos: {e}"}), 500
    return jsonify({"contactos": finales})


@app.route("/api/contactos/importar", methods=["POST"])
def api_importar_contactos():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return jsonify({"error": "Selecciona un archivo Excel (.xlsx) o CSV."}), 400
    ext = Path(archivo.filename).suffix.lower()
    if ext not in (".xlsx", ".xlsm", ".csv"):
        return jsonify({"error": "Formato no soportado. Sube un .xlsx o .csv."}), 400
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / ("importacion" + ext)
        archivo.save(ruta)
        emails = contactos.leer_emails_archivo(ruta)
    if not emails:
        return jsonify({"error": "No se encontraron correos en el archivo."}), 400
    try:
        finales = contactos.anadir_contactos(emails)
    except PermissionError:
        return jsonify({"error": "No se puede escribir en el Excel: "
                                 "ciérralo si está abierto en Excel."}), 409
    except Exception as e:  # noqa: BLE001
        log.exception("Error importando contactos")
        return jsonify({"error": f"Error importando contactos: {e}"}), 500
    return jsonify({"contactos": finales, "importados": len(emails)})


@app.route("/api/contactos/exportar")
def api_exportar_contactos():
    return send_file(
        contactos.exportar_excel_bytes(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Contactos_Envio_Diario.xlsx",
    )


@app.route("/api/programacion")
def api_programacion():
    estado = programar_tarea.estado_tarea()
    hora = _hora_corta(estado.get("hora")) if estado else None
    return jsonify({
        "hora": hora or config.HORA_ENVIO,
        "habilitado": bool(estado and estado.get("activa")),
        "tarea": estado,
    })


@app.route("/api/programacion", methods=["POST"])
def api_programacion_guardar():
    datos = request.get_json(silent=True) or {}
    habilitado = bool(datos.get("habilitado", True))
    hora = datos.get("hora") or config.HORA_ENVIO
    try:
        estado = programar_tarea.configurar(hora, habilitado)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        log.exception("Error configurando la tarea")
        return jsonify({"error": f"Error configurando la tarea: {e}"}), 500
    hora_final = _hora_corta(estado.get("hora")) if estado else hora
    return jsonify({
        "hora": hora_final or config.HORA_ENVIO,
        "habilitado": bool(estado and estado.get("activa")),
        "tarea": estado,
    })


@app.route("/api/programacion/eliminar", methods=["POST"])
def api_programacion_eliminar():
    try:
        programar_tarea.eliminar_tarea()
    except Exception as e:  # noqa: BLE001
        log.exception("Error eliminando la tarea")
        return jsonify({"error": f"Error eliminando la tarea: {e}"}), 500
    return jsonify({
        "hora": config.HORA_ENVIO,
        "habilitado": False,
        "tarea": None,
    })


@app.route("/api/generar", methods=["POST"])
def api_generar():
    datos = request.get_json(silent=True) or {}
    manual = None
    if datos.get("manual"):
        try:
            manual = _validar_manual(datos["manual"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    if not _lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una operación en curso"}), 409
    try:
        import generar_informe

        resultado = generar_informe.ejecutar(enviar=False, manual=manual)
        return jsonify({
            "ok": True,
            "pdf": Path(str(resultado.pdf)).name,
            "faltan": resultado.faltan,
        })
    except Exception as e:  # noqa: BLE001
        log.exception("Error generando informe")
        return jsonify({"error": f"Error generando informe: {e}"}), 500
    finally:
        _lock.release()


MERCADOS_MANUAL = ("ELEC", "GAS")


def _clave_manual(clave):
    """Normaliza la clave de un dato manual de futuros.

    Electricidad y gas comparten columna historico, asi que la clave lleva el
    mercado: "ELEC:BASE_Q3_2027" o "GAS:BASE_Q3_2027". Una clave sin mercado
    se acepta y se aplica a los dos (compatibilidad con avisos anteriores).
    """
    clave = str(clave)
    if ":" not in clave:
        return clave
    mercado, _, columna = clave.partition(":")
    mercado = mercado.strip().upper()
    if mercado not in MERCADOS_MANUAL:
        raise ValueError(f"Mercado desconocido en '{clave}' (usa ELEC o GAS)")
    columna = columna.strip()
    if not columna:
        raise ValueError(f"Columna vacía en '{clave}'")
    return f"{mercado}:{columna}"


def _validar_manual(manual):
    """Valida y convierte a float el dict de datos manuales de la web."""
    limpio = {}
    for clave in ("precio_omie", "precio_mibgas"):
        valor = manual.get(clave)
        if valor in (None, ""):
            continue
        try:
            limpio[clave] = float(valor)
        except (TypeError, ValueError):
            raise ValueError(f"Valor no numérico en {clave}")
    futuros = {}
    fut = manual.get("futuros") or {}
    if not isinstance(fut, dict):
        raise ValueError("'futuros' debe ser un objeto")
    for clave, valor in fut.items():
        if valor in (None, ""):
            continue
        clave = _clave_manual(clave)
        try:
            futuros[clave] = float(valor)
        except (TypeError, ValueError):
            raise ValueError(f"Valor no numérico en {clave}")
    if futuros:
        limpio["futuros"] = futuros
    if not limpio:
        raise ValueError("Indica al menos un dato manual")
    return limpio


@app.route("/api/estado")
def api_estado():
    ruta = config.ULTIMO_ESTADO_JSON
    if not ruta.exists():
        return jsonify({"estado": None})
    try:
        return jsonify({"estado": json.loads(ruta.read_text(encoding="utf-8"))})
    except Exception:  # noqa: BLE001
        log.exception("Error leyendo el estado de la última ejecución")
        return jsonify({"estado": None})


def _marcar_enviado(nombre_pdf, fallidos=None):
    """Actualiza el estado guardado tras un envío manual de ese PDF."""
    ruta = config.ULTIMO_ESTADO_JSON
    if not ruta.exists():
        return
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
        if data.get("pdf") != nombre_pdf:
            return
        fallidos = list(fallidos or [])
        data["enviado"] = True
        data["motivo"] = "envio_parcial" if fallidos else "ok"
        # Si el reenvío va a todos, se borra el aviso anterior: si no, la web
        # seguiría enseñando destinatarios fallidos que ya lo recibieron.
        if fallidos:
            data["fallidos_envio"] = fallidos
        else:
            data.pop("fallidos_envio", None)
        ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.exception("No se pudo actualizar el estado al enviar")


@app.route("/api/enviar", methods=["POST"])
def api_enviar():
    datos = request.get_json(silent=True) or {}
    nombre = datos.get("pdf", "")
    if not _nombre_valido(nombre):
        return jsonify({"error": "Selecciona un PDF válido para enviar"}), 400

    lista = contactos.leer_contactos()
    if not lista:
        return jsonify({"error": "No hay destinatarios configurados. "
                                 "Revisa la lista de envío."}), 400

    if not _lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una operación en curso"}), 409
    try:
        _com_init()
        destino = config.SALIDA_DIR / nombre
        envio = enviar_correo.enviar_informe(destino, lista)
        _marcar_enviado(nombre, envio.fallidos)
        return jsonify({"ok": True, "enviados": envio.enviados,
                        "total": envio.total, "fallidos": envio.fallidos,
                        "contactos": lista, "pdf": nombre})
    except Exception as e:  # noqa: BLE001
        log.exception("Error enviando informe")
        return jsonify({"error": f"Error enviando: {e}"}), 500
    finally:
        _lock.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    print("\nAbre el informe en el navegador: http://127.0.0.1:8000\n")
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)