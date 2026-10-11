@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem Режим виконання за розкладом: планувальник викликає "bat run"
if /i "%~1"=="run" (
    start "" /min python gui_app.py
    exit /b 0
)

rem Реєстрація завдання: щоденний автозапуск о 10:00
schtasks /create /tn "CleanArch Daily 10AM" /tr "\"%~dp0schedule_daily_10am.bat\" run" /sc daily /st 10:00 /f

if errorlevel 1 (
    echo Помилка: не вдалося створити завдання планувальника.
) else (
    echo Готово: щоденний автозапуск о 10:00 заплановано.
    echo.
    echo Перевірка:  schtasks /query /tn "CleanArch Daily 10AM"
    echo Видалення:  schtasks /delete /tn "CleanArch Daily 10AM" /f
)
if "%~1"=="" pause
