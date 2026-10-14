@echo off
rem Dong goi scripts\windows_hardware_agent.py thanh 1 file .exe doc lap bang
rem PyInstaller, de mang sang may Windows khac chay thu KHONG can cai Python.
rem Chay file nay tren MAY WINDOWS (double-click hoac "build_agent_exe.bat" trong cmd),
rem KHONG chay trong Docker/Linux - PyInstaller dong goi theo dung OS dang build.

setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay "python". Cai Python 3.11+ tu https://www.python.org/downloads/
    echo       va nho tick "Add python.exe to PATH" luc cai, roi chay lai file nay.
    pause
    exit /b 1
)

if not exist .venv (
    echo Dang tao moi truong Python rieng (.venv)...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Dang cai thu vien can thiet (keyboard, pyserial, requests, PyYAML, pyinstaller)...
python -m pip install --disable-pip-version-check -q --upgrade pip
pip install --disable-pip-version-check -q -r requirements-windows-agent.txt pyinstaller
if errorlevel 1 (
    echo [LOI] Cai thu vien that bai - kiem tra lai ket noi Internet (chi can cho lan dau nay).
    pause
    exit /b 1
)

echo Dang dong goi file .exe (co the mat 1-2 phut)...
pyinstaller --onefile --name parking_hardware_agent --paths . --hidden-import keyboard._winkeyboard --clean --noconfirm scripts\windows_hardware_agent.py
if errorlevel 1 (
    echo [LOI] PyInstaller build khong thanh cong, xem log phia tren.
    pause
    exit /b 1
)

if not exist dist\config mkdir dist\config
copy /Y config\config.example.yaml dist\config\config.example.yaml >nul

echo.
echo ================================================================
echo  BUILD XONG: dist\parking_hardware_agent.exe
echo.
echo  Mang CA THU MUC "dist" (khong chi rieng file .exe) sang may can chay.
echo  Tren may do: copy dist\config\config.example.yaml thanh
echo  dist\config\config.yaml roi sua lai dung voi bai xe/barie/dau doc the thuc te
echo  (xem config.yaml muc "card_reader" va "barrier_hardware").
echo.
echo  Chay thu: mo cmd trong thu muc dist, go: parking_hardware_agent.exe
echo ================================================================
pause
