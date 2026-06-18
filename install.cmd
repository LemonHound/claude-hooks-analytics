@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m installer
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  python -m installer
  goto :eof
)
echo Python 3.12+ is required but was not found.
echo Install it from https://www.python.org/downloads/ and retry.
exit /b 1
