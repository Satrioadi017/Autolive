@echo off
REM Setup script untuk Windows 10/11
REM Membuat virtualenv, install dependencies, dan menyiapkan .env

setlocal

cd /d "%~dp0"

echo [autolive] === Setup Autolive Bot (Windows) ===

where python >NUL 2>&1
if errorlevel 1 (
  echo [autolive] Python tidak ditemukan di PATH. Install Python 3.10+ dari https://python.org dulu.
  exit /b 1
)

for /f "delims=" %%i in ('python -c "import sys;print(sys.version_info>=(3,10))"') do set PY_OK=%%i
if /I not "%PY_OK%"=="True" (
  echo [autolive] Versi Python kurang dari 3.10. Silakan upgrade.
  exit /b 1
)

where ffmpeg >NUL 2>&1
if errorlevel 1 (
  echo [autolive] FFmpeg tidak ditemukan. Download dari https://www.gyan.dev/ffmpeg/builds/ lalu tambahkan ke PATH.
  echo [autolive] Tip: gunakan winget install Gyan.FFmpeg
)

if not exist ".venv" (
  echo [autolive] Membuat virtualenv di .venv ...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [autolive] Gagal mengaktifkan virtualenv.
  exit /b 1
)

echo [autolive] Upgrading pip...
python -m pip install --upgrade pip

echo [autolive] Install dependencies dari requirements.txt ...
pip install -r requirements.txt

if not exist ".env" (
  echo [autolive] Menyalin .env.example -^> .env ...
  copy /Y .env.example .env >NUL
  echo [autolive] Edit .env dan isi YOUTUBE_STREAM_KEY + ANTHROPIC_API_KEY sebelum menjalankan bot.
)

if not exist "logs" mkdir logs
if not exist "assets\backgrounds" mkdir assets\backgrounds
if not exist "assets\music" mkdir assets\music
if not exist "assets\fonts" mkdir assets\fonts
if not exist "assets\overlays" mkdir assets\overlays

echo [autolive] Setup selesai. Jalankan:
echo   .venv\Scripts\activate
echo   python main.py --test-content        REM preview konten
echo   python main.py --dry-run             REM uji pipeline tanpa streaming
echo   python main.py                       REM mulai streaming 24/7

endlocal
