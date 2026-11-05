# Histórico de versões

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/): MAIOR.MENOR.CORREÇÃO.

- **MAIOR:** mudança incompatível, por exemplo no protocolo serial entre firmware e interface.
- **MENOR:** função nova que não quebra o que já existia.
- **CORREÇÃO:** conserto de erro.

A interface e o firmware compartilham o mesmo número de versão.

## [Não publicado]

### Interface
- O passa-baixas dos lock-ins (OPT101, INMP441 e τ da integração longa do Modo Duplo) passa a ser escolhido pela constante de tempo τ, em vez do corte em Hz. As setas andam na sequência 1–3–10, de 1 ms a 100 s.
- Ao lado do τ aparecem o corte de −3 dB, a banda equivalente de ruído (ENBW) e a espera de 9τ.
- O τ automático ao mudar a frequência é arredondado para 0,3 s, 1 s ou 3 s.
- Os CSVs do Lock-In registram o τ no cabeçalho.
- As preferências salvas guardam o τ. O passa-baixas salvo pela versão 1.0.0 (em Hz) é ignorado uma vez.

## [1.0.0] - 2026-10-27

Primeira versão publicada.

### Interface (`interface/stm32_opt_inmmp_novo.py`)
- Lock-in em Python dos dois canais: OPT101 (com PLL em software) e INMP441.
- Aba OPT101: osciloscópio, Lock-In e Valor Médio (com ajuste de 1 ou 2 exponenciais), FFT do ADC com fit do pico, varreduras em frequência e em PWM.
- Aba INMP441: Lock-In, Ruído/SNR, FFT com fit do pico, varreduras em frequência e em PWM com correção pela calibração.
- Modo Duplo: os dois lock-ins no mesmo passo, sinal normalizado pelo OPT101, calibração do microfone com folha de alumínio, ajuste de modelos e abertura de varreduras salvas.
- Exportação padronizada em CSV/PNG com o nome da amostra e "Finalizar experimento" (ZIP da sessão).
- Detecção automática da porta, reconexão e modo simulado sem o STM32.

### Firmware (`firmware/`)
- STM32F401 Black Pill: PWM do laser de 5 kHz (0–100 %, passo de 0,1 %) e modulação em onda quadrada de 0,1 a 5000 Hz.
- ADC do OPT101 a 12,5 kS/s com 14 bits efetivos (sobreamostragem) e referência do laser por DMA.
- INMP441 por I2S a ≈32 kS/s, 24 bits, com marcador de início da modulação para a fase.
- Envio por USB CDC.

[1.0.0]: https://github.com/mbelancon/SOI/releases/tag/v1.0.0
