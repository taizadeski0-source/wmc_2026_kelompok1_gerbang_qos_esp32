# Pengujian

## Yang Perlu Disiapkan

- 1 papan ESP32 DevKit, 1 kabel USB-C, 1 adaptor daya cadangan.
- 5 telepon genggam: satu sebagai sumber internet (hotspot 2,4 GHz), empat sebagai objek ukur.
- Laptop dengan Python 3.10+ dan port USB.

## Urutan Menjalankan

```bash
# 1. Unggah firmware gerbang (isi SSID/sandi lebih dulu di berkas .ino)
arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p /dev/cu.usbserial-XXXX firmware/esp32-gateway

# 2. Lihat catatan mentah dari kabel USB
arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=115200

# 3. Jalankan penerima + dashboard (terminal lain; monitor serial ditutup dulu)
python3 src/penerima/penerima.py --uji            # cek pengurai, tanpa papan
python3 src/penerima/penerima.py --port /dev/cu.usbserial-XXXX --sesi S1
```

Dashboard: <http://127.0.0.1:8080>. Hasil masuk `data/qos.db`, CSV lewat
`/api/ekspor.csv`. Port serial hanya boleh dibuka satu program — tutup `arduino-cli
monitor` sebelum menjalankan penerima, kalau tidak kedua program berebut.

Urutan nyala yang dipakai setiap sesi:

1. Hotspot HP-1 dinyalakan (2,4 GHz, WPA2, tanpa mode hemat daya).
2. ESP32 dicolok ke laptop, monitor serial dibuka sampai muncul `# uplink ... ip ...`.
3. Perangkat uji disambungkan ke hotspot `ESP32-QoS`.
4. Kegiatan dijalankan sesuai skenario, dicatat waktu mulai dan selesainya.

> [!warning] Angka harus dari perangkat nyata
> Catatan dari simulator (Wokwi) hanya sah untuk membuktikan packet loss, throughput,
> dan perbandingan relatif antar protokol. Latency dan jitter absolut dari simulator
> **tidak sah** karena jam simulasi berjalan lebih lambat daripada jam dinding —
> pada pengujian 21 Oktober 2026 selisihnya mencapai 36 detik. Angka latency dari
> simulator tidak boleh masuk laporan.

## Cara Angka Dihitung

| Angka | Sumber |
|---|---|
| Byte/paket per perangkat | Bingkai 802.11 data yang tertangkap papan, dijumlahkan per alamat MAC |
| Retry (%) | Bingkai yang punya bit *retry* dibagi seluruh bingkai perangkat itu — petunjuk packet loss di radio, bukan hitungan paket hilang yang pasti |
| Laju (kbps) | Selisih angka kumulatif antar laporan, dibagi jarak waktu, dikali 8 |
| Waktu sambung uplink | Selisih waktu `connect()` TCP papan ke 1.1.1.1:53, diukur tiap 2 detik |
| Nama domain | Isi pertanyaan DNS biasa dari perangkat; DNS terenkripsi (DoH/DoT) tidak terlihat |
| Kekuatan sinyal | `esp_wifi_ap_get_sta_list()` dari sisi papan |

Karena dihitung dari bingkai 802.11 (termasuk header radio dan bingkai yang diulang),
angka byte beberapa persen lebih besar daripada hitungan di sisi perangkat. Hal ini
wajib disebut saat membandingkan dengan angka dari telepon.

## Batas Nilai yang Diharapkan

Angka ini ditetapkan sebelum mengukur, sebagai patokan penilaian — bukan hasil.

| Parameter | Batas yang diharapkan |
|---|---|
| Waktu sambung uplink (pengganti latency) | di bawah 150 ms |
| Packet loss | di bawah 2 % |
| Jitter | di bawah 50 ms |
| Throughput | di atas 800 kbps total |

## Skenario

Setiap skenario dijalankan lima menit dan diulang tiga kali; yang dilaporkan adalah
nilai tengahnya. Kegiatan yang dijalankan sama di semua skenario: menggulir media
sosial, memutar video, dan mengunduh satu berkas.

| Skenario | Jumlah perangkat aktif | Yang dijalankan |
|---|---|---|
| S1 | 1 perangkat | Menggulir media sosial |
| S2 | 1 perangkat | Mengunduh berkas besar |
| S3 | 2 perangkat | Satu menggulir, satu mengunduh |
| S4 | 4 perangkat | Semua aktif bersamaan |
| S5 | 4 perangkat tanpa kegiatan | Pengukuran dasar (pembanding) |

Tambahan yang dicatat di luar skenario utama:

| Uji tambahan | Yang divariasikan | Yang diamati |
|---|---|---|
| Jarak | Perangkat pada 1 m, 4 m, 8 m dari ESP32 | Packet loss, jitter |
| Penghalang | Dinding atau tubuh di antara perangkat dan ESP32 | Packet loss |
| Kanal padat | Ruangan ramai perangkat 2,4 GHz | Latency, jitter |
| Uplink putus | Hotspot HP-1 dimatikan saat pengujian | Waktu sambung ulang, perilaku dashboard |

## Hal yang Wajib Dicatat Tiap Sesi

- Tanggal, jam mulai, dan jam selesai.
- Skenario yang dijalankan dan jumlah perangkat aktif.
- Kondisi ruangan: jumlah orang, perkiraan jumlah jaringan WiFi 2,4 GHz yang terlihat.
- Jarak perangkat ke ESP32 dan posisi ponsel (di tangan, di meja, di kantong).
- Kanal hotspot, model ponsel, dan operator seluler sumber internet.

## Tabel Hasil

| Skenario | Tanggal | Latency (ms) | Packet loss (%) | Jitter (ms) | Throughput (kbps) | Catatan |
|---|---|---|---|---|---|---|
| S1 — 1 perangkat, gulir | Belum diukur | — | — | — | — | — |
| S2 — 1 perangkat, unduh | Belum diukur | — | — | — | — | — |
| S3 — 2 perangkat | Belum diukur | — | — | — | — | — |
| S4 — 4 perangkat | Belum diukur | — | — | — | — | — |
| S5 — 4 perangkat diam | Belum diukur | — | — | — | — | — |
| Jarak 1 / 4 / 8 m | Belum diukur | — | — | — | — | — |
| Penghalang | Belum diukur | — | — | — | — | — |
| Kanal padat | Belum diukur | — | — | — | — | — |
| Uplink putus | Belum diukur | — | — | — | — | — |

## Yang Sudah Terbukti (Simulator, 21–28 Oktober 2026)

Pengujian di Wokwi dipakai untuk memastikan firmware dan penerima bekerja sebelum
perangkat keras tersedia. Hasilnya **bukan** data laporan, tetapi berguna sebagai bukti
bahwa pengiriman dan penghitungan tidak salah:

- 192 paket diterima, nomor urut 582–773 tanpa lompatan, 0 % hilang, ±3,97 paket/detik
  pada interval kirim 250 ms.
- Latency tercatat 1.918,65 ms dan jitter 246,88 ms — **tidak sah**, penyebabnya
  selisih jam simulasi seperti dijelaskan di atas.
- QoS 0 terbukti berjalan. QoS 1 dan 2 sudah dapat dikompilasi tetapi belum dijalankan.

Berkas bukti pengujian simulator disimpan pada folder kerja terpisah di luar repository.
