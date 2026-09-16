"""Servidor web local de revisión y envío del informe diario.

Arranque (desde la raíz del proyecto):
    python informe_precios\\servidor_web.py

Abre en el navegador: http://127.0.0.1:8000
"""

import logging
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from flask import Flask, jsonify, render_template, request, send_file
from modulos import contactos, enviar_correo

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="web")

_lock = threading.Lock()


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
        invalidos = [e for e in lista
                     if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e)]
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


@app.route("/api/generar", methods=["POST"])
def api_generar():
    if not _lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una operación en curso"}), 409
    try:
        import generar_informe

        destino = generar_informe.ejecutar(enviar=False)
        return jsonify({"ok": True, "pdf": Path(destino).name})
    except Exception as e:  # noqa: BLE001
        log.exception("Error generando informe")
        return jsonify({"error": f"Error generando informe: {e}"}), 500
    finally:
        _lock.release()


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
        enviados = enviar_correo.enviar_informe(destino, lista)
        return jsonify({"ok": True, "enviados": enviados,
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