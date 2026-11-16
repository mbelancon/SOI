@echo off
REM Abre a interface SOI sem janela de terminal (pythonw do miniconda).
REM Mensagens e erros ficam em interface\logs\soi.log.
REM Primeira vez (instala as dependencias, com terminal): rodar_interface.bat instalar
REM Com terminal, para depurar: rodar_interface.bat terminal
cd /d "%~dp0"
set PY=%USERPROFILE%\miniconda3\python.exe
set PYW=%USERPROFILE%\miniconda3\pythonw.exe
if not exist "%PY%" set PY=python
if not exist "%PYW%" set PYW=pythonw
if /I "%1"=="instalar" (
  "%PY%" -m pip install -r requirements.txt
  pause
  exit /b
)
if /I "%1"=="terminal" (
  "%PY%" interface\soi_controller.py
  pause
  exit /b
)
start "" "%PYW%" interface\soi_controller.py
