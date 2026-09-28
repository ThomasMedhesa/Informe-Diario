"""Punto de entrada de la aplicacion de escritorio del informe diario.

Uso habitual (doble clic en el ejecutable, o ``python informe_precios/lanzador.py``):
    - arranca el servidor web local,
    - abre automaticamente el navegador en la pantalla de revision y envio,
    - muestra una ventana pequena para abrir de nuevo la web o cerrar todo.

Parametro especial (lo usa la tarea programada de Windows):
    ``--generar``  genera el informe de hoy, lo envia y termina sin ventanas.
"""

import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# El paquete se importa con su propia carpeta en sys.path para que funcione
# tanto como script suelto como empaquetado (en el .exe ya viene incluido).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

log = logging.getLogger("lanzador")

URL = f"http://{config.SERVIDOR_HOST}:{config.SERVIDOR_PUERTO}"
ARG_GENERAR = "--generar"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _configurar_log():
    """Log a archivo (el ejecutable no tiene consola donde escribir)."""
    config.asegurar_dirs()
    ruta = config.SALIDA_DIR / "lanzador.log"
    manejador = logging.FileHandler(ruta, encoding="utf-8", delay=True)
    manejador.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[manejador],
    )
    return ruta


def puerto_libre(host, puerto):
    """True si se puede escuchar en (host, puerto)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, puerto))
        except OSError:
            return False
    return True


def _mostrar_error(titulo, mensaje):
    """Aviso en un cuadro de diálogo (o consola si no hay tkinter)."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(titulo, mensaje)
        raiz.destroy()
    except Exception:  # noqa: BLE001
        print(f"{titulo}: {mensaje}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Modo generacion (tarea programada)
# ---------------------------------------------------------------------------
def modo_generar():
    """Genera el informe de hoy y lo envia. Devuelve el codigo de salida."""
    import generar_informe

    generar_informe._activar_log_archivo()
    resultado = generar_informe.ejecutar(enviar=True)
    if resultado.faltan:
        log.warning("Informe generado con %d datos faltantes.", len(resultado.faltan))
    return 0


# ---------------------------------------------------------------------------
# Modo aplicacion (ventana + web)
# ---------------------------------------------------------------------------
def _servidor(app):
    """Arranca el servidor Flask en segundo plano y devuelve el servidor."""
    from werkzeug.serving import make_server

    return make_server(config.SERVIDOR_HOST, config.SERVIDOR_PUERTO, app,
                       threaded=True)


def modo_aplicacion():
    """Abre la ventana de control con el servidor web detrás."""
    import tkinter as tk
    from tkinter import ttk

    from servidor_web import app

    raiz = tk.Tk()
    raiz.title("Informe diario de precios energéticos")
    raiz.resizable(False, False)
    raiz.configure(background="#f4f6f7")

    marco = ttk.Frame(raiz, padding=18)
    marco.grid(row=0, column=0, sticky="nsew")

    ttk.Label(marco, text="Informe diario de precios energéticos",
              font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 2))
    ttk.Label(marco, text=f"Aplicación activa en {URL}",
              font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=2,
                                        sticky="w", pady=(0, 12))

    estado = ttk.Label(marco, text=" ", font=("Segoe UI", 9))
    estado.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))

    servidor = None
    hilo = None

    def avisar(texto):
        estado.config(text=texto)

    def abrir_web():
        try:
            webbrowser.open(URL)
            avisar("Navegador abierto.")
        except Exception as e:  # noqa: BLE001
            avisar(f"No se pudo abrir el navegador: {e}")

    def apagar():
        nonlocal servidor
        avisar("Cerrando...")
        raiz.update_idletasks()
        if servidor is not None:
            servidor.shutdown()
        raiz.destroy()

    def arrancar():
        nonlocal servidor, hilo
        if servidor is not None:
            avisar("El servidor ya está en marcha.")
            return
        try:
            servidor = _servidor(app)
        except OSError as e:
            avisar(f"No se pudo arrancar el servidor: {e}")
            _mostrar_error(
                "Informe diario",
                f"No se pudo abrir el puerto {config.SERVIDOR_PUERTO}.\n\n"
                f"Puede que la aplicación ya esté abierta.\n\nDetalle: {e}")
            return
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        avisar("Servidor en marcha.")
        log.info("Servidor iniciado en %s", URL)
        abrir_web()

    ttk.Button(marco, text="Abrir en el navegador",
               command=abrir_web).grid(row=3, column=0, sticky="ew", padx=(0, 6))
    ttk.Button(marco, text="Reiniciar servidor",
               command=arrancar).grid(row=3, column=1, sticky="ew", padx=(6, 0))
    marco.columnconfigure(0, weight=1)
    marco.columnconfigure(1, weight=1)

    ttk.Separator(marco).grid(row=4, column=0, columnspan=2, sticky="ew",
                              pady=14)
    ttk.Button(marco, text="Cerrar aplicación", command=apagar).grid(
        row=5, column=0, columnspan=2, sticky="ew")

    raiz.protocol("WM_DELETE_WINDOW", apagar)
    # Margen para que el aviso de inicio se vea antes de abrir el navegador.
    avisar("Arrancando...")
    raiz.after(300, arrancar)
    raiz.mainloop()
    return 0


def main():
    _configurar_log()
    if ARG_GENERAR in sys.argv:
        return modo_generar()
    if not puerto_libre(config.SERVIDOR_HOST, config.SERVIDOR_PUERTO):
        # Puede ser otra copia de la aplicación: basta con abrir el navegador.
        log.info("Puerto ocupado, se abre el navegador sobre la instancia viva")
        try:
            webbrowser.open(URL)
            return 0
        except Exception:  # noqa: BLE001
            return 1
    return modo_aplicacion()


if __name__ == "__main__":
    sys.exit(main())
