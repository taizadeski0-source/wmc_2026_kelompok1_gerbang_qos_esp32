#!/usr/bin/env python3
"""Penerima catatan ESP32 lewat kabel USB + dashboard.

Tanpa pustaka luar — hanya modul bawaan Python 3.10+.

Contoh:
    # baca papan sungguhan
    python3 src/penerima/penerima.py --port /dev/cu.usbserial-1130 --sesi S1

    # uji tanpa papan (angka tiruan, jelas ditandai di dashboard)
    python3 src/penerima/penerima.py --sim --durasi 120

    # cek cepat bahwa pengurai dan basis data bekerja
    python3 src/penerima/penerima.py --uji

Dashboard: http://127.0.0.1:8080  (API: /api/state, unduh: /api/ekspor.csv)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import select
import sqlite3
import sys
import termios
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AKAR = Path(__file__).resolve().parents[2]
DASHBOARD = AKAR / "src" / "dashboard" / "index.html"
SKEMA = """
CREATE TABLE IF NOT EXISTS sesi (
  id INTEGER PRIMARY KEY, nama TEXT, mulai TEXT, mode TEXT, catatan TEXT
);
CREATE TABLE IF NOT EXISTS trafik (
  id INTEGER PRIMARY KEY, sesi INTEGER, t REAL, mac TEXT, ip TEXT,
  naik_bps REAL, turun_bps REAL, bingkai_naik INTEGER, bingkai_turun INTEGER, bingkai_ulang INTEGER
);
CREATE TABLE IF NOT EXISTS dns (
  id INTEGER PRIMARY KEY, sesi INTEGER, t REAL, mac TEXT, ip TEXT, nama TEXT
);
CREATE TABLE IF NOT EXISTS rtt (
  id INTEGER PRIMARY KEY, sesi INTEGER, t REAL, ms REAL
);
"""


# ------------------------------------------------------------------ pengurai --

def urai(baris: str) -> dict | None:
    """Ubah satu baris serial menjadi entri. Baris tak dikenal -> None."""
    b = baris.strip()
    if not b or b.startswith("#"):
        return None
    bagian = b.split(",")
    jenis = bagian[0]
    try:
        if jenis == "hb" and len(bagian) >= 5:
            return {"jenis": "hb", "ms": int(bagian[1]), "klien": int(bagian[2]),
                    "rssi": int(bagian[3]), "heap": int(bagian[4])}
        if jenis == "st" and len(bagian) >= 4:
            return {"jenis": "st", "mac": bagian[1].lower(), "ip": bagian[2], "rssi": int(bagian[3])}
        if jenis == "tr" and len(bagian) >= 8:
            return {"jenis": "tr", "mac": bagian[1].lower(), "ip": bagian[2],
                    "naik": int(bagian[3]), "turun": int(bagian[4]),
                    "bingkai_naik": int(bagian[5]), "bingkai_turun": int(bagian[6]),
                    "bingkai_ulang": int(bagian[7])}
        if jenis == "dns" and len(bagian) >= 4:
            return {"jenis": "dns", "mac": bagian[1].lower(), "ip": bagian[2],
                    "nama": ",".join(bagian[3:])}
        if jenis == "rtt" and len(bagian) >= 2:
            return {"jenis": "rtt", "ms": float(bagian[1])}
        if jenis == "ev" and len(bagian) >= 3:
            return {"jenis": "ev", "arah": bagian[1], "mac": bagian[2].lower()}
    except ValueError:
        return None
    return None


# -------------------------------------------------------------- penyimpanan --

class Simpanan:
    def __init__(self, path: Path, sesi_nama: str, mode: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(SKEMA)
        self.mulai = datetime.now(timezone.utc)
        self.db.execute("INSERT INTO sesi (nama, mulai, mode, catatan) VALUES (?,?,?,?)",
                        (sesi_nama, self.mulai.isoformat(timespec="seconds"), mode, ""))
        self.sesi = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.commit()
        self.antre: list[tuple] = []
        self.antre_dns: list[tuple] = []
        self.antre_rtt: list[tuple] = []

    def catat(self, t: float, mac: str, ip: str, naik: float, turun: float,
              bn: int, bt: int, bu: int) -> None:
        self.antre.append((self.sesi, t, mac, ip, naik, turun, bn, bt, bu))

    def catat_dns(self, t: float, mac: str, ip: str, nama: str) -> None:
        self.antre_dns.append((self.sesi, t, mac, ip, nama))

    def catat_rtt(self, t: float, ms: float) -> None:
        self.antre_rtt.append((self.sesi, t, ms))

    def kuras(self) -> None:
        if self.antre:
            self.db.executemany(
                "INSERT INTO trafik (sesi,t,mac,ip,naik_bps,turun_bps,bingkai_naik,bingkai_turun,bingkai_ulang)"
                " VALUES (?,?,?,?,?,?,?,?,?)", self.antre)
            self.antre.clear()
        if self.antre_dns:
            self.db.executemany("INSERT INTO dns (sesi,t,mac,ip,nama) VALUES (?,?,?,?,?)", self.antre_dns)
            self.antre_dns.clear()
        if self.antre_rtt:
            self.db.executemany("INSERT INTO rtt (sesi,t,ms) VALUES (?,?,?)", self.antre_rtt)
            self.antre_rtt.clear()
        self.db.commit()


# ---------------------------------------------------------------- pengumpul --

class Pengumpul:
    """Mengubah angka kumulatif dari papan menjadi laju per detik."""

    def __init__(self, simpanan: Simpanan):
        self.simpanan = simpanan
        self.t0 = time.monotonic()
        self.perangkat_tabel: dict[str, dict] = {}
        self.rtt: list[float] = []
        self.rtt_gagal = 0
        self.histori: list[dict] = []
        self.detik_terakhir = 0.0
        self.klien = 0
        self.rssi_uplink = 0
        self.mode = "serial"

    def perangkat(self, mac: str, ip: str) -> dict:
        return self.perangkat_tabel.setdefault(mac, {
            "mac": mac, "ip": ip, "rssi": 0, "dns": [],
            "kum_naik": 0, "kum_turun": 0, "kum_bn": 0, "kum_bt": 0, "kum_bu": 0,
            "naik_bps": 0.0, "turun_bps": 0.0,
            "bingkai_naik": 0, "bingkai_turun": 0, "bingkai_ulang": 0,
            "detik": 0.0,
        })

    def detik(self) -> float:
        return round(time.monotonic() - self.t0, 1)

    def terima(self, entri: dict) -> None:
        jenis = entri["jenis"]

        if jenis == "tr":
            p = self.perangkat(entri["mac"], entri["ip"])
            p["ip"] = entri["ip"] or p["ip"]
            kini = time.monotonic()
            if p["detik"] == 0.0:
                p.update(kum_naik=entri["naik"], kum_turun=entri["turun"],
                         kum_bn=entri["bingkai_naik"], kum_bt=entri["bingkai_turun"],
                         kum_bu=entri["bingkai_ulang"], detik=kini)
                return
            jeda = max(kini - p["detik"], 0.2)
            d_naik = max(entri["naik"] - p["kum_naik"], 0)
            d_turun = max(entri["turun"] - p["kum_turun"], 0)
            d_bn = max(entri["bingkai_naik"] - p["kum_bn"], 0)
            d_bt = max(entri["bingkai_turun"] - p["kum_bt"], 0)
            d_bu = max(entri["bingkai_ulang"] - p["kum_bu"], 0)
            p.update(kum_naik=entri["naik"], kum_turun=entri["turun"],
                     kum_bn=entri["bingkai_naik"], kum_bt=entri["bingkai_turun"],
                     kum_bu=entri["bingkai_ulang"], detik=kini,
                     naik_bps=d_naik * 8 / jeda, turun_bps=d_turun * 8 / jeda,
                     bingkai_naik=d_bn, bingkai_turun=d_bt, bingkai_ulang=d_bu)
            self.simpanan.catat(self.detik(), entri["mac"], p["ip"], p["naik_bps"], p["turun_bps"],
                                d_bn, d_bt, d_bu)

        elif jenis == "st":
            p = self.perangkat(entri["mac"], entri["ip"])
            p["rssi"] = entri["rssi"]
            if entri["ip"] and entri["ip"] != "0.0.0.0":
                p["ip"] = entri["ip"]

        elif jenis == "dns":
            p = self.perangkat(entri["mac"], entri["ip"])
            if entri["nama"] not in p["dns"]:
                p["dns"] = ([entri["nama"]] + p["dns"])[:8]
            self.simpanan.catat_dns(self.detik(), entri["mac"], entri["ip"], entri["nama"])

        elif jenis == "rtt":
            if entri["ms"] >= 0:
                self.rtt = (self.rtt + [entri["ms"]])[-60:]
                self.simpanan.catat_rtt(self.detik(), entri["ms"])
            else:
                self.rtt_gagal += 1

        elif jenis == "hb":
            self.klien = entri["klien"]
            self.rssi_uplink = entri["rssi"]

    def tutup_detik(self, detik: float) -> None:
        """Rekam satu titik waktu untuk grafik."""
        if detik - self.detik_terakhir < 1.0:
            return
        self.detik_terakhir = detik
        naik = sum(p["naik_bps"] for p in self.perangkat_tabel.values()) / 1000
        turun = sum(p["turun_bps"] for p in self.perangkat_tabel.values()) / 1000
        rtt = self.rtt[-1] if self.rtt else None
        self.histori = (self.histori + [{"t": detik, "naik": round(naik, 1),
                                         "turun": round(turun, 1), "rtt": rtt}])[-180:]

    def keadaan(self) -> dict:
        detik = self.detik()
        perangkat = []
        for p in self.perangkat_tabel.values():
            total_bingkai = p["bingkai_naik"] + p["bingkai_turun"]
            perangkat.append({
                "mac": p["mac"], "ip": p["ip"], "rssi": p["rssi"],
                "naik_kbps": round(p["naik_bps"] / 1000, 1),
                "turun_kbps": round(p["turun_bps"] / 1000, 1),
                "bingkai": total_bingkai,
                "ulang": p["bingkai_ulang"],
                "ulang_persen": round(100 * p["bingkai_ulang"] / total_bingkai, 2) if total_bingkai else 0.0,
                "dns": p["dns"],
            })
        perangkat.sort(key=lambda d: d["turun_kbps"] + d["naik_kbps"], reverse=True)
        rtt_kini = self.rtt[-1] if self.rtt else 0
        return {
            "mode": self.mode,
            "detik": detik,
            "klien": self.klien,
            "rssi_uplink": self.rssi_uplink,
            "rtt": {
                "sekarang": rtt_kini,
                "rata2": round(sum(self.rtt) / len(self.rtt), 1) if self.rtt else 0,
                "min": min(self.rtt) if self.rtt else 0,
                "maks": max(self.rtt) if self.rtt else 0,
                "gagal": self.rtt_gagal,
            },
            "perangkat": perangkat,
            "histori": self.histori,
            "sesi": self.simpanan.sesi,
            "mulai": self.simpanan.mulai.isoformat(timespec="seconds"),
        }


# ------------------------------------------------------------------ sumber --

class PortLepas(RuntimeError):
    """Port serial hilang di tengah sesi (kabel dicabut / papan restart)."""



def baca_port(port: str):
    """Buka port serial tanpa pustaka luar; hasilkan baris satu per satu."""
    fd = os.open(port, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0                                        # iflag
    attrs[1] = 0                                        # oflag
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0                                        # lflag
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    sisa = b""
    kosong = 0
    try:
        while True:
            siap, _, _ = select.select([fd], [], [], 1.0)
            if not siap:
                continue
            try:
                data = os.read(fd, 4096)
            except OSError:
                # kabel dicabut atau papan restart: port hilang
                raise PortLepas(port)
            if not data:
                # ujung lain menutup: di macOS ini EOF, bukan OSError
                kosong += 1
                if kosong >= 20:
                    raise PortLepas(port)
                time.sleep(0.05)
                continue
            kosong = 0
            sisa += data
            while b"\n" in sisa:
                baris, sisa = sisa.split(b"\n", 1)
                yield baris.decode("utf-8", "replace").strip()
    finally:
        os.close(fd)


def aliran_simulasi():
    """Angka tiruan: jelas bukan hasil pengukuran, dipakai untuk menguji tampilan."""
    perangkat = [
        {"mac": "3c:5a:b4:11:22:33", "ip": "192.168.4.2", "rssi": -48},
        {"mac": "8c:aa:b5:44:55:66", "ip": "192.168.4.3", "rssi": -61},
        {"mac": "e4:5f:01:77:88:99", "ip": "192.168.4.4", "rssi": -70},
        {"mac": "a0:b7:65:aa:bb:cc", "ip": "192.168.4.5", "rssi": -76},
    ]
    kumulatif = [{"naik": 0, "turun": 0, "bn": 0, "bt": 0, "bu": 0} for _ in perangkat]
    contoh_dns = ["tiktokcdn.com", "googlevideo.com", "i.instagram.com", "wa.me",
                  "cdn.whatsapp.net", "github.com", "detik.com", "spotify.com"]
    aktif = 1
    mulai = time.monotonic()
    yield "# simulasi: angka tiruan, bukan hasil pengukuran"
    while True:
        detik = int(time.monotonic() - mulai)
        if detik % 20 == 0:
            aktif = min(1 + detik // 20, len(perangkat))
        for i, p in enumerate(perangkat[:aktif]):
            k = kumulatif[i]
            beban = random.uniform(0.4, 1.0) if i == 0 else random.uniform(0.05, 0.7)
            k["turun"] += int(random.gauss(180_000, 40_000) * beban)
            k["naik"] += int(random.gauss(30_000, 8_000) * beban)
            k["bt"] += int(random.gauss(160, 20) * beban)
            k["bn"] += int(random.gauss(110, 15) * beban)
            k["bu"] += int(abs(random.gauss(2, 3)) * (1 + aktif / 3))
            yield f"tr,{p['mac']},{p['ip']},{k['naik']},{k['turun']},{k['bn']},{k['bt']},{k['bu']}"
            yield f"st,{p['mac']},{p['ip']},{p['rssi']}"
            if random.random() < 0.25:
                yield f"dns,{p['mac']},{p['ip']},{random.choice(contoh_dns)}"
        yield f"hb,{detik*1000},{aktif},-52,280000"
        yield f"rtt,{int(random.gauss(35 + aktif * 12, 6))}"
        time.sleep(1.0)


# ------------------------------------------------------------------- HTTP ---

def buat_http(pengumpul: Pengumpul, port: int, simpanan: Simpanan) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # jangan banjiri terminal
            pass

        def kirim(self, kode: int, tipe: str, isi: bytes) -> None:
            self.send_response(kode)
            self.send_header("Content-Type", tipe)
            self.send_header("Content-Length", str(len(isi)))
            self.end_headers()
            self.wfile.write(isi)

        def do_GET(self):
            if self.path.startswith("/api/state"):
                isi = json.dumps(pengumpul.keadaan(), ensure_ascii=False).encode()
                return self.kirim(200, "application/json; charset=utf-8", isi)
            if self.path.startswith("/api/ekspor.csv"):
                baris = ["t,mac,ip,naik_bps,turun_bps,bingkai_naik,bingkai_turun,bingkai_ulang"]
                # koneksi sendiri: sqlite3 hanya boleh dipakai di thread pembuatnya
                baca = sqlite3.connect(str(simpanan.path))
                try:
                    for r in baca.execute(
                            "SELECT t,mac,ip,naik_bps,turun_bps,bingkai_naik,bingkai_turun,bingkai_ulang"
                            " FROM trafik WHERE sesi=? ORDER BY t", (simpanan.sesi,)):
                        baris.append(",".join(str(x) for x in r))
                finally:
                    baca.close()
                return self.kirim(200, "text/csv; charset=utf-8",
                                  ("\n".join(baris) + "\n").encode())
            if self.path in ("/", "/index.html"):
                if DASHBOARD.exists():
                    return self.kirim(200, "text/html; charset=utf-8", DASHBOARD.read_bytes())
                return self.kirim(404, "text/plain", b"dashboard tidak ditemukan")
            self.kirim(404, "text/plain", b"tidak ada")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno == 48:
            print(f"port {port} sudah dipakai program lain — tutup dulu, atau pakai --http-port {port + 1}")
            raise SystemExit(2)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# -------------------------------------------------------------------- uji ---

def uji_mandiri() -> int:
    """Cek pengurai + hitung laju + basis data memakai pty (tanpa papan)."""
    import tempfile

    masukan = [
        "# esp32-gateway siap",
        "ev,connect,3c:5a:b4:11:22:33",
        "tr,3c:5a:b4:11:22:33,192.168.4.2,1000,9000,10,12,1",
        "st,3c:5a:b4:11:22:33,192.168.4.2,-48",
        "dns,3c:5a:b4:11:22:33,192.168.4.2,i.instagram.com",
        "rtt,31",
        "hb,1000,1,-52,280000",
    ]
    for b in masukan:
        assert urai(b) is not None or b.startswith("#"), f"gagal urai: {b}"
    assert urai("tr,rusak") is None, "baris cacat harus diabaikan"
    assert urai("dns,aa:bb,1.2.3.4,contoh.com")["nama"] == "contoh.com"

    with tempfile.TemporaryDirectory() as tmp:
        simpanan = Simpanan(Path(tmp) / "uji.db", "uji", "uji")
        pengumpul = Pengumpul(simpanan)
        for b in masukan:
            e = urai(b)
            if e:
                pengumpul.terima(e)
        time.sleep(0.3)
        pengumpul.terima(urai("tr,3c:5a:b4:11:22:33,192.168.4.2,6000,49000,60,62,4"))
        simpanan.kuras()
        jml = simpanan.db.execute("SELECT COUNT(*) FROM trafik").fetchone()[0]
        assert jml >= 1, "trafik tidak tersimpan"
        dns = simpanan.db.execute("SELECT nama FROM dns").fetchone()[0]
        assert dns == "i.instagram.com", f"dns salah: {dns}"
        k = pengumpul.keadaan()
        assert k["perangkat"][0]["ip"] == "192.168.4.2"
        assert k["perangkat"][0]["naik_kbps"] > 0, "laju naik harus positif"
        assert k["rtt"]["sekarang"] == 31
    print("uji: lulus")
    return 0


# ------------------------------------------------------------------ utama ---

def utama() -> int:
    p = argparse.ArgumentParser(description="Penerima catatan ESP32 + dashboard")
    p.add_argument("--port", help="port serial, mis. /dev/cu.usbserial-1130")
    p.add_argument("--sim", action="store_true", help="pakai angka tiruan (bukan pengukuran)")
    p.add_argument("--sesi", default=None, help="nama sesi, mis. S1")
    p.add_argument("--durasi", type=float, default=0, help="berhenti setelah N detik (0 = sampai Ctrl+C)")
    p.add_argument("--db", default=str(AKAR / "data" / "qos.db"))
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("--tanpa-http", action="store_true")
    p.add_argument("--uji", action="store_true", help="jalankan pemeriksaan mandiri lalu keluar")
    a = p.parse_args()

    if a.uji:
        return uji_mandiri()
    if not a.port and not a.sim:
        p.error("pilih --port <serial> atau --sim")

    mode = "sim" if a.sim else "serial"
    nama_sesi = a.sesi or datetime.now().strftime("%Y%m%d-%H%M%S")
    simpanan = Simpanan(Path(a.db), nama_sesi, mode)
    pengumpul = Pengumpul(simpanan)
    pengumpul.mode = mode

    if not a.tanpa_http:
        buat_http(pengumpul, a.http_port, simpanan)
        print(f"dashboard: http://127.0.0.1:{a.http_port}   (Ctrl+C untuk berhenti)")
    if mode == "sim":
        print("mode simulasi: angka tiruan, jangan dipakai di laporan")

    sumber = aliran_simulasi() if a.sim else baca_port(a.port)
    mulai = time.monotonic()
    terakhir_kuras = mulai
    kode = 0
    try:
        for baris in sumber:
            entri = urai(baris)
            if entri:
                pengumpul.terima(entri)
                pengumpul.tutup_detik(pengumpul.detik())
            if time.monotonic() - terakhir_kuras > 5:
                simpanan.kuras()
                terakhir_kuras = time.monotonic()
            if a.durasi and time.monotonic() - mulai >= a.durasi:
                break
    except PortLepas as e:
        print(f"\nport {e} lepas — kabel dicabut atau papan restart.", file=sys.stderr)
        print("sambung lagi lalu jalankan ulang; riwayat sesi sudah tersimpan.", file=sys.stderr)
        kode = 2
    except KeyboardInterrupt:
        print("\nberhenti")
    finally:
        simpanan.kuras()
        k = pengumpul.keadaan()
        print(f"sesi {k['sesi']} ({mode}) — {len(k['perangkat'])} perangkat, "
              f"{len(k['histori'])} titik grafik, rtt rata-rata {k['rtt']['rata2']} ms")
        print(f"tersimpan: {a.db}")
    return kode


if __name__ == "__main__":
    sys.exit(utama())
