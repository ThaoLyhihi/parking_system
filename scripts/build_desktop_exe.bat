@echo off
rem Dong goi ung dung desktop all-in-one (desktop\main.py) thanh thu muc dist\ParkingAI\ParkingAI.exe.
rem Chay tren MAY WINDOWS (PyInstaller khong build cheo OS). Khong co may Windows: dung GitHub Actions
rem (.github\workflows\build-desktop.yml).
setlocal
cd /d "%~dp0.."
where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay "python". Cai Python 3.11+ va tick "Add python.exe to PATH".
    pause
    exit /b 1
)
if not exist .venv-desktop python -m venv .venv-desktop
call .venv-desktop\Scripts\activate.bat
python -m pip install --disable-pip-version-check -q --upgrade pip
pip install --disable-pip-version-check -q -r requirements-desktop.txt
if errorlevel 1 (
    echo [LOI] Cai thu vien that bai - can Internet (chi lan dau).
    pause
    exit /b 1
)
pyinstaller parking_desktop.spec --noconfirm --clean
if errorlevel 1 (
    echo [LOI] Build that bai, xem log phia tren.
    pause
    exit /b 1
)
echo.
echo BUILD XONG: dist\ParkingAI\ParkingAI.exe  (mang CA THU MUC dist\ParkingAI sang may khac, khong can cai Python)
pause
