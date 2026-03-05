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

taskkill /f /im CompressPDF.exe >nul 2>nul

pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "%GS_BIN%;ghostscript" app.py
if errorlevel 1 (
  echo [WARN] Build utama gagal. Kemungkinan folder dist sedang terkunci.
  echo [WARN] Mencoba ulang ke output folder alternatif...

  set "ALT_DIST=dist_retry_%RANDOM%%RANDOM%"
  pyinstaller --noconfirm --clean --windowed --distpath "%ALT_DIST%" --name CompressPDF --add-binary "%GS_BIN%;ghostscript" app.py
  if errorlevel 1 (
    echo [ERROR] Build retry juga gagal.
    echo [HINT] Tutup aplikasi CompressPDF, tutup File Explorer yang membuka folder dist, lalu coba lagi.
    exit /b 1
  )

  if not exist "%ALT_DIST%\CompressPDF\CompressPDF.exe" (
    echo [ERROR] Build retry selesai tapi file output tidak ditemukan.
    exit /b 1
  )

  echo [OK] Build selesai: %ALT_DIST%\CompressPDF\CompressPDF.exe
  exit /b 0
)

if not exist "dist\CompressPDF\CompressPDF.exe" (
  echo [ERROR] Build selesai tapi file output tidak ditemukan.
  exit /b 1
)

echo [OK] Build selesai: dist\CompressPDF\CompressPDF.exe
