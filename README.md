# Batch Photo Cropper

Aplikasi desktop GTK3 untuk memotong (crop) banyak foto sekaligus ke ukuran pas foto — 3x4 cm, 2x3 cm, ukuran paspor, atau ukuran custom dalam milimeter.

Dibangun dengan **PyGObject (GTK3)** + **Pillow** + **Cairo**.

<!-- Tambahkan screenshot setelah commit, contoh:
![Screenshot](docs/screenshot.png)
-->

## Fitur

- **Batch crop** — pilih banyak foto sekaligus, satu crop box berlaku untuk semua.
- **Preset ukuran Indonesia** — 3x4, 2x3, 4x6, 2x2, 3x3, 5x7, 6x8 cm.
- **Preset paspor** — UK (35x45 mm) dan US (2x2 inci).
- **Custom size** — masukkan lebar/tinggi bebas dalam mm.
- **Rasio terkunci** — crop box selalu mengikuti rasio preset saat diperbesar.
- **Preview** — lihat hasil semua foto dalam grid 3 kolom sebelum export.
- **Pilihan output** — JPEG, PNG, WEBP, atau BMP; DPI 72/96/150/300/600; slider kualitas untuk JPEG/WEBP.
- **DPI print** — ukuran pixel dihitung dari ukuran mm × DPI (mis. 3x4 cm @300 DPI = 354x472 px).
- **Crop interaktif** — drag untuk memindah, drag corner handle untuk mengubah ukuran, rule of thirds, navigasi lewat thumbnail.
- **Anti-timpa** — file hasil yang namanya bentrok otomatis diberi suffix `_1`, `_2`, dst.

## Kebutuhan Sistem

Butuh **GTK 3** dan binding PyGObject. Python minimal 3.9 (menggunakan type hints `list[...]`).

### Arch / Omarchy

```bash
sudo pacman -S gtk3 python-gobject python-pillow
```

### Debian / Ubuntu

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo python3-pil
```

### Fedora

```bash
sudo dnf install gtk3 python3-gobject python3-pillow
```

> Nama paket `python3-cairo` / `pycairo` sudah ikut terpasang sebagai dependensi `python3-gobject` di sebagian besar distro.

## Instalasi

```bash
git clone git@github.com:natedekaka/photo-cropper.git
cd photo-cropper
pip install -r requirements.txt
```

`requirements.txt` hanya memuat Pillow — PyGObject, GTK3, dan Cairo meditating di-*install* lewat package manager sistem karena keduanya punya bagian native (C library).

## Menjalankan

```bash
python3 app.py
```

Alternatif, agar bisa dipanggil dari mana saja:

```bash
sudo cp app.py /usr/local/bin/photo-cropper && sudo chmod +x /usr/local/bin/photo-cropper
photo-cropper
```

## Cara Pakai

1. Klik **📂 Pilih Foto...** — pilih satu atau banyak file (PNG, JPG, JPEG, BMP, GIF, WEBP, TIF/TIFF).
2. Pilih **preset ukuran** atau isi lebar/tinggi custom, lalu klik **Terapkan Ukuran**.
   - Crop box otomatis ditempatkan di tengah dengan rasio preset, dan area luarnya digelapkan.
   - Rasio dan ukuran pixel output ditampilkan di bawahnya.
3. Sesuaikan crop box: **drag di dalam** untuk memindah, **drag corner** (titik hijau) untuk mengubah ukuran.
4. Navigasi foto dengan **thumbnail**, **scroll wheel**, atau **← / →**.
5. Klik **👁 Preview Semua** untuk mengecek hasil semua foto sekaligus.
6. Klik **💾 Export Semua...** dan pilih folder tujuan.
7. Selesai — tiap file disimpan sebagai `<nama-asli>_cropped.<ext>` di folder tersebut.

## Pintasan Keyboard

| Tombol | Fungsi |
| --- | --- |
| `←` / `→` | Foto sebelumnya / berikutnya |
| `Scroll` | Foto sebelumnya / berikutnya |
| `Delete` | Hapus foto yang sedang dipilih dari daftar |

## Rincian Teknis

| Item | Nilai |
| --- | --- |
| Ukuran output | dalam milimeter, rasio dikunci |
| Resolusi | 72 / 96 / 150 / 300 / 600 DPI |
| Resize | `Image.LANCZOS` |
| Metadata DPI | ditulis ke file hasil (kecuali PNG) |
| Struktur | `app.py` — `Theme`, `CropCanvas` (preview + interaksi), `PhotoCropperApp` (UI, ekspor) |

Alur export: `GdkPixbuf` (decode) → koordinat display dipetakan balik ke koordinat gambar asli lewat `scale`/`offset` → `PIL.Image.crop` → `resize` ke ukuran target → `save` dengan DPI & kualitas yang dipilih.

## Batasan

- Area crop yang sama dipakai untuk semua foto dalam batch. Foto dengan rasio atau orientasi berbeda akan mendapat areaCrop yang tidak identik secara proporsional — jadi sebaiknya satu batch berisi foto dengan orientasi serupa.
- Crop hanya, tidak ada rotasi, koreksi warna, atau auto-facial detection.
- Berjalan di Linux/BSD saja (PyGObject + GTK3). Tidak ada build untuk Windows atau macOS.
- Foto dimuat penuh ke memori (`GdkPixbuf` + salinan PIL), jadi tidak ideal untuk ribuan foto resolusi besar sekaligus.

## Lisensi

[MIT](LICENSE) — bebas dipakai, modifikasi, dan distribusi wajib menyertakan teks lisensi.
