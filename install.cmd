@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 -m installer
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw -m installer
  exit /b 0
)
where py >nul 2>nul
if %errorlevel%==0 (
  start "" py -3 -m installer
  exit /b 0
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "" python -m installer
  exit /b 0
)
echo Python 3.12+ is required but was not found.
echo Install it from https://www.python.org/downloads/ and retry.
exit /b 1
