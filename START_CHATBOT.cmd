@echo off
setlocal
title Sunoida Guide Assistant
cd /d "%~dp0"
if not exist "backend\launch_chatbot.py" (
  echo Extract the full startup package into this project folder first.
  pause
  exit /b 1
)
set "CHATBOT_PYTHON=backend\.venv\Scripts\python.exe"
if not exist "%CHATBOT_PYTHON%" goto setup
"%CHATBOT_PYTHON%" -c "import sys; from importlib.util import find_spec; sys.exit(not all(find_spec(name) for name in ('fastapi', 'uvicorn', 'chromadb', 'ollama', 'langchain_ollama', 'pydantic_settings', 'pypdfium2')))" >nul 2>&1
if not errorlevel 1 goto launch

:setup
if not exist "SETUP_CHATBOT.cmd" (
  echo SETUP_CHATBOT.cmd is missing. Keep both launchers in the chatbot folder.
  pause
  exit /b 1
)
echo Setting up the chatbot's Python environment. This can take a few minutes.
call "SETUP_CHATBOT.cmd" --from-start
if errorlevel 1 (
  echo The chatbot setup could not finish. Read the message above.
  pause
  exit /b 1
)
title Sunoida Guide Assistant

:launch
"%CHATBOT_PYTHON%" -u "backend\launch_chatbot.py" %*
set "CHATBOT_EXIT=%errorlevel%"
if not "%CHATBOT_EXIT%"=="0" (
  echo.
  echo The chatbot could not start. Read the message above.
  pause
)
exit /b %CHATBOT_EXIT%
