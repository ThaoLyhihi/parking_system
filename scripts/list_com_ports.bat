@echo off
rem Liet ke cac cong COM dang co tren may Windows nay (dau doc the qua serial,
rem va/hoac mach dieu khien barie qua COM) - chay file nay de biet "tinh hinh
rem thuc te" cua may truoc khi dien vao trang Cai dat (muc "Dau doc the" /
rem "Barie (COM/TCP)").

setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay "python". Cai Python 3.11+ tu https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist .venv (
    call .venv\Scripts\activate.bat
) else (
    echo (Chua co .venv - se dung Python he thong. Chay build_agent_exe.bat 1 lan
    echo  truoc de tao .venv day du thu vien, hoac de script nay tu cai pyserial.)
)

python -c "import serial" >nul 2>nul
if errorlevel 1 (
    echo Dang cai pyserial (chi can cho lan dau)...
    pip install --disable-pip-version-check -q pyserial
)

echo.
echo ================ Cong COM hien co tren may nay ================
python -c "import serial.tools.list_ports as p; ports = list(p.comports()); print('  (Khong tim thay cong COM nao - kiem tra da cam dau doc the/mach barie chua)') if not ports else [print(f'  {x.device}  -  {x.description}') for x in ports]"
echo =================================================================
echo.
echo Dung dung ten cong (vd COM7) o tren de dien vao trang Cai dat:
echo   - Muc "Dau doc the"      -> truong "Cong COM" (chi khi chon loai 'serial')
echo   - Muc "Barie (COM/TCP)"  -> trong JSON "barriers", phan "port"
echo.
pause
