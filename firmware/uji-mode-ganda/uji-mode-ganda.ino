/*
 * uji-mode-ganda — verifikasi mode ganda (STA + AP) + NAPT pada ESP32
 *
 * Skets ini HANYA menguji bagian mode ganda + NAPT, tanpa promiscuous,
 * tanpa hitung per perangkat, tanpa DNS, tanpa RTT. Tujuan: membuktikan
 * bahwa ESP32 bisa menjadi gerbang WiFi yang meneruskan internet dari
 * uplink ke perangkat uji.
 *
 * Pemakaian:
 *   1. Isi UPLINK_SSID dan UPLINK_PASS di bawah (atau buat hotspot.h
 *      dengan menyalin hotspot.h.example).
 *   2. Unggah ke papan: arduino-cli compile --fqbn esp32:esp32:esp32
 *      --upload -p /dev/cu.usbserial-XXXX firmware/uji-mode-ganda
 *   3. Buka monitor serial 115200.
 *   4. Sambungkan HP ke hotspot "esp32-qos-uji" (sandi: qos12345).
 *   5. Buka halaman web di HP. Kalau terbuka -> mode ganda + NAPT bekerja.
 *   6. Matikan hotspot sumber, lihat sambung ulang otomatis.
 *
 * Keluaran serial:
 *   # uplink tersambung, kanal 6         (STA berhasil sambung ke uplink)
 *   # perangkat uji tersambung: xx:xx:.. (HP tersambung ke AP)
 *   # uplink terputus (alasan 201)       (hotspot sumber mati)
 *   # sambung ulang uplink, coba ke-1    (mulai reconnect dengan backoff)
 *   hb,5000,1,-52,280000,hidup           (denyut: waktu, klien, rssi, heap, uplink)
 *
 * Board: ESP32 DevKit V1 (esp32:esp32:esp32), core 3.x
 * Tanggung jawab: Deski Taiza (23210003) — Firmware mode ganda + NAPT
 */

#include <WiFi.h>

// --- Kredensial --------------------------------------------------------------
// Salin hotspot.h.example menjadi hotspot.h, lalu isi sandi asli.
// Berkas hotspot.h masuk .gitignore.
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
  #define AP_SSID "esp32-qos-uji"
#endif
#ifndef AP_PASS
  #define AP_PASS "qos12345"
#endif

#define BATAS_KLIEN 4      // softAP bawaan ESP32 sanggup 4 klien
// ---------------------------------------------------------------------------

// --- status uplink -----------------------------------------------------------
static bool uplink_hidup = false;
static uint32_t uplink_coba = 0;
static unsigned long jeda_sambung = 5000;   // mulai 5 detik, maksimum 60 detik
static unsigned long cek_sambung = 0;

static void cetak_mac(const uint8_t *m) {
  Serial.printf("%02x:%02x:%02x:%02x:%02x:%02x",
    m[0], m[1], m[2], m[3], m[4], m[5]);
}

static void pada_peristiwa(WiFiEvent_t ev, WiFiEventInfo_t info) {
  // --- sisi STA (uplink ke internet) ---
  if (ev == ARDUINO_EVENT_WIFI_STA_CONNECTED) {
    uplink_hidup = true;
    uplink_coba = 0;
    jeda_sambung = 5000;
    Serial.printf("# uplink TERSAMBUNG, kanal %d\n", WiFi.channel());
  }
  if (ev == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    uplink_hidup = false;
    Serial.printf("# uplink TERPUTUS (alasan %u), sambung ulang otomatis\n",
                  info.wifi_sta_disconnected.reason);
  }

  // --- sisi AP (perangkat uji) ---
  if (ev == ARDUINO_EVENT_WIFI_AP_STACONNECTED) {
    Serial.printf("# perangkat uji tersambung: ");
    cetak_mac(info.wifi_ap_staconnected.mac);
    Serial.println();
  }
  if (ev == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    Serial.printf("# perangkat uji terlepas: ");
    cetak_mac(info.wifi_ap_stadisconnected.mac);
    Serial.println();
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("# === uji-mode-ganda: verifikasi STA + AP + NAPT ===");
  Serial.println("# tanggung jawab: Deski Taiza (23210003)");
  Serial.println();

  WiFi.onEvent(pada_peristiwa);

  // Mode ganda: STA (uplink) + AP (hotspot untuk perangkat uji)
  WiFi.mode(WIFI_AP_STA);

  // Hotspot untuk perangkat uji. Kanal 6 adalah nilai awal;
  // setelah STA tersambung, AP otomatis ikut kanal uplink karena
  // keduanya berbagi satu radio.
  WiFi.softAP(AP_SSID, AP_PASS, 6, 0, BATAS_KLIEN);

  // NAPT: meneruskan trafik dari AP (perangkat uji) ke STA (uplink).
  bool napt_ok = WiFi.AP.enableNAPT(true);

  // Urutan WAJIB: softAP() dulu, baru softAPConfig().
  // Kalau dibalik, softAP() menimpa konfigurasi netif dan parameter
  // DNS hilang. DHCP kembali membagikan 192.168.4.1 (papan sendiri)
  // sebagai DNS, padahal papan tidak menjalankan server DNS. HP gagal
  // resolusi nama, menandai WiFi "tanpa internet", lalu memutus sendiri.
  // Parameter ke-5 adalah DNS yang dikirim ke klien lewat DHCP option 6.
  WiFi.softAPConfig(
    IPAddress(192, 168, 4, 1),    // IP papan di jaringan AP
    IPAddress(192, 168, 4, 1),    // gateway
    IPAddress(255, 255, 255, 0),  // subnet
    IPAddress(192, 168, 4, 2),    // awal sewa DHCP
    IPAddress(1, 1, 1, 1)         // DNS untuk klien
  );

  int kanal_ap = WiFi.channel();
  Serial.printf("# AP %s, ip %s, kanal %d, NAPT %s, batas %d klien\n",
                AP_SSID,
                WiFi.softAPIP().toString().c_str(),
                kanal_ap,
                napt_ok ? "AKTIF" : "GAGAL!",
                BATAS_KLIEN);

  if (!napt_ok) {
    Serial.println("# PERINGATAN: NAPT gagal diaktifkan!");
    Serial.println("#   Perangkat uji akan tersambung ke hotspot tapi tidak");
    Serial.println("#   mendapat internet. Pastikan core ESP32 >= 3.x.");
  }

  // Sambung ke uplink (hotspot HP sumber internet)
  Serial.printf("# menghubungkan ke uplink \"%s\" ...\n", UPLINK_SSID);
  WiFi.begin(UPLINK_SSID, UPLINK_PASS);
  unsigned long mulai = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - mulai < 20000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("# uplink %s, ip %s, kanal %d\n",
                  WiFi.SSID().c_str(),
                  WiFi.localIP().toString().c_str(),
                  WiFi.channel());
    uplink_hidup = true;
  } else {
    Serial.println("# uplink gagal dalam 20 detik pertama");
    Serial.println("# AP tetap menyala; sambung ulang otomatis dengan backoff");
  }

  // Kanal AP sekarang mengikuti kanal uplink (satu radio, dua peran)
  kanal_ap = WiFi.channel();
  Serial.printf("# AP kanal sekarang: %d%s\n", kanal_ap,
                (kanal_ap >= 12) ? " (KANAL 12-13: banyak HP menolak!)" : "");

  Serial.println();
  Serial.println("# === CARA UJI ===");
  Serial.printf("# 1. Sambungkan HP ke WiFi \"%s\" (sandi: %s)\n", AP_SSID, AP_PASS);
  Serial.println("# 2. Buka browser di HP, kunjungi http://1.1.1.1");
  Serial.println("# 3. Kalau halaman terbuka -> mode ganda + NAPT BEKERJA");
  Serial.println("# 4. Matikan hotspot sumber -> lihat sambung ulang otomatis");
  Serial.println("# 5. Nyalakan lagi -> uplink harus tersambung dalam 5-10 detik");
  Serial.println();
}

void loop() {
  // --- sambung ulang uplink dengan backoff eksponensial ---
  // 5, 10, 20, 40, 60, 60, 60, ... detik (maksimum 60 detik)
  if (millis() - cek_sambung > jeda_sambung) {
    cek_sambung = millis();
    if (WiFi.status() != WL_CONNECTED) {
      WiFi.reconnect();
      uplink_coba++;
      uint32_t kali = 1;
      for (uint32_t i = 0; i < uplink_coba && i < 4; i++) kali *= 2;
      jeda_sambung = min(5000UL * kali, 60000UL);
      Serial.printf("# sambung ulang uplink, coba ke-%u, tunggu %lu ms\n",
                    (unsigned)uplink_coba, (unsigned long)jeda_sambung);
    } else {
      jeda_sambung = 5000;
    }
  }

  // --- denyut tiap 5 detik: ringkasan keadaan ---
  static unsigned long terakhir_hb = 0;
  if (millis() - terakhir_hb >= 5000) {
    terakhir_hb = millis();
    int klien = WiFi.softAPgetStationNum();
    long rssi = uplink_hidup ? WiFi.RSSI() : 0;
    Serial.printf("hb,%lu,%d,%ld,%u,%s\n",
                  (unsigned long)millis(), klien, rssi,
                  (unsigned)ESP.getFreeHeap(),
                  uplink_hidup ? "hidup" : "putus");
  }
}
