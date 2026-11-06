"""Uji: kabel serial dicabut di tengah sesi tidak boleh meledak dengan traceback.

Jalankan: python3 src/penerima/uji-kabel-lepas.py
Butuh pty (macOS/Linux). Papan fisik tidak diperlukan.
"""
import os, pty, subprocess, sys, time
from pathlib import Path

AKAR = Path(__file__).resolve().parents[2]
PENERIMA = AKAR / "src" / "penerima" / "penerima.py"

master, slave = pty.openpty()
nama = os.ttyname(slave)

proc = subprocess.Popen(
    [sys.executable, str(PENERIMA), "--port", nama, "--tanpa-http",
     "--db", "/tmp/uji-lepas.db", "--sesi", "lepas"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=AKAR)

os.write(master, b"hb,1000,1,-50,200000\n")
time.sleep(1.5)
os.close(master)          # pura-pura kabel dicabut
time.sleep(2.0)

out, err = proc.communicate(timeout=20)
print("kode   :", proc.returncode)
print("keluaran:", out.strip().replace("\n", " | "))
print("galat  :", err.strip().replace("\n", " | "))

assert proc.returncode == 2, "harus keluar dengan kode 2"
assert "lepas" in err, "pesan port lepas tidak muncul"
assert "Traceback" not in err, "masih ada traceback"
print("lulus: kabel lepas ditangani tanpa traceback")
