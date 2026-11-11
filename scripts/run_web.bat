@echo off
rem Keeps the review app running on 127.0.0.1:8765. Started at boot by the "tprm-web" scheduled task.
rem If the app exits, wait 10 seconds and start it again. Output goes to private\logs\web.log (git-ignored).
cd /d "%~dp0.."
:loop
echo [%date% %time%] starting >> "private\logs\web.log"
".venv\Scripts\python.exe" -m tprm_assurance.web >> "private\logs\web.log" 2>&1
echo [%date% %time%] exited with %errorlevel%, restarting in 10 s >> "private\logs\web.log"
timeout /t 10 /nobreak > nul
goto loop
