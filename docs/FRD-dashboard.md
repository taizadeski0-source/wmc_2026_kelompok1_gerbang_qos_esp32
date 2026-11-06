# FRD — Dashboard Pemantauan QoS Gerbang ESP32

| | |
|---|---|
| Proyek | MKKL1029 Wireless/Mobile Computing — Kelompok 1 |
| Dokumen | Functional Requirements Document (FRD) untuk antarmuka dashboard |
| Versi | 1.2 — 28 Oktober 2026 |
| Berkait | `docs/arsitektur.md`, `docs/pengujian.md`, `src/penerima/penerima.py` |
| Status | Diterapkan pada `src/dashboard/index.html` v1.2 (tema terang, 28 Oktober 2026) |

## 1. Tujuan

Dokumen ini menetapkan apa yang **harus** bisa dilakukan dashboard sebelum satu baris
tampilan ditulis, supaya pembangunan UI tidak menjadi tebak-tebakan selera. Semua
kebutuhan di bawah bisa diperiksa: tiap butir punya kriteria terima yang terlihat di layar
atau terbaca di data.

Ruang lingkup: satu halaman web yang disajikan `src/penerima/penerima.py` di
`http://127.0.0.1:8080` dan membaca `/api/state` tiap detik.

## 2. Pengguna dan Konteks

| Hal | Kenyataan yang mengikat rancangan |
|---|---|
| Pengguna | 1 operator (mahasiswa) di depan laptop sendiri |
| Penonton | dosen penguji dan kelas, sering lewat proyektor |
| Jarak baca | 1–3 meter saat presentasi, 50 cm saat mengoperasikan |
| Waktu pakai | 3–8 menit per skenario uji, dipakai berulang S1–S5 |
| Lingkungan | ruang kelas terang; layar proyektor sering kehilangan kontras |
| Perangkat | laptop Mac 1280–1512 px, kadang dibuka di ponsel untuk cek cepat |

Konsekuensi: tema **terang** (bukan gelap) karena ruangan terang dan proyektor menurunkan
kontras; angka harus besar dan tebal; warna dipakai hemat agar tidak jadi pelangi.

## 3. Istilah

| Istilah | Arti di dokumen ini |
|---|---|
| Gerbang | papan ESP32 yang jadi hotspot sekaligus meneruskan internet |
| Perangkat | telepon yang tersambung ke hotspot gerbang |
| Turun | data dari internet ke perangkat (unduh) |
| Naik | data dari perangkat ke internet (unggah) |
| Retry | persen bingkai radio yang dikirim ulang — petunjuk packet loss |
| Waktu sambung | lama `connect()` TCP gerbang ke 1.1.1.1:53, pengganti latency |
| Sesi | satu kali jalan penerima, tersimpan di `data/qos.db` |

## 4. Alur Pemakaian

1. Operator menjalankan penerima; dashboard terbuka sendiri di peramban.
2. Operator menyalakan hotspot sumber, menancapkan papan, menunggu angka bergerak.
3. Operator menyambungkan telepon uji; tiap telepon muncul sebagai satu baris tabel.
4. Operator menjalankan aktivitas di telepon sesuai skenario (S1–S5) sambil membaca angka.
5. Operator mengunduh CSV untuk lampiran laporan, lalu menghentikan sesi (Ctrl+C).

## 5. Sumber Data

Dashboard **tidak** menghitung apa pun sendiri kecuali selisih waktu dan format angka.
Semua angka berasal dari `GET /api/state` (JSON, diperbarui tiap 1 detik).

| Medan | Tipe | Arti |
|---|---|---|
| `mode` | `"serial"` \| `"sim"` | asal data; `sim` berarti angka tiruan |
| `detik` | number | umur sesi dalam detik |
| `klien` | int | jumlah klien yang dilaporkan papan |
| `rssi_uplink` | int | kekuatan sinyal papan ke hotspot sumber (dBm) |
| `rtt.sekarang` / `rata2` / `min` / `maks` / `gagal` | number | waktu sambung uplink (ms) dan jumlah kegagalan |
| `perangkat[]` | array | `mac`, `ip`, `rssi`, `naik_kbps`, `turun_kbps`, `bingkai`, `ulang`, `ulang_persen`, `dns[]` |
| `histori[]` | array ≤180 | `{t, naik, turun, rtt}` per detik, untuk grafik |
| `sesi` | int | nomor sesi di basis data |
| `mulai` | ISO-8601 | waktu sesi dimulai |

`GET /api/ekspor.csv` mengembalikan CSV sesi berjalan: `t,mac,ip,naik_bps,turun_bps,
bingkai_naik,bingkai_turun,bingkai_ulang`.

## 6. Kebutuhan Fungsional

Prioritas: **W** = wajib, **S** = sebaiknya.

| ID | Kebutuhan | Pri | Kriteria terima |
|---|---|---|---|
| FR-01 | Menampilkan identitas sesi: nomor sesi, umur sesi, mode data | W | Header memuat `sesi N`, `mm:ss`, dan penanda `LANGSUNG` atau `SIMULASI` |
| FR-02 | Memberi peringatan jelas bila data tiruan | W | Mode `sim` menampilkan pita peringatan kuning di atas layar, bukan sekadar label kecil |
| FR-03 | Menampilkan total laju turun dan naik detik terakhir | W | Dua angka besar, satuan kbps, sama dengan jumlah kolom per perangkat |
| FR-04 | Menampilkan waktu sambung uplink terkini beserta rata-rata, min, maks, gagal | W | Empat nilai terbaca; `gagal > 0` ditandai warna peringatan |
| FR-05 | Menampilkan jumlah perangkat aktif dan jumlah klien menurut papan | W | `n aktif` dan `dari n klien`, selisih keduanya terlihat |
| FR-06 | Menggambar laju turun dan naik per detik, maksimum 180 detik terakhir | W | Dua garis, legenda berwarna, sumbu Y berlabel satuan, sumbu X berlabel waktu |
| FR-07 | Menggambar waktu sambung uplink per detik | W | Garis tunggal, penanda nilai terakhir, skala ms |
| FR-08 | Menabelkan tiap perangkat: MAC, IP, kekuatan sinyal, turun, naik, jumlah bingkai, retry % | W | Satu baris per perangkat, angka rata kanan, satuan tertulis |
| FR-09 | Mengurutkan perangkat dari pemakaian terbesar | W | Baris teratas selalu punya `turun+naik` terbesar; urutan berubah bila pemakaian berubah |
| FR-10 | Menampilkan nama domain terakhir per perangkat | W | Paling banyak 6 domain per baris; kosong ditandai `—` |
| FR-11 | Menandai perangkat yang retry-nya tinggi | W | Retry > 10 % berwarna peringatan dan ada keterangan batasnya |
| FR-12 | Menandai perangkat dengan sinyal lemah | S | RSSI ≤ −75 dBm berwarna peringatan |
| FR-13 | Menyediakan unduhan CSV sesi berjalan | W | Tautan `Unduh CSV` mengarah ke `/api/ekspor.csv` dan berkasnya terunduh |
| FR-14 | Menampilkan waktu pembaruan terakhir | W | Ada penanda `diperbarui 0,3 dtk lalu` yang berubah tiap detik |
| FR-15 | Memberi status bila API tidak menjawab 3 detik | W | Pita merah `penerima tidak menjawab` muncul; angka terakhir tetap tampil dengan tanda buram |
| FR-16 | Memberi status kosong sebelum ada data | W | Pesan `menunggu data dari gerbang` dengan petunjuk 3 langkah, bukan layar putih |
| FR-17 | Memberi status bila papan belum tersambung ke hotspot sumber | W | `rtt.gagal > 0` dan `klien = 0` → keterangan `gerbang belum dapat uplink` |
| FR-18 | Menjeda pembaruan tanpa menghentikan penerima | S | Tombol `Jeda`/`Lanjut` menghentikan polling; status tetap terlihat |
| FR-19 | Menyembunyikan perangkat yang sudah pergi lebih dari 30 detik | S | Baris perangkat hilang setelah 30 detik tanpa data, tanpa menghapus riwayat grafik |
| FR-20 | Menampilkan catatan metode pengukuran | W | Footer menyebut hitungan dari bingkai 802.11, retry sebagai petunjuk loss, waktu sambung ≠ ping |
| FR-21 | Menggambar skema: sumber internet → gerbang ESP32 → empat perangkat | W | Tiga kelompok tergambar sebagai kotak berlabel; satu kabel per perangkat, berangkat dari sisi gerbang |
| FR-22 | Skema mengikuti keadaan nyata | W | Lampu sumber hijau bila uplink hidup; garis kabel per perangkat menyala hanya bila perangkat itu mengirim data; slot kosong bergaris putus-putus |
| FR-23 | Kotak animasi aliran data di bawah skema | W | Kanvas selebar isi, tiga zona berlabel `internet`/`gerbang`/`perangkat`, satu baris per perangkat |
| FR-24 | Animasi mewakili arah dan besar pemakaian | W | Titik biru bergerak ke perangkat (turun), titik hijau ke internet (naik); jumlah dan kecepatan titik naik-turun mengikuti laju detik itu; tanpa data, jalur putus-putus tanpa titik |

## 7. Kebutuhan Non-Fungsional

| ID | Kebutuhan | Kriteria terima |
|---|---|---|
| NFR-01 | Tema terang sebagai satu-satunya tema | Latar terang; tidak ada mode gelap tersembunyi |
| NFR-02 | Kontras teks utama ≥ 4,5:1, teks sekunder ≥ 3:1 | Diukur pada pasangan warna yang dipakai |
| NFR-03 | Angka memakai angka tabular agar tidak bergoyang | Lebar digit sama saat nilai berubah |
| NFR-04 | Tanpa sumber luar: tanpa CDN, tanpa font jarak jauh, tanpa gambar jaringan | Halaman tetap utuh saat WiFi mati |
| NFR-05 | Tanpa gradien, tanpa emoji, tanpa bayangan tebal, tanpa kartu melayang | Diperiksa visual; gaya mengikuti acuan bagian 8 |
| NFR-06 | Format angka Indonesia: koma desimal, titik ribuan, `kbps`/`ms`/`%` | `1.375,9 kbps`, `4,1 %`, `58 ms` |
| NFR-07 | Berat halaman < 60 KB, tanpa pustaka | `index.html` tunggal |
| NFR-08 | Tidak menampilkan isi trafik, hanya volume dan domain | Tidak ada kolom URL penuh atau data pribadi |
| NFR-09 | Tetap terbaca pada 1280×720 (proyektor) dan 1512×982 | Tidak ada gulir mendatar; tabel tetap utuh |
| NFR-10 | Pembaruan tidak mengubah tata letak | Tidak ada lompatan posisi saat angka berubah |
| NFR-11 | Skema menyesuaikan lebar jendela | Lebar ≥ 1000 px: empat perangkat berjajar, label tiga baris di bawah ikon. Lebih sempit: perangkat bertumpuk, label di samping ikon. Isi label tidak dipotong di kedua tata letak |
| NFR-12 | Animasi hemat dan sopan | Maksimum 220 titik di kanvas; bila sistem meminta kurangi gerak (`prefers-reduced-motion`), animasi melambat ke 2 bingkai/detik dan tetap terbaca |

## 8. Rancangan Tampilan

Acuan gaya: **halaman laporan cetak**, bukan panel aplikasi modern. Putih gading, garis
rambut, huruf judul berkelas serif, angka monospace, satu warna aksen.

### 8.1 Zona layar (atas ke bawah)

1. **Kepala** — judul, identitas sesi, tombol `Jeda`, tautan `Unduh CSV`.
2. **Pita peringatan** — hanya muncul saat mode simulasi atau API putus.
3. **Strip angka kunci** — 4 kolom dipisah garis rambut: turun, naik, waktu sambung, perangkat.
4. **Skema perangkat** — sumber internet, gerbang ESP32, empat slot perangkat; kabel menyala
   sesuai keadaan, label MAC/laju/IP di bawah tiap perangkat.
5. **Kotak animasi aliran data** — di bawah skema; titik paket bergerak dua arah per baris perangkat.
6. **Grafik laju** — lebar penuh, 180 detik, dua seri.
7. **Grafik waktu sambung** — lebar penuh, tinggi 1/3 grafik laju.
8. **Tabel perangkat** — satu baris per perangkat, angka rata kanan.
9. **Kaki** — metode pengukuran, berkas basis data, versi.

### 8.2 Palet (terang)

| Peran | Warna | Catatan |
|---|---|---|
| Latar | `#f7f5f0` | putih gading, bukan putih murni (mengurangi silau proyektor) |
| Permukaan | `#fffdf8` | area grafik dan tabel |
| Garis | `#d9d3c6` | garis rambut 1 px |
| Teks utama | `#191713` | kontras ≈ 15:1 |
| Teks sekunder | `#6b6459` | kontras ≈ 5:1 |
| Aksen | `#0f5b47` | hijau tua; tautan dan seri `naik` |
| Seri turun | `#23577f` | biru tinta |
| Peringatan | `#8a5a06` | retry tinggi, sinyal lemah |
| Bahaya | `#8f2b1e` | API putus, uplink gagal |

### 8.3 Huruf

| Peran | Keluarga | Ukuran |
|---|---|---|
| Judul | Iowan Old Style / Palatino / Georgia (serif sistem) | 26 px |
| Label | sans sistem, huruf besar, spasi 0,08 em | 10 px |
| Angka kunci | SF Mono / Menlo, tabular | 40 px |
| Isi tabel | sans sistem | 13 px |
| Angka tabel | SF Mono / Menlo, tabular | 13 px |

## 9. Status dan Perilaku Tepi

| Keadaan | Yang tampil |
|---|---|
| Belum ada data | Kotak kosong bergaris putus-putus: `menunggu data dari gerbang` + 3 langkah singkat |
| Mode simulasi | Pita kuning: `angka tiruan — jangan dipakai di laporan` |
| API tidak menjawab > 3 dtk | Pita merah + angka terakhir diburamkan, penanda `terakhir <waktu>` |
| Uplink gagal (`rtt.gagal > 0`, `klien = 0`) | Keterangan di strip waktu sambung: `gerbang belum dapat uplink` |
| Retry > 10 % | Angka retry warna peringatan, keterangan `batas wajar < 10 %` |
| Sinyal ≤ −75 dBm | Ikon sinyal warna peringatan, teks `lemah` |
| Sesi dihentikan | Halaman menampilkan `penerima berhenti` dan angka beku |

## 10. Di Luar Lingkup

- Riwayat banyak sesi dan perbandingan antar sesi (cukup lewat CSV).
- Kontrol papan dari dashboard (nyalakan, ganti SSID, restart).
- Peta jaringan, topologi otomatis, notifikasi surel.
- Mode gelap, tema bebas, pengaturan warna oleh pengguna.
- Dukungan ponsel sebagai layar utama (hanya sebagai pembaca cepat).

## 11. Penelusuran

| Kebutuhan | Bagian UI | Bukti uji |
|---|---|---|
| FR-01, FR-02 | Kepala + pita peringatan | Tangkapan layar mode `sim` |
| FR-03, FR-04, FR-05 | Strip angka kunci | Jumlah kolom per perangkat = angka total |
| FR-06, FR-07 | Dua grafik | Jumlah titik = umur sesi (maks 180) |
| FR-08 … FR-12 | Tabel perangkat | Baris bertambah saat telepon tersambung |
| FR-13 | Tautan `Unduh CSV` | `curl -o` mengembalikan 200 dan berkas terisi |
| FR-14 … FR-17 | Pita status | Uji matikan penerima saat halaman terbuka |
| FR-18 | Tombol `Jeda` | Angka berhenti berubah, sesi tetap jalan |
| FR-19 | Tabel perangkat | Perangkat hilang setelah 30 dtk tanpa data |
| FR-20 | Kaki halaman | Teks tampil |
| FR-21, FR-22 | Skema perangkat | Empat slot terisi saat empat telepon aktif; kabel menyala |
| FR-23, FR-24 | Kotak aliran data | `window.__animasi()` melaporkan jumlah titik dan sebaran kiri–kanan |

## 12. Riwayat

| Versi | Tanggal | Perubahan |
|---|---|---|
| 1.0 | 2026-10-28 | Versi pertama; tema terang menggantikan dashboard gelap awal |
| 1.1 | 2026-10-28 | Tambah skema perangkat dan kotak animasi aliran data (FR-21…FR-24) |
| 1.2 | 2026-10-28 | Dua tata letak skema (lebar/sempit), satuan sumbu menyatu dengan tick teratas, label MAC utuh, angka total = jumlah angka per perangkat |
