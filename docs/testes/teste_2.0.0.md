# SOI 2.0.0: roteiro de teste (versão não publicada)

Firmware e interface 2.0.0 andam juntos: o protocolo USB mudou, então o firmware 1.0.0 não funciona com esta interface (e vice-versa).

## 1. Gravar o firmware

- PlatformIO: abra a pasta `firmware/` e faça Upload. Se o `pio.exe` for bloqueado pelo Windows, use
  `%USERPROFILE%\.platformio\penv\Scripts\python.exe -m platformio run -t upload` dentro de `firmware/`.
  Na primeira vez o PlatformIO baixa o `framework-stm32cubef4`.
- Ou grave `binarios/soi_firmware_v2.0.0.bin` no endereço **0x08000000** (STM32CubeProgrammer ou PlatformIO).
- O dispositivo aparece como "SOI OPT101/INMP441 (STM32F401)", VID 0483, PID 5740.
- Para voltar ao firmware antigo: `SOI StCube\backup\soi_flash_backup.bin` em 0x08000000.

## 2. Abrir a interface

`python interface/soi_controller.py` (mesmas dependências da 1.0.0). O título deve dizer **SOI Controller 2.0.0**.

## 3. O que conferir

1. Barra de status do OPT101: "12,5 kS/s (OSR 16)" e **nenhum** aviso vermelho de "Perdas USB" depois de alguns minutos.
2. Mude a **Sobreamostragem** de 16x para 1x, 4x e 64x: o osciloscópio e o lock-in devem continuar fluidos, e o R do lock-in deve ficar igual (a correção de amplitude acompanha o OSR).
3. Com OSR 1 (200 kS/s), olhe as bordas do laser no osciloscópio e no Valor Médio (passo de 5 µs).
4. **Teste de resolução**: laser em PWM 0 % (ou luz constante), Medir por 4 s. Veja até que N os pontos seguem a reta 1/√N e o histograma dos códigos. Salve o CSV/PNG. Repita com outro ganho do OPT101 se quiser comparar.
5. Aba INMP441: status com 48 kHz, lock-in e FFT funcionando; a fase do INMP441 deve ficar estável (não gira mais com o tempo).
6. Uma varredura curta em frequência no Modo Duplo, para conferir que nada mudou nos resultados.

Anote qualquer perda, travamento ou valor estranho. Nada desta versão está no GitHub.
