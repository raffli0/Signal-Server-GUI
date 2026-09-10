# RF-Propagation

Aplikasi simulasi propagasi sinyal RF yang menggabungkan engine C++ **Signal-Server** dengan antarmuka desktop (GUI) berbasis Python/PySide6, lengkap dengan visualisasi path profile, peta elevasi, serta sistem auto-patch.

---

## Credits & Upstream

Project ini berakar dari engine RF keren buatan **[Alex (W3AXL)](https://github.com/W3AXL)** di repo **[W3AXL/Signal-Server](https://github.com/W3AXL/Signal-Server)**.

Awalnya repo ini adalah fork langsung dari sana. Supaya lebih leluasa fokus mengembangkan GUI desktop, setup packaging installer Windows, dan alur CI/CD patch tanpa mengotori atau membebani repo upstream, repo ini akhirnya dipisahkan jadi repo mandiri.

- Kode core engine RF di folder `Signal-Server/` adalah karya W3AXL dan para kontributor aslinya.
- Kalau butuh versi CLI C++ murni atau mau ikut kontribusi ke pengembangan kalkulasi propagasinya, silakan langsung meluncur dan beri bintang ke repo aslinya: [github.com/W3AXL/Signal-Server](https://github.com/W3AXL/Signal-Server). *Big respect to W3AXL & contributors!*

---

## Struktur Folder

| Folder | Keterangan |
|---|---|
| `gui/` | Kode GUI desktop (PySide6/Qt) untuk setting parameter transmitter/receiver, render peta, dan grafik profil lintasan sinyal. |
| `Signal-Server/` | Engine kalkulasi propagasi sinyal RF berbasis C++ (upstream dari [W3AXL/Signal-Server](https://github.com/W3AXL/Signal-Server)). |
| `asanlib/` | Runtime AddressSanitizer untuk bantu deteksi memory leak / issue saat debugging. |

---

## Lisensi

- Kode engine `Signal-Server/` tetap menggunakan lisensi aslinya dari W3AXL, yaitu **GNU General Public License v2 (GPLv2)** — cek [`LICENSE`](./LICENSE).
- Karena repo ini menggabungkan dan mendistribusikan kode GPLv2, seluruh kode tambahan di folder `gui/` juga mengikuti lisensi yang sama (**GPLv2**).

---

## Catatan

- Cache data elevasi DEM/SDF (`gui/cache/`), `.venv`, dan artifact build sengaja diabaikan via `.gitignore`.


