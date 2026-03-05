#!/usr/bin/env bash
set -euo pipefail

GS_BIN="vendor/ghostscript/macos/gs"
if [[ ! -f "$GS_BIN" ]]; then
  echo "[ERROR] Ghostscript binary tidak ditemukan di $GS_BIN"
  echo "Salin binary gs ke path tersebut lalu jalankan lagi."
  exit 1
fi

chmod +x "$GS_BIN"
pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "$GS_BIN:ghostscript" app.py

echo "Build selesai: dist/CompressPDF.app"
