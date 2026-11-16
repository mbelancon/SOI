@echo off
REM Campanha noturna de deriva (Sinal x t pelo modo sem janela). Feche a interface antes.
REM Uso: campanha_deriva.bat [nome_da_amostra]    (padrao: Deriva)
REM Cada bloco: 10 min com PWM 0 (laser parado: esfria e mede o fundo) + 20 min com o laser modulando.
REM Duracao total estimada: ~5 h. Tudo vai para interface\Medidas e para interface\logs\soi.log.
REM Ctrl+C interrompe a medida atual (salva o que ja foi medido); responda S para parar a campanha.
cd /d "%~dp0"
set PY=%USERPROFILE%\miniconda3\python.exe
if not exist "%PY%" set PY=python
set AM=%1
if "%AM%"=="" set AM=Deriva
set RUN="%PY%" interface\soi_controller.py --sinal-t --tau 1 --dt 5 --desligar --amostra
echo Inicio: %date% %time%
for %%B in ("10 100 20" "10 50 20" "10 25 20" "5 100 20" "30 100 20" "100 100 20" "10 100 60") do call :bloco %%~B
echo Varredura final (tau adaptativo, precisao 2 %%):
"%PY%" interface\soi_controller.py --varredura --amostra %AM%_final --tau 4 --precisao 2 --desligar
echo Fim: %date% %time%
pause
exit /b

:bloco
echo.
echo === %1 Hz, PWM %2 %%, %3 min (antes: 10 min com PWM 0) ===
%RUN% %AM%_f%1_pwm0_fundo --f %1 --pwm 0 --duracao 10
%RUN% %AM%_f%1_pwm%2 --f %1 --pwm %2 --duracao %3
exit /b
