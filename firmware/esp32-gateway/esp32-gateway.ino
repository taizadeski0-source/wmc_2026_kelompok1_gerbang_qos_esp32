/*
 * esp32-gateway — gerbang WiFi + pencatat pemakaian per perangkat
 *
 * Peran papan ini (docs/arsitektur.md):
 *   - klien (STA)  : tersambung ke hotspot 2,4 GHz yang menyediakan internet
 *   - hotspot (AP) : menampung sampai 4 perangkat yang diukur
 *   - NAPT         : meneruskan trafik perangkat uji ke jalur uplink
 *   - pencatat     : menghitung byte/paket per perangkat, mencatat nama domain
 *                    dari pertanyaan DNS, dan mengukur waktu sambung ke internet
 *   - pengirim     : semua catatan dikirim ke laptop lewat kabel USB (serial),
 *                    bukan lewat jaringan. Papan tidak menyimpan riwayat.
 *
 * Cara menghitung: papan mendengarkan bingkai 802.11 di kanalnya sendiri
 * (mode promiscuous, hanya bingkai data). Untuk setiap perangkat yang dikenal,
 * dijumlahkan besar bingkai naik (dari perangkat) dan turun (ke perangkat),
 * jumlah bingkai, serta jumlah bingkai yang ditandai ulang (retry) — angka
 * retry inilah yang dipakai sebagai petunjuk packet loss di sisi radio.
 *
 * Batas yang perlu diketahui:
 *   - Angka byte dihitung dari bingkai 802.11 (bukan hanya isi IP), jadi
 *     beberapa persen lebih besar daripada hitungan di laptop.
 *   - Bingkai yang diulang ikut terhitung dua kali; itu disengaja, karena
 *     pengulangan itu memang memakan waktu udara.
 *   - Isi HTTPS/QUIC tidak dibaca. Yang terlihat hanya nama domain dari DNS
 *     biasa; aplikasi yang memakai DNS terenkripsi atau IP langsung tidak
 *     tercatat namanya.
 *
 * Format baris serial (CSV satu arah, 115200 baud):
 *   hb,<ms>,<jumlah_klien>,<rssi_uplink>,<heap>
 *   st,<mac>,<ip>,<rssi>                                  (tiap 1 detik per perangkat)
 *   tr,<mac>,<ip>,<byte_naik>,<byte_turun>,<bingkai_naik>,<bingkai_turun>,<bingkai_retry>
 *   dns,<mac>,<ip>,<nama_domain>                          (saat ada pertanyaan DNS)
 *   rtt,<ms>|rtt,-1                                       (tiap 2 detik, gagal = -1)
 *
 * Board  : ESP32 DevKit V1 (esp32:esp32:esp32), core 3.3.12
 */

#include <WiFi.h>
#include <esp_wifi.h>

// --- Kredensial --------------------------------------------------------------
// Sandi WiFi jangan ditulis di berkas ini (repository publik). Isi
// firmware/esp32-gateway/hotspot.h — berkas itu masuk .gitignore.
// Tanpa hotspot.h, papan tetap menyala sebagai hotspot dan mencatat bingkai,
// hanya saja jalur uplink tidak tersambung (rtt,-1).
#if __has_include("hotspot.h")
  #include "hotspot.h"
#endif

#ifndef UPLINK_SSID
  #define UPLINK_SSID "HP-1"
#endif
#ifndef UPLINK_PASS
  #define UPLINK_PASS "ganti-sandi-disini"
#endif
#ifndef AP_SSID
  #define AP_SSID "esp32-qos"
#endif
#ifndef AP_PASS
  #define AP_PASS "qos12345"
#endif

#define BATAS_KLIEN 4      // HP-2..HP-5; softAP bawaan sanggup 4 klien
#define MAKS_PERANGKAT 8   // ruang tabel (klien + sisa untuk sementara)
#define INTERVAL_LAPOR 1000
#define INTERVAL_RTT 2000
#define BATAS_RTT_MS 2000
// ---------------------------------------------------------------------------

struct Perangkat {
  uint8_t mac[6];
  uint32_t ip;
  uint32_t byte_naik, byte_turun;
  uint32_t bingkai_naik, bingkai_turun, bingkai_retry;
  uint32_t terakhir_lihat;
  bool dipakai;
};

static Perangkat tabel[MAKS_PERANGKAT];
static uint8_t mac_ap[6];
static uint32_t klien = 0;
static uint32_t terakhir_lapor = 0, terakhir_rtt = 0;
static portMUX_TYPE kunci = portMUX_INITIALIZER_UNLOCKED;

// --- status uplink (mode ganda + NAPT) --------------------------------------
// Dilaporkan lewat event handler dan dipakai untuk backoff sambung ulang.
static bool uplink_hidup = false;          // STA tersambung ke hotspot sumber
static uint32_t uplink_coba = 0;           // jumlah percobaan sambung ulang
static unsigned long jeda_sambung = 5000;  // mulai 5 detik, maksimum 60 detik

// ---------------------------------------------------------------- utilitas --

static void kirim(const char *fmt, ...) {
  char buf[160];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.println(buf);
}

// Antrean baris untuk dipakai dari CALLBACK SNIFFER.
// Serial.println di dalam callback memblokir task driver Wi-Fi: satu baris
// 160 byte pada 115200 baud ≈ 14 ms. Setiap paket DNS membuat driver
// berhenti 14 ms, sehingga throughput anjlok (terukur ~7 KB/s, seharusnya
// ~1 MB/s) dan probe RTT ikut gagal. Baris ditampung dulu di sini, lalu
// dicetak oleh loop() yang bukan task driver.
#define ANTREAN_BARIS 16
#define ANTREAN_PANJANG 96
static char antrean[ANTREAN_BARIS][ANTREAN_PANJANG];
static volatile uint8_t antrean_kepala = 0, antrean_ekor = 0;

static void antre(const char *teks) {
  uint8_t next = (antrean_kepala + 1) % ANTREAN_BARIS;
  if (next == antrean_ekor) return;            // penuh: buang, jangan blokir
  strncpy(antrean[antrean_kepala], teks, ANTREAN_PANJANG - 1);
  antrean[antrean_kepala][ANTREAN_PANJANG - 1] = 0;
  antrean_kepala = next;
}

static void kuras_antrean(void) {
  while (antrean_ekor != antrean_kepala) {
    Serial.println(antrean[antrean_ekor]);
    antrean_ekor = (antrean_ekor + 1) % ANTREAN_BARIS;
  }
}

static void mac_teks(const uint8_t *m, char *out) {
  sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
}

static Perangkat *cari_perangkat(const uint8_t *mac) {
  for (int i = 0; i < MAKS_PERANGKAT; i++) {
    if (tabel[i].dipakai && memcmp(tabel[i].mac, mac, 6) == 0) return &tabel[i];
  }
  for (int i = 0; i < MAKS_PERANGKAT; i++) {
    if (!tabel[i].dipakai) {
      memset(&tabel[i], 0, sizeof(Perangkat));
      memcpy(tabel[i].mac, mac, 6);
      tabel[i].dipakai = true;
      return &tabel[i];
    }
  }
  return nullptr;  // tabel penuh
}

// Alamat IP klien diambil dari sewa DHCP, BUKAN dari isi paket.
// Pada AP ber-WPA2 isi paket terenkripsi sehingga IP sumber/tujuan tidak
// terbaca; sewa DHCP tetap tersedia di sisi papan.
static uint32_t ip_dari_dhcp(const uint8_t *mac) {
  static esp_netif_t *netif_ap = nullptr;
  if (netif_ap == nullptr) netif_ap = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
  if (netif_ap == nullptr) return 0;

  esp_netif_pair_mac_ip_t pasangan[8];
  memset(pasangan, 0, sizeof(pasangan));
  for (int i = 0; i < 8; i++) memcpy(pasangan[i].mac, mac, 6);

  esp_err_t err = esp_netif_dhcps_get_clients_by_mac(netif_ap, 8, pasangan);
  if (err != ESP_OK) return 0;
  for (int i = 0; i < 8; i++) {
    if (memcmp(pasangan[i].mac, mac, 6) == 0) {
      // esp_ip4_addr_t.addr disimpan urutan jaringan (big-endian). Dibaca
      // sebagai uint32_t di ESP32 (little-endian) hasilnya terbalik, jadi
      // oktet diambil satu per satu agar tidak bergantung endianness.
      const uint8_t *b = (const uint8_t *)&pasangan[i].ip.addr;
      return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) |
             ((uint32_t)b[2] << 8) | (uint32_t)b[3];
    }
  }
  return 0;
}

static bool dari_papan(const uint8_t *mac) { return memcmp(mac, mac_ap, 6) == 0; }

// ------------------------------------------------------------- baca DNS ----

// Ambil nama domain dari paket DNS (port 53). Hanya bentuk paling umum:
// satu pertanyaan, label biasa, tanpa kompresi.
static void catat_dns(const uint8_t *dns, int len, uint32_t ip_klien, const uint8_t *mac_klien) {
  if (len < 13) return;
  uint16_t qdcount = (dns[4] << 8) | dns[5];
  if (qdcount < 1) return;

  char nama[80];
  int pos = 12, out = 0;
  while (pos < len && out < (int)sizeof(nama) - 2) {
    uint8_t panjang = dns[pos++];
    if (panjang == 0) break;
    if (panjang > 63) return;             // label panjang = bukan nama biasa
    if (pos + panjang > len) return;
    if (out) nama[out++] = '.';
    for (int i = 0; i < panjang && out < (int)sizeof(nama) - 2; i++) {
      char c = (char)dns[pos + i];
      nama[out++] = (c > 32 && c < 127) ? c : '?';
    }
    pos += panjang;
  }
  if (out < 4) return;                    // terlalu pendek untuk nama domain
  nama[out] = 0;

  char teks_mac[18];
  mac_teks(mac_klien, teks_mac);
  // Dipanggil dari callback sniffer, jadi masuk antrean (lihat antre()).
  char baris[ANTREAN_PANJANG];
  snprintf(baris, sizeof(baris), "dns,%s,%u.%u.%u.%u,%s", teks_mac,
           (ip_klien >> 24) & 0xFF, (ip_klien >> 16) & 0xFF,
           (ip_klien >> 8) & 0xFF, ip_klien & 0xFF, nama);
  antre(baris);
}

// --------------------------------------------------- hitung bingkai 802.11 --

static void hitung_bingkai(const uint8_t *f, int len, bool retry) {
  if (len < 24) return;
  if ((f[0] & 0x0C) != 0x08) return;          // hanya bingkai data

  bool qos = (f[0] & 0x80) != 0;               // QoS data: header lebih panjang
  int hdr = qos ? 26 : 24;
  if (len < hdr) return;

  // Alamat MAC ada di HEADER 802.11 dan selalu dikirim tanpa enkripsi,
  // meskipun payload-nya dienkripsi WPA2. Jadi arah dan pemilik bingkai
  // bisa ditentukan tanpa mendekripsi apa pun.
  const uint8_t *addr1 = f + 4;   // penerima di radio
  const uint8_t *addr2 = f + 10;  // pengirim di radio

  Perangkat *p = nullptr;
  bool naik = false;
  if (dari_papan(addr1) && !dari_papan(addr2)) {        // perangkat -> papan
    p = cari_perangkat(addr2);
    naik = true;
  } else if (dari_papan(addr2) && !dari_papan(addr1)) { // papan -> perangkat
    p = cari_perangkat(addr1);
  } else {
    return;                                      // bukan trafik perangkat kita
  }
  if (!p) return;

  // Hitung byte SEBELUM mencoba membaca isi paket. Dulu pemeriksaan LLC/IP
  // dilakukan lebih awal, sehingga pada AP ber-WPA2 semua bingkai ditolak
  // (payload terenkripsi, tidak pernah 0xAA 0xAA 0x03) dan seluruh angka
  // perangkat selalu nol tanpa pesan galat apa pun.
  portENTER_CRITICAL_ISR(&kunci);
  p->terakhir_lihat = millis();
  if (naik) {
    p->byte_naik += len;
    p->bingkai_naik++;
  } else {
    p->byte_turun += len;
    p->bingkai_turun++;
  }
  if (retry) p->bingkai_retry++;

  // Isi paket hanya bisa dibaca bila jaringannya TERBUKA (tanpa sandi).
  // Pada WPA2 bagian ini dilewati: IP dan nama domain tidak tersedia,
  // tetapi byte dan jumlah bingkai per perangkat tetap terhitung.
  const uint8_t *llc = f + hdr;
  int ip_len = len - hdr;
  bool terbaca = (ip_len >= 8 + 20)
                 && llc[0] == 0xAA && llc[1] == 0xAA && llc[2] == 0x03
                 && llc[6] == 0x08 && llc[7] == 0x00;   // IPv4 saja
  if (terbaca) {
    const uint8_t *ip = llc + 8;
    ip_len -= 8;
    if ((ip[0] >> 4) == 4) {
      int hdr_ip = (ip[0] & 0x0F) * 4;
      if (hdr_ip >= 20 && ip_len >= hdr_ip) {
        uint32_t sumber = ((uint32_t)ip[12] << 24) | ((uint32_t)ip[13] << 16) |
                          ((uint32_t)ip[14] << 8) | ip[15];
        uint32_t tujuan = ((uint32_t)ip[16] << 24) | ((uint32_t)ip[17] << 16) |
                          ((uint32_t)ip[18] << 8) | ip[19];
        p->ip = naik ? sumber : tujuan;

        // Pertanyaan DNS dari perangkat: protokol UDP, port tujuan 53.
        if (naik && ip[9] == 17 && ip_len >= hdr_ip + 8) {
          const uint8_t *udp = ip + hdr_ip;
          uint16_t port_tujuan = (udp[2] << 8) | udp[3];
          int panjang_udp = (udp[4] << 8) | udp[5];
          if (port_tujuan == 53 && panjang_udp > 12 && ip_len >= hdr_ip + 8 + 12) {
            catat_dns(udp + 8, min((int)panjang_udp, ip_len - hdr_ip - 8), sumber, p->mac);
          }
        }
      }
    }
  }
  portEXIT_CRITICAL_ISR(&kunci);
}

static void pada_bingkai(void *buf, wifi_promiscuous_pkt_type_t tipe) {
  if (tipe != WIFI_PKT_DATA) return;
  const wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)buf;
  const uint8_t *f = pkt->payload;
  int len = pkt->rx_ctrl.sig_len - 4;              // buang FCS
  bool retry = (f[1] & 0x08) != 0;                 // bit retry pada frame control
  hitung_bingkai(f, len, retry);
}

// ------------------------------------------------------------------ RTT ----

// Waktu sambung TCP ke DNS publik: angka kasar kualitas jalur uplink.
static long ukur_rtt() {
  if (WiFi.status() != WL_CONNECTED) return -1;
  WiFiClient c;
  unsigned long t0 = millis();
  bool ok = c.connect("1.1.1.1", 53, BATAS_RTT_MS);
  long hasil = ok ? (long)(millis() - t0) : -1;
  c.stop();
  return hasil;
}

// ------------------------------------------------------------- peristiwa ----

static void pada_peristiwa(WiFiEvent_t ev, WiFiEventInfo_t info) {
  if (ev == ARDUINO_EVENT_WIFI_AP_STACONNECTED || ev == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    klien = WiFi.softAPgetStationNum();
    const uint8_t *m = (ev == ARDUINO_EVENT_WIFI_AP_STACONNECTED)
                           ? info.wifi_ap_staconnected.mac
                           : info.wifi_ap_stadisconnected.mac;
    char teks[18];
    mac_teks(m, teks);
    kirim("ev,%s,%s", ev == ARDUINO_EVENT_WIFI_AP_STACONNECTED ? "connect" : "disconnect", teks);
  }
  // --- sisi STA (uplink ke internet) ---
  // Melaporkan setiap kali jalur uplink tersambung atau terputus, supaya
  // penyebab masalah internet langsung terlihat di monitor serial tanpa
  // harus menebak dari baris hb saja.
  if (ev == ARDUINO_EVENT_WIFI_STA_CONNECTED) {
    uplink_hidup = true;
    uplink_coba = 0;
    jeda_sambung = 5000;
    kirim("# uplink tersambung, kanal %d", WiFi.channel());
  }
  if (ev == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    uplink_hidup = false;
    kirim("# uplink terputus (alasan %u), sambung ulang otomatis",
          info.wifi_sta_disconnected.reason);
  }
}

// ---------------------------------------------------------------- setup ----

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("# esp32-gateway siap; format: hb, st, tr, dns, rtt, ev");

  WiFi.onEvent(pada_peristiwa);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASS, 6, 0, BATAS_KLIEN);
  bool napt_ok = WiFi.AP.enableNAPT(true);

  // Urutan WAJIB: softAP() dulu, baru softAPConfig(). Kalau dibalik,
  // softAP() menimpa konfigurasi netif dan parameter dns hilang — DHCP
  // kembali membagikan 192.168.4.1 (papan itu sendiri) sebagai DNS,
  // padahal papan tidak menjalankan server DNS. Akibatnya HP gagal
  // resolusi nama, menandai WiFi "tanpa internet", lalu memutus sendiri.
  // Parameter ke-5 adalah DNS yang dikirim ke klien lewat DHCP option 6.
  WiFi.softAPConfig(IPAddress(192, 168, 4, 1),   // IP papan di jaringan AP
                    IPAddress(192, 168, 4, 1),   // gateway
                    IPAddress(255, 255, 255, 0), // subnet
                    IPAddress(192, 168, 4, 2),   // awal sewa DHCP
                    IPAddress(1, 1, 1, 1));      // DNS untuk klien
  // Ambil 6 byte BINER alamat MAC AP. WiFi.softAPmacAddress() tanpa argumen
  // mengembalikan String "84:1F:E8:27:C6:18", jadi .c_str() + memcpy 6 akan
  // mengambil karakter ASCII '8','4',':','1','F',':' — bukan alamat MAC.
  // Akibatnya dari_papan() tidak pernah cocok dan hitung_bingkai() selalu
  // mengabaikan semua trafik (data per perangkat selalu nol).
  // Varian dengan argumen filling array 6 byte langsung dengan alamat biner.
  WiFi.softAPmacAddress(mac_ap);

  WiFi.begin(UPLINK_SSID, UPLINK_PASS);
  unsigned long mulai = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - mulai < 20000) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("# uplink %s, ip %s, kanal %d\n", WiFi.SSID().c_str(),
                  WiFi.localIP().toString().c_str(), WiFi.channel());
  } else {
    Serial.println("# uplink gagal; perangkat uji belum punya internet");
  }
  // AP dan STA berbagi satu radio, jadi kanal AP dipaksa ikut kanal uplink.
  // Bila uplink di kanal 12-13, banyak HP menolak/tidak stabil — dicatat
  // supaya penyebabnya langsung terlihat saat uji.
  {
    int kanal_ap = WiFi.channel();
    Serial.printf("# AP %s, ip %s, kanal %d, NAPT %s%s\n", AP_SSID,
                  WiFi.softAPIP().toString().c_str(), kanal_ap,
                  napt_ok ? "aktif" : "GAGAL!",
                  (kanal_ap >= 12) ? " (KANAL 12-13: banyak HP menolak!)" : "");
  }

  // Dengarkan bingkai data di kanal sendiri untuk menghitung pemakaian.
  wifi_promiscuous_filter_t saring;
  saring.filter_mask = WIFI_PROMIS_FILTER_MASK_DATA;
  esp_wifi_set_promiscuous_filter(&saring);
  esp_wifi_set_promiscuous_rx_cb(pada_bingkai);
  esp_wifi_set_promiscuous(true);
}

// ----------------------------------------------------------------- loop ----

void loop() {
  static unsigned long cek = 0;
  if (millis() - cek > jeda_sambung) {
    cek = millis();
    if (WiFi.status() != WL_CONNECTED) {
      WiFi.reconnect();
      uplink_coba++;
      // backoff eksponensial: 5, 10, 20, 40, 60, 60, ... detik (maks 60)
      uint32_t kali = 1;
      for (uint32_t i = 0; i < uplink_coba && i < 4; i++) kali *= 2;
      jeda_sambung = min(5000UL * kali, 60000UL);
      kirim("# sambung ulang uplink, coba ke-%lu, jeda %lu ms",
            (unsigned long)uplink_coba, (unsigned long)jeda_sambung);
    } else {
      jeda_sambung = 5000;
    }
  }

  // Cetak baris DNS yang ditampung callback sniffer. loop() bukan task
  // driver Wi-Fi, jadi menulis Serial di sini tidak menghentikan jaringan.
  kuras_antrean();

  if (millis() - terakhir_lapor >= INTERVAL_LAPOR) {
    terakhir_lapor = millis();

    // Daftar klien beserta kekuatan sinyal (dari sisi papan).
    wifi_sta_list_t daftar;
    if (esp_wifi_ap_get_sta_list(&daftar) == ESP_OK) {
      for (int i = 0; i < daftar.num; i++) {
        char teks[18];
        mac_teks(daftar.sta[i].mac, teks);
        Perangkat *p = cari_perangkat(daftar.sta[i].mac);
        // IP dari sewa DHCP; isi paket tidak terbaca pada AP ber-WPA2.
        uint32_t ip = p ? (p->ip ? p->ip : ip_dari_dhcp(daftar.sta[i].mac)) : 0;
        if (p && ip && !p->ip) p->ip = ip;
        kirim("st,%s,%u.%u.%u.%u,%d", teks, (ip >> 24) & 0xFF, (ip >> 16) & 0xFF, (ip >> 8) & 0xFF,
              ip & 0xFF, daftar.sta[i].rssi);
      }
    }

    portENTER_CRITICAL(&kunci);
    for (int i = 0; i < MAKS_PERANGKAT; i++) {
      if (!tabel[i].dipakai) continue;
      char teks[18];
      mac_teks(tabel[i].mac, teks);
      uint32_t ip = tabel[i].ip;
      kirim("tr,%s,%u.%u.%u.%u,%lu,%lu,%lu,%lu,%lu", teks, (ip >> 24) & 0xFF, (ip >> 16) & 0xFF,
            (ip >> 8) & 0xFF, ip & 0xFF, (unsigned long)tabel[i].byte_naik,
            (unsigned long)tabel[i].byte_turun, (unsigned long)tabel[i].bingkai_naik,
            (unsigned long)tabel[i].bingkai_turun, (unsigned long)tabel[i].bingkai_retry);
    }
    portEXIT_CRITICAL(&kunci);

    long rssi = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0;
    kirim("hb,%lu,%u,%ld,%u", millis(), klien, rssi, (unsigned)ESP.getFreeHeap());
  }

  if (millis() - terakhir_rtt >= INTERVAL_RTT) {
    terakhir_rtt = millis();
    kirim("rtt,%ld", ukur_rtt());
  }
}
