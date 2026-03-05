@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "GS_BIN=vendor\ghostscript\windows\gswin64c.exe"
if not exist "%GS_BIN%" (
  echo [ERROR] Ghostscript binary tidak ditemukan di %GS_BIN%
  echo [HINT] Download Ghostscript lalu simpan executable ke path tersebut.
  exit /b 1
)

where pyinstaller >nul 2>nul
if errorlevel 1 (
  echo [ERROR] pyinstaller belum terpasang atau tidak ada di PATH.
  echo [HINT] Jalankan: pip install pyinstaller
  exit /b 1
)

pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "%GS_BIN%;ghostscript" app.py
if errorlevel 1 (
  echo [ERROR] Build gagal. Cek error di output terminal di atas.
  exit /b 1
)

if not exist "dist\CompressPDF\CompressPDF.exe" (
  echo [ERROR] Build selesai tapi file output tidak ditemukan.
  exit /b 1
)

echo [OK] Build selesai: dist\CompressPDF\CompressPDF.exe
