# Pengujian Firmware — Mode Ganda + NAPT

**Tanggung jawab:** Deski Taiza (23210003)
**Berkait:** `firmware/esp32-gateway/esp32-gateway.ino`, `firmware/uji-mode-ganda/uji-mode-ganda.ino`, `docs/arsitektur.md`

## Tujuan

Membuktikan di papan ESP32 sungguhan bahwa:

1. ESP32 bekerja dalam dua peran radio sekaligus (STA + AP).
2. NAPT meneruskan internet dari uplink ke perangkat uji.
3. Sambung ulang otomatis bekerja saat uplink putus.
4. Konfigurasi DHCP benar (DNS 1.1.1.1 terbagi ke klien, bukan IP papan).

## Prasyarat

| Alat | Jumlah | Keterangan |
|---|---|---|
| ESP32 DevKit V1 | 1 | papan firmware |
| Kabel USB-C | 1 | ke laptop |
| HP sumber internet | 1 | hotspot 2,4 GHz, WPA2, tanpa mode hemat daya |
| HP perangkat uji | 1+ | tersambung ke hotspot ESP32 |
| Laptop | 1 | Arduino CLI terpasang, Python 3.10+ |

## Persiapan

### Isi kredensial

```bash
cp firmware/esp32-gateway/hotspot.h.example firmware/esp32-gateway/hotspot.h
# Edit hotspot.h: isi UPLINK_SSID, UPLINK_PASS dengan nama dan sandi hotspot HP
```

Berkas `hotspot.h` masuk `.gitignore` dan tidak akan masuk repository.

### Pastikan Arduino CLI mengenal ESP32

```bash
arduino-cli core list | grep esp32:esp32
# kalau belum terpasang:
arduino-cli core install esp32:esp32:esp32
```

## Tahap 1 — Uji Terisolasi (skets `uji-mode-ganda`)

Skets ini HANYA menguji mode ganda + NAPT, tanpa promiscuous, tanpa hitung
per perangkat, tanpa DNS. Tujuannya: membuktikan inti tugas tanpa pengaruh
bagian lain. Jika tahap ini gagal, masalah ada di mode ganda atau NAPT, bukan
di kode bagian Wira.

### Langkah

1. **Unggah skets uji:**

   ```bash
   arduino-cli compile --fqbn esp32:esp32:esp32 \
     --upload -p /dev/cu.usbserial-XXXX firmware/uji-mode-ganda
   ```

2. **Buka monitor serial (115200 baud):**

   ```bash
   arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=115200
   ```

3. **Tunggu sampai muncul:**

   ```
   # AP esp32-qos-uji, ip 192.168.4.1, kanal 6, NAPT AKTIF, batas 4 klien
   # menghubungkan ke uplink "HP-1" ...
   # uplink HP-1, ip 192.168.43.12, kanal 6
   # AP kanal sekarang: 6
   ```

   Jika NAPT tertulis **GAGAL**, perangkat uji tidak akan mendapat internet.
   Pastikan core ESP32 >= 3.x (`arduino-cli core list`).

4. **Sambungkan HP ke hotspot `esp32-qos-uji`** (sandi: `qos12345`).

   Monitor harus menampilkan:

   ```
   # perangkat uji tersambung: 3c:5a:b4:11:22:33
   ```

5. **Buka browser di HP, kunjungi `http://1.1.1.1`.**

   - Halaman terbuka -> **mode ganda + NAPT bekerja.**
   - Tidak terbuka -> lanjut ke "Penanganan Masalah" di bawah.

6. **Uji sambung ulang:** matikan hotspot HP sumber.

   Monitor harus menampilkan:

   ```
   # uplink TERPUTUS (alasan 201), sambung ulang otomatis
   # sambung ulang uplink, coba ke-1, tunggu 5000 ms
   # sambung ulang uplink, coba ke-2, tunggu 10000 ms
   # sambung ulang uplink, coba ke-3, tunggu 20000 ms
   ```

   Nyalakan lagi hotspot sumber. Dalam 5-10 detik harus muncul:

   ```
   # uplink TERSAMBUNG, kanal 6
   ```

### Yang dibuktikan di tahap 1

- [ ] AP menyala dengan IP 192.168.4.1
- [ ] NAPT tertulis AKTIF
- [ ] STA tersambung ke uplink, mendapat IP
- [ ] Kanal AP mengikuti kanal uplink
- [ ] Perangkat uji tersambung ke AP
- [ ] Perangkat uji bisa membuka halaman web (NAPT meneruskan internet)
- [ ] Saat uplink putus, sambung ulang otomatis bekerja
- [ ] Backoff eksponensial: 5, 10, 20, 40, 60 detik

## Tahap 2 — Uji Firmware Lengkap (`esp32-gateway`)

Setelah tahap 1 lulus, uji firmware lengkap yang juga mencatat pemakaian per
perangkat (bagian Wira). Tutup monitor serial dulu sebelum menjalankan
penerima.

1. **Unggah firmware lengkap:**

   ```bash
   arduino-cli compile --fqbn esp32:esp32:esp32 \
     --upload -p /dev/cu.usbserial-XXXX firmware/esp32-gateway
   ```

2. **Buka monitor serial, tunggu `# uplink ...`:**

   ```
   # esp32-gateway siap; format: hb, st, tr, dns, rtt, ev
   # uplink HP-1, ip 192.168.43.12, kanal 6
   # AP esp32-qos, ip 192.168.4.1, kanal 6, NAPT aktif
   ```

3. **Sambungkan HP ke `esp32-qos`, buka aplikasi.**

   Monitor harus menampilkan baris `ev,connect,...` dan `hb,...` tiap detik.

4. **Tutup monitor, jalankan penerima + dashboard:**

   ```bash
   python3 src/penerima/penerima.py --port /dev/cu.usbserial-XXXX --sesi S1
   ```

   Buka `http://127.0.0.1:8080`.

### Yang dibuktikan di tahap 2

- [ ] Keluaran serial sama format dengan dokumentasi (`hb`, `st`, `tr`, `dns`, `rtt`, `ev`)
- [ ] NAPT tertulis `aktif` di baris `# AP ...`
- [ ] Perangkat uji mendapat internet lewat `esp32-qos`
- [ ] Dashboard menampilkan perangkat dan pemakaian
- [ ] Tidak ada pesan `# uplink terputus` yang berulang tanpa henti

## Tahap 3 — Uji Batas dan Kondisi Tepi

### Kanal 12-13

Jika hotspot HP sumber berada di kanal 12 atau 13, monitor menampilkan
peringatan `(KANAL 12-13: banyak HP menolak!)`. Beberapa HP menolak
tersambung ke AP di kanal tersebut. Solusi: pindahkan hotspot sumber ke
kanal 1-11.

### Empat perangkat bersamaan

Sambungkan 4 HP sekaligus ke `esp32-qos`. Semua harus mendapat internet.
SoftAP bawaan ESP32 sanggup 4 klien (BATAS_KLIEN = 4).

### Hotspot sumber tidur

Beberapa hotspot HP mematikan diri saat tidak ada trafik. Setelah idle
beberapa menit, uplink bisa putus. Firmware akan sambung ulang otomatis
dengan backoff. Untuk mencegah: matikan mode hemat daya hotspot HP.

## Penanganan Masalah

| Gejala | Kemungkinan penyebab | Solusi |
|---|---|---|
| NAPT tertulis GAGAL | Core ESP32 < 3.x | `arduino-cli core install esp32:esp32:esp32` |
| HP tersambung tapi "tanpa internet" | DNS tidak terbagi dengan benar | Pastikan `softAPConfig()` dipanggil setelah `softAP()`, parameter ke-5 = 1.1.1.1 |
| HP tidak mau tersambung sama sekali | Kanal 12-13, atau sandi salah | Cek kanal di monitor, cek AP_PASS |
| Uplink gagal dalam 20 detik | Hotspot HP mati / di luar jangkauan / sandi salah | Cek hotspot HP, cek UPLINK_SSID dan UPLINK_PASS di hotspot.h |
| Sambung ulang terus tanpa henti | Hotspot HP di luar jangkauan | Dekatkan ESP32 ke HP sumber |
| Perangkat uji bisa ping tapi tidak bisa buka web | DNS tidak terbagi | Pastikan parameter ke-5 softAPConfig adalah 1.1.1.1 |

## Bukti yang Perlu Dicatat

Setiap pengujian dicatat:

1. Tanggal dan jam.
2. Model papan ESP32 dan versi core (`arduino-cli core list`).
3. SSID dan kanal hotspot sumber.
4. Berapa perangkat uji yang dicoba.
5. Tangkapan layar monitor serial saat `# uplink TERSAMBUNG`.
6. Tangkapan layar HP membuka halaman web lewat `esp32-qos`.
7. Tangkapan layar monitor saat uplink putus dan sambung ulang.
8. Catatan: apakah ada masalah dan bagaimana diselesaikan.
