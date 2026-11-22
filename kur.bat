@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Ampul kurulumu

echo.
echo  === Ampul widget kurulumu ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo  Python bulunamadi. https://www.python.org/downloads/ adresinden kur,
  echo  kurulumda "Add python.exe to PATH" kutusunu isaretle ve bu dosyayi tekrar calistir.
  pause
  exit /b 1
)

echo  [1/3] Gerekli paketler yukleniyor...
%PY% -m pip install --quiet --upgrade pip
%PY% -m pip install --quiet --upgrade tinytuya tuya-device-sharing-sdk qrcode pyinstaller
if errorlevel 1 goto hata

echo  [2/3] Ampul.exe olusturuluyor (1-2 dakika surebilir)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name Ampul ^
  --icon ampul.ico --add-data "ampul.ico;." ^
  --collect-submodules tuya_sharing --collect-submodules tinytuya ^
  ampul_widget.py >build.log 2>&1
if errorlevel 1 (
  echo  Exe olusturulamadi, ayrintilar build.log dosyasinda.
  goto hata
)

echo  [3/3] Uygulama yerlestiriliyor ve kisayollar olusturuluyor...
set "HEDEF=%LOCALAPPDATA%\AmpulWidget"
if not exist "%HEDEF%" mkdir "%HEDEF%"
taskkill /im Ampul.exe /f >nul 2>nul
copy /y "dist\Ampul.exe" "%HEDEF%\Ampul.exe" >nul
if errorlevel 1 goto hata

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $s = $w.CreateShortcut((Join-Path $d 'Ampul.lnk'));" ^
  "  $s.TargetPath = '%HEDEF%\Ampul.exe'; $s.WorkingDirectory = '%HEDEF%';" ^
  "  $s.IconLocation = '%HEDEF%\Ampul.exe,0'; $s.Save() }"

rmdir /s /q build >nul 2>nul
del /q Ampul.spec >nul 2>nul

echo.
echo  Tamamlandi! Masaustundeki ve Baslat menusundeki "Ampul" kisayolundan acabilirsin.
echo.
start "" "%HEDEF%\Ampul.exe"
pause
exit /b 0

:hata
echo.
echo  Bir hata olustu. Yukaridaki mesaji (ve varsa build.log dosyasini) gonder.
pause
exit /b 1
