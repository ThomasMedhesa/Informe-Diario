# PLAN: Envío del informe por correo (Outlook COM)

Objetivo: enviar el PDF generado a la lista de contactos "Contactos envío diario"
usando la cuenta `atencionalcliente@medhesa.es` ya autenticada en Outlook (sin
contraseña, vía COM/MAPI con pywin32).

---

## Módulo nuevo `informe_precios/modulos/enviar_correo.py`

- `leer_contactos()`: lee `Contactos Envio Diario.xlsx`, hoja `Hoja1`,
  columna B (índice 2) desde la fila 5 hacia abajo; ignora celdas vacías,
  elimina duplicados. Depura: columna B = `config.CONTACTOS_COL`,
  inicio = `config.CONTACTOS_FILA_INICIO`.
- `_firma_html()`: lee la firma desde
  `%APPDATA%\Microsoft\Signatures\Atención al Cliente (atencionalcliente@medhesa.es).htm`
  decodificada como UTF-8 con fallback a windows-1252.
- `es_dia_laborable()`: `datetime.today().weekday() < 5` (lunes a viernes).
- `enviar_informe(pdf, contactos)` con `win32com.client.Dispatch("Outlook.Application")`:
  - Busca en `ns.Accounts` la cuenta cuyo `SmtpAddress` == `config.CUENTA_ENVIO`
    y la asigna a `mail.SendUsingAccount`.
  - **Fallback**: si la cuenta no existe, usa la cuenta por defecto y registra
    un warning en el log.
  - `mail.Subject` = `config.ASUNTO`.
  - `mail.HTMLBody` = cuerpo HTML + `<br><br>` + firma HTML
    (imágenes referenciadas por ruta; Outlook las embebe al renderizar).
  - Adjunta el PDF con `mail.Attachments.Add(str(pdf))`.
  - Envía **un correo por destinatario** (`mail.Send()` en bucle).

## Cambios en `informe_precios/config.py`

Añadir:

```python
# Contactos / envío de correo
CONTACTOS_XLSX = RAIZ / "Contactos Envio Diario.xlsx"
CONTACTOS_HOJA = "Hoja1"
CONTACTOS_COL = 2
CONTACTOS_FILA_INICIO = 5

CUENTA_ENVIO = "atencionalcliente@medhesa.es"
ASUNTO = "Informe Precio Mercados Energ\u00e9ticos"
CUERPO = "Adjuntamos informe de precios de mercados energ\u00e9ticos de hoy (de aplicaci\u00f3n para ma\u00f1ana)."
NOMBRE_FIRMA = "Atenci\u00f3n al Cliente (atencionalcliente@medhesa.es)"
FIRMAS_DIR = Path(os.environ["APPDATA"]) / "Microsoft" / "Signatures"
```

## Cambios en `informe_precios/generar_informe.py` (paso 6, tras el PDF)

- Importar `enviar_correo`.
- Flags CLI nuevos: `--enviar` (default) y `--no-enviar`.
- Tras generar el PDF:
  - Si `--no-enviar` → log y skip.
  - Si no es día laborable (sáb/dom) → log "día no laborable" y skip.
  - Si no hay contactos → log y skip.
  - Si `os.name != "nt"` → log y skip.
  - Si todo ok → `enviar_correo.enviar_informe(destino, contactos)` y log.

## Cambios en `requirements.txt`

Añadir:

```
pywin32>=306
```

## Automatización futura (no implementar aún)

Tarea programada de Windows: `python generar_informe.py`, "solo cuando el
usuario está conectado" (mismo Windows PC41). Al usar Outlook COM requiere
que este perfil de Windows tenga Outlook configurado (ya está: se listan
4 cuentas). Outlook se lanza solo si está cerrado; no pide contraseña.

Nota: envío también funciona con Outlook cerrado (Windows tiene las
credenciales almacenadas), pero la tarea no debe correr como servicio.

## Verificación

1. `python informe_precios/generar_informe.py --no-enviar` → genera PDF sin enviar (regresión).
2. `python informe_precios/generar_informe.py --enviar` en día laborable →
   envía a `tbrellenthin@medhesa.es` con firma "Atención al Cliente" y adjunto,
   asunto "Informe Precio Mercados Energéticos".
3. Comprobar en el buzón que llega con el adjunto y la firma correcta.