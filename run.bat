@echo off
echo ============================================================
echo    XSMN LOTTERY LIMIT MANAGEMENT SYSTEM
echo    He Thong Quan Ly Han Muc Lo - Mien Nam
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python chua duoc cai dat!
    echo Vui long cai dat Python tu https://python.org
    pause
    exit /b 1
)

REM Install dependencies
echo [1/3] Cai dat thu vien...
cd /d "%~dp0backend"
pip install -r requirements.txt --quiet

echo.
echo [2/3] Khoi tao database...
python -c "from database import init_db; init_db()"

echo.
echo [3/3] Khoi dong server...
echo.
echo ============================================================
echo    Dashboard: http://localhost:8000
echo    API Docs:  http://localhost:8000/docs
echo ============================================================
echo    Nhan Ctrl+C de dung server
echo ============================================================
echo.

REM Open browser after 2 seconds
start /b cmd /c "timeout /t 2 >nul && start http://localhost:8000"

REM Start server
python main.py
