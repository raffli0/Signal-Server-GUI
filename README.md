# RF-Propagation

Monorepo untuk simulasi propagasi sinyal RF: engine C++ **Signal-Server** yang
dibungkus dengan antarmuka **GUI** Python, plus runtime AddressSanitizer
(`asanlib/`) untuk debugging.

## Struktur

| Folder           | Isi                                                                 |
|-----------------|---------------------------------------------------------------------|
| `gui/`          | Antarmuka Python (PySide/Qt) untuk menjalankan dan memvisualisasikan simulasi. |
| `Signal-Server/`| Engine propagasi sinyal berbasis SDF (clone/ fork dari W3AXL/Signal-Server). |
| `asanlib/`      | Library runtime AddressSanitizer (dependency sistem, tidak di-commit). |

## Lisensi

Kode di `Signal-Server/` berasal dari [W3AXL/Signal-Server](https://github.com/W3AXL/Signal-Server)
dan dilisensikan di bawah **GNU GPL v2** — lihat [`LICENSE`](./LICENSE).
Karena repo ini menggabungkan kode GPLv2, keseluruhan karya terdistribusi
berlaku GPLv2. Tambahan di `gui/` mengikuti lisensi yang sama.

## Catatan

- `gui/cache/` (data DEM/SDF terunduh, ~936 MB), `__pycache__`, `.venv`,
  dan `build-*/` sengaja di-abaikan lewat `.gitignore`.
- `graphify-out/` (hasil analisis otomatis) juga di-ignore.
