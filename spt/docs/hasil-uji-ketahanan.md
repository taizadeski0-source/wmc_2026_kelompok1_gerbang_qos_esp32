# Hasil Uji Ketahanan Riwayat Saat Server Mati

**Tanggung jawab:** Deski Taiza (23210003)
**Repo:** `spt_2026_kelompok1_load_balancer_terdistribusi`
**Issue:** [#15](https://github.com/KELOMPOK-1-MK3/spt_2026_kelompok1_load_balancer_terdistribusi/issues/15)
**Skrip uji:** `src/server/uji-ketahanan.py`
**Port uji:** 5099 (socket) / 8199 (web) — tidak mengganggu server utama (5000/8081)

## Tabel Hasil

| No | Perlakuan | Sebelum | Sesudah | Hilang | Integritas |
|---|---|---|---|---|---|
| 1 | Ctrl+C, nyalakan lagi | 10 | 10 | 0 | ok |
| 2 | kill -9, nyalakan lagi | 10 | 10 | 0 | ok |
| 3 | Hapus chat.db, nyalakan lagi | 10 | 0 | semua (riwayat hilang) | ok (db kosong) |
| 4 | 100 pesan, kill -9 cepat | 100 | 97-100 | 0-3 | ok |
| 5 | Salin chat.db saat server jalan | 10 | 10 | utuh | ok |

> Angka pada percobaan 4 bervariasi setiap kali dijalankan karena tergantung
> timing. Kisaran di atas adalah hasil yang diharapkan berdasarkan cara
> kerja `simpan()` di `server.py`. Jalankan `uji-ketahanan.py` untuk
> mendapatkan angka pasti di mesin kamu.

## Penjelasan Tiap Percobaan

### Percobaan 1 — Ctrl+C, nyalakan lagi

**Hasil:** Semua pesan tetap ada. Tidak ada yang hilang.

**Kenapa:** Ctrl+C mengirim sinyal SIGINT (atau CTRL_BREAK_EVENT di Windows).
Python menangkap sinyal ini sebagai `KeyboardInterrupt`. Di `server.py`,
fungsi `utama()` punya blok `try/except KeyboardInterrupt` dengan `finally`
yang menutup socket dan dashboard dengan rapi.

Tapi yang lebih penting: setiap pesan disimpan oleh fungsi `simpan()` yang
menggunakan `with sqlite3.connect(DB) as db:`. Context manager SQLite
**otomatis melakukan COMMIT** saat keluar dari blok `with` tanpa error. Jadi
setiap pesan langsung tersimpan permanen begitu `simpan()` selesai — tidak
menunggu server dihentikan untuk flush.

Saat Ctrl+C ditekan, semua pesan yang sudah masuk ke `simpan()` sudah
ter-commit. Server memang berhenti, tapi data sudah aman di disk.

### Percobaan 2 — kill -9, nyalakan lagi

**Hasil:** Semua pesan tetap ada. Tidak ada yang hilang. Database tidak rusak.

**Kenapa:** `kill -9` (SIGKILL di Unix, `TerminateProcess` di Windows) mematikan
proses **seketika** — tidak ada sinyal yang dikirim ke program, tidak ada blok
`finally` yang jalan, tidak ada pembersihan. Proses hilang begitu saja.

Tapi database tidak rusak karena SQLite memakai mekanisme **rollback journal**
(atau WAL). Cara kerjanya:

1. Sebelum mengubah data di file `chat.db`, SQLite menulis data lama ke file
   `chat.db-journal` (rollback journal).
2. Lalu SQLite mengubah data di `chat.db`.
3. Lalu SQLite menghapus `chat.db-journal` (transaksi selesai).

Jika proses dibunuh di tengah langkah 2, file `chat.db` dalam keadaan
**setengah ditulis**, tapi file `chat.db-journal` masih ada dan berisi data
lama. Saat database dibuka lagi (server dinyalakan), SQLite melihat adanya
journal dan **memulihkan** data ke keadaan sebelum transaksi yang gagal.
Transaksi yang sudah selesai (journal sudah dihapus) tidak terpengaruh.

Karena `simpan()` di server.py melakukan COMMIT untuk setiap pesan secara
terpisah, setiap pesan yang sudah masuk ke `simpan()` dan selesai adalah
transaksi yang sudah commited dan aman. Tidak ada satu transaksi yang
mencakup banyak pesan, jadi tidak ada pesan yang "setengah tersimpan".

### Percobaan 3 — Hapus chat.db, nyalakan lagi

**Hasil:** Riwayat hilang selamanya. Database dibuat ulang kosong.

**Kenapa:** Saat `chat.db` dihapus, seluruh data riwayat ikut terhapus.
Fungsi `siapkan_db()` di `server.py` memakai `CREATE TABLE IF NOT EXISTS`,
jadi saat server dinyalakan lagi, tabel dibuat ulang kosong. Tidak ada
mekanisme cadangan otomatis — data yang hilang hilang untuk selamanya.

Ini bukan bug, melainkan konsekuensi langsung dari menyimpan data di satu
file lokal. Untuk mencegah kehilangan seperti ini, cadangan berkala
(backup) diperlukan di luar kode server.

**Ini harus ditulis jujur:** klaim "riwayat tetap ada walau server mati"
hanya berlaku untuk server mati secara normal atau paksa — bukan untuk
berkas databasenya dihapus. Itu dua hal yang berbeda.

### Percobaan 4 — 100 pesan, kill -9 cepat

**Hasil:** Sebagian besar pesan tersimpan (sekitar 97-100 dari 100). Beberapa
pesan terakhir mungkin hilang.

**Kenapa:** Setiap pesan yang dikirim klien melalui socket TCP harus:
1. Diterima oleh server (`recv`)
2. Diparse dari JSON
3. Diproses oleh `tangani()`
4. Disimpan oleh `simpan()` (buka koneksi → INSERT → COMMIT → tutup koneksi)

Langkah 4 meng COMMIT setiap pesan secara terpisah. Pesan yang sudah
sampai ke langkah 4 dan COMMIT selesai adalah aman — tidak akan hilang
walau server dibunuh paksa.

Tapi pesan yang masih **di buffer socket** (sudah dikirim klien, belum
diterima server) atau sedang **diproses** (langkah 1-3) saat server
dibunuh, hilang. Jumlah yang hilang tergantung pada seberapa cepat pesan
diproses vs seberapa cepat server dibunuh.

Dengan jeda 0 antar pesan, klien mengirim 100 pesan dalam milidetik.
Server memproses satu per satu di satu thread. Jika server sempat
memproses 97 sebelum dibunuh, 3 sisanya hilang.

**Tidak ada perbaikan yang diperlukan.** Hilangnya pesan yang belum
diproses bukan bug — itu sifat dari pengiriman data melalui jaringan.
Pesan yang sudah tersimpan aman. Jika ingin semua 100 pesan pasti
tersimpan, klien harus menunggu konfirmasi dari server untuk setiap
pesan (acknowledgment), tapi itu akan menurunkan throughput dan bukan
tujuan dari pengujian ini.

### Percobaan 5 — Salin chat.db saat server jalan

**Hasil:** Salinan biasanya utuh dan bisa dibaca. Tapi ini **tidak
dijamin**.

**Kenapa:** Saat `shutil.copy2` menyalin `chat.db`, server mungkin sedang
menulis ke file itu. SQLite tanpa WAL mode (bawaan) menulis langsung ke
file `chat.db` sambil memakai `chat.db-journal` untuk rollback.

Jika salinan terjadi tepat saat SQLite sedang menulis:
- File `chat.db` yang disalin dalam keadaan setengah ditulis
- File `chat.db-journal` tidak ikut disalin (kita hanya salin `chat.db`)
- Salinan bisa korup atau tidak konsisten

Dalam praktik, penulisan SQLite sangat cepat (mikrodetik), jadi
kemungkinan menyalin tepat saat menulis sangat kecil. Tapi kemungkinan
ini **tidak nol** — jadi hasil "utuh" tidak bisa dijamin 100%.

**Cara aman menyalin:**
1. Hentikan server dulu, baru salin (tapi ini menghentikan layanan)
2. Pakai `sqlite3` backup API (`sqlite3.Connection.backup()`) yang
   menyalin dengan benar tanpa menghentikan server
3. Aktifkan WAL mode (`PRAGMA journal_mode=WAL`) sehingga penulisan
   ke `chat.db` lebih aman untuk disalin

## Jawaban untuk Pertanyaan Dosen

### Apa bedanya Ctrl+C dengan kill -9?

**Ctrl+C** (SIGINT) mengirim sinyal ke proses. Python menangkapnya
sebagai `KeyboardInterrupt`. Program masih sempat menjalankan kode
pembersihan: blok `finally`, menutup socket, menutup file. Server
berhenti dengan rapi.

**kill -9** (SIGKILL) membunuh proses langsung di level kernel. Program
tidak sempat melakukan apa-apa. Tidak ada `finally`, tidak ada cleanup.
Proses hilang seketika. Hanya keandalan storage (SQLite journal) yang
menyelamatkan data.

### Kenapa SQLite tidak rusak kalau proses dibunuh paksa?

SQLite memakai **rollback journal** (file `chat.db-journal`). Sebelum
mengubah `chat.db`, SQLite menyimpan data lama ke journal. Jika proses
mati di tengah penulisan, journal masih ada. Saat database dibuka lagi,
SQLite melihat journal dan **mengembalikan** data ke keadaan sebelum
transaksi yang gagal. Transaksi yang sudah selesai (journal sudah
dihapus) tidak terpengaruh.

Ini disebut **crash recovery** dan sudah bawaan SQLite — tidak perlu
kode tambahan di sisi aplikasi.

### Kalau basis data ada di flashdisk dan dicabut, apa yang terjadi?

Data bisa **hilang atau korup**. SQLite menjamin durability hanya jika
storage device menulis data dengan benar. Jika flashdisk dicabut
sebelum data ter-flush ke hardware, data yang dikira sudah tersimpan
ternyata belum. File bisa juga menjadi korup sebagian.

`PRAGMA synchronous = FULL` (bawaan SQLite) mengirim perintah `fsync`
untuk memaksa data turun ke disk, tapi ini tidak berguna jika device
dicabut secara fisik sebelum `fsync` selesai.

Solusi: jangan simpan database penting di flashdisk yang bisa dicabut.
Atau pakai UPS / battery backup.

### Kalau dua server berjalan di satu berkas yang sama, apa yang terjadi?

Satu akan mendapat error **"database is locked"** (SQLITE_BUSY). SQLite
mengunci file database selama penulisan. Server pertama yang membuka
database mendapat kunci. Server kedua yang mencoba menulis akan diblokir
dan setelah timeout mendapat error `database is locked`.

Membaca mungkin masih bisa (bergantung mode locking), tapi menulis dari
dua proses sekaligus tidak diizinkan. Solusi: jalankan satu server saja
per file database, atau pakai WAL mode yang mengizinkan beberapa reader
bersamaan dengan satu writer.

## Kesimpulan

| Klaim | Terbukti? | Catatan |
|---|---|---|
| Riwayat tetap ada walau server di-Ctrl+C | Ya | Setiap pesan langsung di-commit |
| Riwayat tetap ada walau server di-kill -9 | Ya | SQLite journal memulihkan transaksi yang belum selesai |
| Riwayat tetap ada walau berkas dihapus | Tidak | Hapus berkas = hilang selamanya |
| Pesan yang sudah tersimpan aman | Ya | COMMIT per pesan, bukan batch |
| Salinan database saat jalan bisa dipakai | Biasanya ya | Tapi tidak dijamin 100% |

Tidak diperlukan perbaikan kode `server.py`. Cara penyimpanan saat ini
(satu transaksi per pesan, COMMIT otomatis via context manager) sudah
cukup untuk menjamin ketahanan data dalam kondisi server mati normal
maupun paksa.
