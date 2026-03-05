# CompressPDF

Aplikasi desktop untuk kompres PDF dengan UI modern berbasis **CustomTkinter** dan engine kompresi **Ghostscript**.
Project ini mendukung **macOS** dan **Windows**.

---

## 1) Gambaran Aplikasi

CompressPDF dirancang untuk user non-teknis agar bisa:

- Upload PDF (drag & drop atau tombol **Upload via browser**)
- Pilih level kompresi
- Jalankan kompres batch
- Simpan hasil ke folder output pilihan

### Fitur Utama (sesuai aplikasi saat ini)

- Upload PDF via:
  - Drag & drop
  - Dialog file (Upload via browser)
- Multi-file preview + tombol hapus (`✕`) per file
- Proteksi duplicate upload (file sama tidak ditambahkan dua kali)
- 3 level kompresi:
  - **Low** (`/screen`) → ukuran lebih kecil, kualitas lebih turun
  - **Medium** (`/ebook`) → seimbang
  - **High** (`/printer`) → kualitas lebih tinggi, kompresi lebih ringan
- Progress proses kompres
- Statistik hasil:
  - Storage saved
  - Files processed
  - Avg speed
- Output default ke: `~/Documents/Compressed_PDFs`
- Tombol `Compress Now` nonaktif saat proses berjalan (mencegah klik berulang)
- Logging performa ke file:
  - `~/Documents/Compressed_PDFs/app_performance.log`

---

## 2) Teknologi

- Python 3.10+
- customtkinter
- tkinterdnd2
- Ghostscript (binary dibundel ke aplikasi saat build)
- PyInstaller (untuk membuat app distribusi)

---

## 3) Menjalankan Saat Development

## 3.1 Siapkan Environment

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3.2 Jalankan App

```bash
python app.py
```

---

## 4) Struktur Folder Penting

- `app.py` → source utama aplikasi
- `requirements.txt` → dependency Python
- `build_windows.bat` → script build Windows
- `build_macos.sh` → script build macOS
- `vendor/ghostscript/windows/gswin64c.exe` → binary GS untuk Windows (harus ada untuk build Windows)
- `vendor/ghostscript/macos/gs` → binary GS untuk macOS (harus ada untuk build macOS)

---

## 5) Panduan Build Lengkap - Windows (Dari Awal Sampai Akhir)

> Build Windows **harus dilakukan di mesin Windows**.

## 5.1 Prasyarat

1. Install Python 3.10+ (centang `Add Python to PATH` saat install)
2. Siapkan project ini di folder lokal
3. Siapkan binary Ghostscript portable untuk bundle:
   - Letakkan file di:
     - `vendor\ghostscript\windows\gswin64c.exe`

## 5.2 Setup Environment

Buka **Command Prompt / PowerShell** di root project:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
```

## 5.3 Build Otomatis (Disarankan)

Jalankan:

```bat
build_windows.bat
```

Script ini akan:

- Cek file `vendor\ghostscript\windows\gswin64c.exe`
- Menjalankan PyInstaller dengan `--add-binary`
- Menghasilkan app di folder `dist`

## 5.4 Build Manual (Opsional)

```powershell
pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "vendor\ghostscript\windows\gswin64c.exe;ghostscript" app.py
```

## 5.5 Output Build

Hasil utama:

- `dist\CompressPDF\CompressPDF.exe`

Folder distribusi yang dibagikan ke user:

- seluruh isi `dist\CompressPDF\`

## 5.6 Uji Build Sebelum Dikirim

1. Jalankan `CompressPDF.exe`
2. Test upload file PDF
3. Test tombol `Change` output folder
4. Test proses kompres sampai selesai
5. Pastikan hasil muncul di folder output

## 5.7 Troubleshooting Windows

- **Error Ghostscript binary tidak ditemukan**
  - Pastikan file ada di: `vendor\ghostscript\windows\gswin64c.exe`
- **App tidak bisa dibuka di PC lain**
  - Kirim **folder** `dist\CompressPDF\` lengkap, jangan hanya `.exe`
- **SmartScreen warning**
  - Normal untuk app unsigned; perlu code-sign certificate jika untuk produksi

---

## 6) Panduan Build Lengkap - macOS (Dari Awal Sampai Akhir)

> Build macOS **harus dilakukan di mesin macOS**.

## 6.1 Prasyarat

1. Install Python 3.10+
2. Siapkan project ini di folder lokal
3. Siapkan binary Ghostscript untuk bundle:
   - Letakkan file di:
     - `vendor/ghostscript/macos/gs`

## 6.2 Setup Environment

Di Terminal, dari root project:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
```

## 6.3 Build Otomatis (Disarankan)

```bash
chmod +x build_macos.sh
./build_macos.sh
```

Script ini akan:

- Cek file `vendor/ghostscript/macos/gs`
- Set executable permission ke binary GS
- Build `.app` via PyInstaller

## 6.4 Build Manual (Opsional)

```bash
chmod +x vendor/ghostscript/macos/gs
pyinstaller --noconfirm --clean --windowed --name CompressPDF --add-binary "vendor/ghostscript/macos/gs:ghostscript" app.py
```

## 6.5 Output Build

Hasil utama:

- `dist/CompressPDF.app`

## 6.6 Uji Build

```bash
open dist/CompressPDF.app
```

Lakukan pengecekan:

1. Upload via browser
2. Drag & drop file PDF
3. Change output folder
4. Compress sampai selesai

## 6.7 Gatekeeper / Security (macOS)

Untuk app unsigned, kadang diblokir macOS:

- Klik kanan app → **Open**
- Atau jalankan:

```bash
xattr -dr com.apple.quarantine dist/CompressPDF.app
```

Untuk distribusi profesional, gunakan:

- Code signing
- Notarization (Apple Developer)

---

## 7) Cara Pakai Aplikasi (Untuk End User)

1. Buka aplikasi
2. Upload file PDF (drag/drop atau tombol upload)
3. Pilih level kompresi (Low/Medium/High)
4. (Opsional) Ubah folder output via tombol `Change`
5. Klik `Compress Now`
6. Tunggu progres selesai
7. Buka folder output untuk mengambil hasil

---

## 8) Konfigurasi Output

- Default output:
  - `~/Documents/Compressed_PDFs`
- Nama hasil otomatis:
  - `<nama_asli>_compressed_<timestamp>.pdf`

---

## 9) Logging dan Diagnostik

Log performa tersimpan di:

- `~/Documents/Compressed_PDFs/app_performance.log`

Log ini berguna untuk analisa:

- Delay klik tombol
- Event loop jitter
- Durasi operasi upload/kompres

---

## 10) .gitignore

Project sudah memakai `.gitignore` agar file yang tidak perlu tidak ikut ke GitHub, termasuk:

- cache Python
- virtual env
- build artifacts (`build`, `dist`)
- log file
- file khusus OS/editor

---

## 11) Lisensi Ghostscript (Penting)

Ghostscript memiliki ketentuan lisensi tersendiri (AGPL/commercial).
Pastikan penggunaan/distribusi aplikasi Anda sesuai lisensi Ghostscript yang dipakai.

---

## 12) Ringkasan Build Cepat

### Windows

```bat
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
build_windows.bat
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
chmod +x build_macos.sh
./build_macos.sh
```

---

Jika ingin, README ini bisa saya lanjutkan dengan bagian **release checklist** (versioning, changelog, tagging git, dan format nama file rilis) supaya siap dipakai untuk workflow tim.
