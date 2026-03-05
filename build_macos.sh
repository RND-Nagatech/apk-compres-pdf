#!/usr/bin/env bash
set -euo pipefail

GS_BIN="vendor/ghostscript/macos/gs"
APP_PATH="dist/CompressPDF.app"

if [[ ! -f "$GS_BIN" ]]; then
  echo "[ERROR] Ghostscript binary tidak ditemukan di $GS_BIN"
  echo "Salin binary gs ke path tersebut lalu jalankan lagi."
  exit 1
fi

chmod +x "$GS_BIN"
pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "$GS_BIN:ghostscript" app.py

if [[ ! -d "$APP_PATH" ]]; then
  echo "[ERROR] Build selesai tapi app bundle tidak ditemukan di $APP_PATH"
  exit 1
fi

echo "[INFO] Ad-hoc signing app bundle..."
codesign --force --deep --sign - "$APP_PATH"

echo "[INFO] Remove quarantine attribute (jika ada)..."
xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true

echo "[INFO] Verifying code signature..."
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "[INFO] Gatekeeper assessment..."
if spctl --assess --type execute --verbose=4 "$APP_PATH"; then
  echo "[OK] Gatekeeper assessment passed"
else
  echo "[WARN] Gatekeeper masih bisa reject untuk app unsigned/not notarized"
  echo "[WARN] User bisa buka via Right click -> Open atau lakukan code-sign + notarization resmi"
fi

echo "Build selesai: $APP_PATH"
