@echo off
REM Varredura em frequencia do Modo Duplo sem janela (feche a interface antes).
REM Ex.: varredura.bat --amostra Al --fmin 5 --fmax 2440 --n 35 --tau 4 --precisao 1
REM Ajuda: varredura.bat --help
cd /d "%~dp0"
set PY=%USERPROFILE%\miniconda3\python.exe
if not exist "%PY%" set PY=python
"%PY%" interface\soi_controller.py --varredura %*
