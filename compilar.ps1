# Compila el ejecutable de escritorio del informe diario.
# Uso:  powershell -ExecutionPolicy Bypass -File .\compilar.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host ''
Write-Host '== 1/3  Dependencias ==' -ForegroundColor Cyan
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python -m pip install --quiet --disable-pip-version-check pyinstaller

Write-Host '== 2/3  Icono de la aplicacion ==' -ForegroundColor Cyan
python -c "from PIL import Image; im=Image.open('icono medhesa.png').convert('RGBA'); im.thumbnail((256,256)); im.save('informe_precios/web/informe_diario.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host '== 3/3  Empaquetado con PyInstaller ==' -ForegroundColor Cyan
if (Test-Path -LiteralPath '.\aplicacion') { Remove-Item -LiteralPath '.\aplicacion' -Recurse -Force }
python -m PyInstaller --noconfirm --clean `
    --distpath '.\aplicacion' `
    --workpath '.\build' `
    '.\InformeDiario.spec'

$exe = Join-Path $PSScriptRoot 'aplicacion\InformeDiario\InformeDiario.exe'
Write-Host ''
if (Test-Path -LiteralPath $exe) {
    Write-Host "Listo: $exe" -ForegroundColor Green
    Write-Host 'Para abrir la aplicacion, haz doble clic en ese archivo.'
} else {
    Write-Host 'No se ha generado el ejecutable. Revisa el log de PyInstaller.' -ForegroundColor Red
    exit 1
}
