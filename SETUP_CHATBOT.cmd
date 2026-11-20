@echo off
setlocal
title Sunoida Guide Assistant - Setup
cd /d "%~dp0"
if not exist "requirements.txt" (
  echo Keep this file in the project folder beside requirements.txt.
  goto failed
)
if not exist ".env.example" (
  echo The configuration template is missing. Extract the complete project first.
  goto failed
)
set "CHATBOT_PYTHON=backend\.venv\Scripts\python.exe"
if not exist "%CHATBOT_PYTHON%" goto create_environment
"%CHATBOT_PYTHON%" -m pip --version >nul 2>&1
if not errorlevel 1 goto install_packages

:create_environment
py -3.14 -V >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.14 with the Windows Python launcher, then run setup again.
  goto failed
)
py -3.14 -m venv "backend\.venv"
if errorlevel 1 (
  echo The Python environment could not be created in backend\.venv.
  goto failed
)

:install_packages
set "CHATBOT_REQUIREMENTS=requirements.txt"
if exist "requirements.lock.txt" set "CHATBOT_REQUIREMENTS=requirements.lock.txt"
"%CHATBOT_PYTHON%" -m pip install --disable-pip-version-check -r "%CHATBOT_REQUIREMENTS%"
if errorlevel 1 (
  echo Package installation failed. Read the message above.
  goto failed
)
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  if errorlevel 1 (
    echo Could not create the local settings file .env.
    goto failed
  )
)
if /i "%~1"=="--from-start" exit /b 0
echo.
echo Python setup is complete. Your existing .env is preserved.
echo Keep your PDFs and Chroma database in backend. Then run START_CHATBOT.cmd.
pause
exit /b 0

:failed
if /i not "%~1"=="--from-start" pause
exit /b 1
