@echo off
setlocal
title Push SPT - Deski Taiza
color 0A

set SPT_DIR=c:\Users\ACER\Documents\spt_temp_clone
set FILES_DIR=c:\Users\ACER\Documents\wmc_2026_kelompok1_gerbang_qos_esp32-main\spt

echo ============================================================
echo   PUSH SPT - Deski Taiza (23210003)
echo   Uji Ketahanan Riwayat Saat Server Mati
echo ============================================================
echo.

echo [1/5] Clone repo SPT...
if exist "%SPT_DIR%" rmdir /s /q "%SPT_DIR%"
git clone https://github.com/KELOMPOK-1-MK3/spt_2026_kelompok1_load_balancer_terdistribusi.git "%SPT_DIR%"
if errorlevel 1 (
    echo Clone gagal! Cek koneksi internet.
    pause
    exit /b 1
)

echo [2/5] Copy file uji-ketahanan.py...
copy /Y "%FILES_DIR%\src\server\uji-ketahanan.py" "%SPT_DIR%\src\server\uji-ketahanan.py"

echo [3/5] Copy file hasil-uji-ketahanan.md...
copy /Y "%FILES_DIR%\docs\hasil-uji-ketahanan.md" "%SPT_DIR%\docs\hasil-uji-ketahanan.md"

echo [4/5] Configure git dan commit...
cd /d "%SPT_DIR%"
git config user.name "Deski Taiza"
git config user.email "taizadeski0@gmail.com"
git checkout -b deski/uji-ketahanan
git add src/server/uji-ketahanan.py docs/hasil-uji-ketahanan.md
git commit -m "uji-ketahanan: skrip uji ketahanan riwayat + hasil pengujian (issue #15)" -m "5 percobaan: Ctrl+C, kill-9, hapus db, 100 pesan kill cepat, salin saat jalan" -m "Tanggung jawab: Deski Taiza (23210003)"

echo [5/5] Push ke GitHub...
git push -u origin deski/uji-ketahanan

echo.
if %ERRORLEVEL% EQU 0 (
    echo PUSH BERHASIL!
    echo Cek: https://github.com/KELOMPOK-1-MK3/spt_2026_kelompok1_load_balancer_terdistribusi/tree/deski/uji-ketahanan
) else (
    echo PUSH GAGAL - login GitHub mungkin diperlukan
    echo Kalau diminta password, gunakan Personal Access Token
    echo Buat di: https://github.com/settings/tokens
    echo Centang: repo
)
echo.
echo Tekan sembarang tombol untuk menutup...
pause >nul
