@echo off
setlocal

set GS_BIN=vendor\ghostscript\windows\gswin64c.exe
if not exist "%GS_BIN%" (
  echo [ERROR] Ghostscript binary tidak ditemukan di %GS_BIN%
  echo Download Ghostscript lalu simpan executable ke path tersebut.
  exit /b 1
)

pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "%GS_BIN%;ghostscript" app.py

echo Build selesai: dist\CompressPDF\CompressPDF.exe
