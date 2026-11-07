#!/usr/bin/env python3
"""Uji ketahanan riwayat saat server mati.

Menjalankan 5 percobaan untuk membuktikan klaim "riwayat tetap ada
walau server mati":

  1. Ctrl+C server, nyalakan lagi    — jumlah pesan sesudah
  2. kill -9 server, nyalakan lagi   — jumlah pesan sesudah
  3. Hapus chat.db, nyalakan lagi     — apa yang terjadi
  4. Tulis 100 pesan, kill -9 cepat   — berapa yang hilang
  5. Salin chat.db saat server jalan  — apakah salinannya utuh

Pakai port uji 5099 (socket) / 8199 (web) supaya tidak ganggu server lain.
Hanya modul bawaan Python — tidak ada dependensi.

Jalankan:
    python3 uji-ketahanan.py

Tanggung jawab: Deski Taiza (23210003)
"""
from __future__ import annotations

import json
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ----------------------------------------------------------------- pengaturan
PORT_SOCKET = 5099
PORT_WEB = 8199
SERVER_PY = Path(__file__).resolve().parent / "server.py"
JEDA_MULAI = 2.0       # detik: tunggu server siap (maks)
JEDA_PESAN = 0.02      # detik: jeda antar pesan (percobaan 1-3, 5)

# -------------------------------------------------------- utilitas pengujian

def mulai_server(db_path: str) -> subprocess.Popen:
    """Mulai server sebagai subprocess dengan port dan DB uji."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY),
         "--port", str(PORT_SOCKET),
         "--web", str(PORT_WEB),
         "--db", str(db_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Windows: grup proses baru supaya bisa kirim sinyal terpisah
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                       if sys.platform == "win32" else 0),
    )
    # Tunggu sampai port socket siap
    for _ in range(20):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", PORT_SOCKET))
            s.close()
            return proc
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.25)
    raise RuntimeError("server tidak siap dalam 5 detik")


def hentikan_server(proc: subprocess.Popen, paksa: bool = False) -> None:
    """Hentikan server.

    paksa=False -> Ctrl+C (SIGINT / graceful shutdown)
    paksa=True  -> kill -9 (SIGKILL / force kill)
    """
    if paksa:
        proc.kill()
    else:
        if sys.platform == "win32":
            # Windows: kirim CTRL_BREAK_EVENT ke grup proses
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except (ValueError, OSError):
                proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def tunggu_port_bebas() -> None:
    """Tunggu sampai port socket bebas (server lama benar-benar mati)."""
    for _ in range(20):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", PORT_SOCKET))
            s.close()
            time.sleep(0.25)
        except (ConnectionRefusedError, socket.timeout, OSError):
            return
    raise RuntimeError("port masih sibuk setelah 5 detik")


def buat_klien() -> socket.socket:
    """Buat klien TCP, sambung ke server, daftar."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(("127.0.0.1", PORT_SOCKET))
    # Daftar
    s.sendall((json.dumps({"tipe": "daftar", "nama": "uji", "sistem": "test"})
               + "\n").encode())
    time.sleep(0.3)
    try:
        s.recv(8192)  # terima pesan selamat
    except socket.timeout:
        pass
    return s


def kirim_pesan(jumlah: int, jeda: float = JEDA_PESAN) -> int:
    """Kirim pesan ke server melalui klien. Kembalikan jumlah yang terkirim."""
    s = buat_klien()
    terkirim = 0
    for i in range(jumlah):
        msg = json.dumps({"tipe": "pesan", "ke": "semua",
                          "isi": f"uji-{i}"}) + "\n"
        try:
            s.sendall(msg.encode())
            terkirim += 1
            if jeda > 0:
                time.sleep(jeda)
        except OSError:
            break
    s.close()
    return terkirim


def hitung_pesan(db_path: str) -> int:
    """Hitung jumlah baris di tabel pesan. -1 = tidak ada, -2 = rusak."""
    if not Path(db_path).exists():
        return -1
    try:
        with sqlite3.connect(db_path) as db:
            return db.execute("SELECT COUNT(*) FROM pesan").fetchone()[0]
    except sqlite3.DatabaseError:
        return -2


def cek_integritas(db_path: str) -> str:
    """Jalankan PRAGMA integrity_check. Kembalikan 'ok' atau pesan error."""
    if not Path(db_path).exists():
        return "tidak ada berkas"
    try:
        with sqlite3.connect(db_path) as db:
            return db.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as e:
        return f"rusak: {e}"


# -------------------------------------------------------- percobaan uji

def percobaan_1_ctrl_c(tmp: Path) -> dict:
    """1. Hentikan server dengan Ctrl+C, nyalakan lagi."""
    db = str(tmp / "uji1.db")
    proc = mulai_server(db)
    kirim_pesan(10)
    time.sleep(0.5)
    sebelum = hitung_pesan(db)

    hentikan_server(proc, paksa=False)  # Ctrl+C
    tunggu_port_bebas()

    proc = mulai_server(db)
    time.sleep(1)
    sesudah = hitung_pesan(db)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    return {
        "nomor": 1,
        "perlakuan": "Ctrl+C, nyalakan lagi",
        "sebelum": sebelum,
        "sesudah": sesudah,
        "hilang": sebelum - sesudah if sesudah >= 0 else "?",
        "integritas": cek_integritas(db),
    }


def percobaan_2_kill9(tmp: Path) -> dict:
    """2. kill -9 proses server (mati paksa), nyalakan lagi."""
    db = str(tmp / "uji2.db")
    proc = mulai_server(db)
    kirim_pesan(10)
    time.sleep(0.5)
    sebelum = hitung_pesan(db)

    hentikan_server(proc, paksa=True)  # kill -9
    tunggu_port_bebas()

    proc = mulai_server(db)
    time.sleep(1)
    sesudah = hitung_pesan(db)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    return {
        "nomor": 2,
        "perlakuan": "kill -9, nyalakan lagi",
        "sebelum": sebelum,
        "sesudah": sesudah,
        "hilang": sebelum - sesudah if sesudah >= 0 else "?",
        "integritas": cek_integritas(db),
    }


def percobaan_3_hapus_db(tmp: Path) -> dict:
    """3. Hapus berkas chat.db, nyalakan lagi."""
    db = str(tmp / "uji3.db")
    proc = mulai_server(db)
    kirim_pesan(10)
    time.sleep(0.5)
    sebelum = hitung_pesan(db)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    # Hapus database beserta file journal/WAL kalau ada
    Path(db).unlink(missing_ok=True)
    for suffix in ["-journal", "-wal", "-shm"]:
        Path(db + suffix).unlink(missing_ok=True)

    proc = mulai_server(db)
    time.sleep(1)
    sesudah = hitung_pesan(db)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    return {
        "nomor": 3,
        "perlakuan": "hapus chat.db, nyalakan lagi",
        "sebelum": sebelum,
        "sesudah": sesudah,
        "hilang": "semua (riwayat hilang)",
        "integritas": cek_integritas(db),
    }


def percobaan_4_kill_cepat(tmp: Path) -> dict:
    """4. Tulis 100 pesan, lalu kill -9 dalam 1 detik."""
    db = str(tmp / "uji4.db")
    proc = mulai_server(db)

    # Daftar dulu
    s = buat_klien()

    # Kirim 100 pesan secepat mungkin (tanpa jeda)
    terkirim = 0
    for i in range(100):
        msg = json.dumps({"tipe": "pesan", "ke": "semua",
                          "isi": f"uji4-{i}"}) + "\n"
        try:
            s.sendall(msg.encode())
            terkirim += 1
        except OSError:
            break
    s.close()

    # Kill segera (dalam 1 detik setelah kirim)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    tersimpan = hitung_pesan(db)

    # Nyalakan lagi untuk konfirmasi integritas
    proc = mulai_server(db)
    time.sleep(1)
    sesudah = hitung_pesan(db)
    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    return {
        "nomor": 4,
        "perlakuan": "100 pesan, kill -9 cepat",
        "sebelum": terkirim,
        "sesudah": tersimpan,
        "hilang": terkirim - tersimpan,
        "integritas": cek_integritas(db),
    }


def percobaan_5_salin_saat_jalan(tmp: Path) -> dict:
    """5. Salin chat.db ke tempat lain selagi server jalan."""
    db = str(tmp / "uji5.db")
    salinan = str(tmp / "uji5_salinan.db")

    proc = mulai_server(db)
    kirim_pesan(10)
    time.sleep(0.5)

    # Salin saat server masih jalan
    shutil.copy2(db, salinan)

    sebelum = hitung_pesan(db)
    salinan_pesan = hitung_pesan(salinan)
    salinan_integritas = cek_integritas(salinan)

    hentikan_server(proc, paksa=True)
    tunggu_port_bebas()

    return {
        "nomor": 5,
        "perlakuan": "salin chat.db saat server jalan",
        "sebelum": sebelum,
        "sesudah": salinan_pesan,
        "hilang": "utuh" if salinan_integritas == "ok" else "salinan tidak utuh",
        "integritas": salinan_integritas,
    }


# --------------------------------------------------------------- cetak hasil

def cetak_tabel(hasil: list[dict]) -> None:
    """Cetak tabel ringkasan hasil."""
    print()
    print("=" * 76)
    print("  HASIL UJI KETAHANAN RIWAYAT SAAT SERVER MATI")
    print("  Tanggung jawab: Deski Taiza (23210003)")
    print("=" * 76)
    print()
    fmt = "  {:<4} {:<32} {:<10} {:<10} {:<15}"
    print(fmt.format("No", "Perlakuan", "Sebelum", "Sesudah", "Hilang"))
    print(fmt.format("--", "--------", "-------", "-------", "------"))
    for h in hasil:
        print(fmt.format(h["nomor"], h["perlakuan"],
                         str(h["sebelum"]), str(h["sesudah"]), str(h["hilang"])))
    print()
    print("  Integritas database setelah tiap percobaan:")
    for h in hasil:
        print(f"    {h['nomor']}. {h['perlakuan']}: {h['integritas']}")
    print()
    print("=" * 76)
    print()
    print("  Catatan:")
    print("    - Setiap pesan disimpan sebagai transaksi terpisah yang")
    print("      langsung di-commit. Pesan yang sudah di-commit aman.")
    print("    - kill -9 tidak merusak database karena SQLite memakai")
    print("      rollback journal untuk memulihkan transaksi yang belum selesai.")
    print("    - Hapus chat.db = riwayat hilang selamanya (server buat ulang).")
    print("    - Salin saat server jalan: biasanya utuh, tapi TIDAK dijamin")
    print("      jika sedang menulis saat disalin.")


# ------------------------------------------------------------------- utama

def utama() -> int:
    if not SERVER_PY.exists():
        print(f"ERROR: server.py tidak ditemukan di {SERVER_PY}")
        print("Jalankan skrip ini dari dalam folder src/server/")
        return 1

    with tempfile.TemporaryDirectory(prefix="uji-ketahanan-") as tmp:
        tmp = Path(tmp)
        print(f"  Database uji di: {tmp}")
        print(f"  Port socket: {PORT_SOCKET}, Port web: {PORT_WEB}")
        print()

        hasil: list[dict] = []

        print("  [1/5] Ctrl+C, nyalakan lagi ...")
        hasil.append(percobaan_1_ctrl_c(tmp))

        print("  [2/5] kill -9, nyalakan lagi ...")
        hasil.append(percobaan_2_kill9(tmp))

        print("  [3/5] Hapus chat.db, nyalakan lagi ...")
        hasil.append(percobaan_3_hapus_db(tmp))

        print("  [4/5] 100 pesan, kill -9 cepat ...")
        hasil.append(percobaan_4_kill_cepat(tmp))

        print("  [5/5] Salin chat.db saat server jalan ...")
        hasil.append(percobaan_5_salin_saat_jalan(tmp))

        cetak_tabel(hasil)

    return 0


if __name__ == "__main__":
    sys.exit(utama())
