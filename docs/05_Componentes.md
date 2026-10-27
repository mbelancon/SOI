# Componentes do sistema de lock-in fotoacústico

## Microcontrolador

Um microcontrolador é um computador completo em um único circuito integrado. No mesmo chip ficam o processador, a memória de programa (flash), a memória de dados (RAM) e vários periféricos: conversores analógico-digitais (ADC), temporizadores, controladores de DMA e interfaces de comunicação (USB, I2S, SPI, UART). Um computador pessoal roda um sistema operacional de uso geral, sujeito a atrasos imprevisíveis. O microcontrolador executa um único programa dedicado, com temporização determinística na escala de nanossegundos. Por isso é adequado para gerar sinais de controle e adquirir sensores em instantes rigorosamente definidos. Neste sistema, o microcontrolador modula o laser, amostra os dois sensores em sincronia e envia os dados ao computador, que faz o processamento numérico (lock-in) e a visualização.

## STM32F401 "Black Pill"

A placa Black Pill usa o STM32F401CCU6, que tem um núcleo ARM Cortex-M4 de 84 MHz com unidade de ponto flutuante e instruções de DSP. A memória é de 256 KB de flash e 64 KB de RAM. A placa custa poucos dólares e é programada com ferramentas abertas (PlatformIO, framework Arduino). Para este projeto, os recursos decisivos são:

- **ADC de 12 bits de até 2,4 MS/s**, disparado por temporizador e lido por **DMA**. As amostras são coletadas sem intervenção da CPU e sem jitter. Com sobreamostragem (16 amostras somadas a 200 kHz), obtêm-se **14 bits efetivos a 12,5 kS/s**.
- **Interface I2S com PLL dedicado**, que lê o microfone digital a ≈32 kS/s em 24 bits. Os relógios do ADC e do I2S vêm do mesmo cristal, então os dois canais têm base de tempo comum. Isso permite comparar suas fases.
- **Temporizadores avançados**, que geram o PWM de potência do laser (5 kHz, passos de 0,1 %) e a onda quadrada de modulação (0,1 a 5000 Hz, resolução de 95 ns).
- **USB 2.0 Full Speed nativo (12 Mbit/s)**, que transmite os dois fluxos (≈160 kB/s) sem conversor externo.

## OPT101: referência óptica

O OPT101 (Texas Instruments) integra no mesmo encapsulamento um fotodiodo de 2,29 × 2,29 mm e um amplificador de transimpedância com resistor de realimentação interno de 1 MΩ. A integração elimina a capacitância e o ruído captado pelas ligações entre fotodiodo e amplificador, que são as principais fontes de erro em montagens discretas. Características típicas do datasheet:

- **Linearidade:** não linearidade de ±0,01 % do fundo de escala. A tensão de saída é proporcional à potência óptica incidente, o que permite usar o OPT101 como referência de intensidade para normalizar o sinal acústico.
- **Velocidade:** banda de 14 kHz com o ganho de 1 MΩ, muito acima das frequências de modulação usadas.
- **Sensibilidade:** responsividade de 0,45 A/W em 650 nm, isto é, 0,45 V/µW com o resistor interno. A resposta espectral vai de ~300 a 1100 nm.
- **Simplicidade:** alimentação única de 2,7 a 36 V e consumo de 120 µA. A saída analógica vai direto ao ADC.

## INMP441: detecção fotoacústica

O INMP441 (TDK InvenSense) é um microfone MEMS omnidirecional que contém o transdutor, o pré-amplificador, o conversor sigma-delta e o filtro anti-aliasing. A saída é digital, em I2S, com 24 bits. Como o sinal sai do encapsulamento já digitalizado, ele não sofre interferência eletromagnética nem atenuação nos fios até o microcontrolador. Características típicas do datasheet:

- **Precisão:** SNR de 61 dBA, sensibilidade de −26 dBFS a 94 dB SPL com tolerância de ±1 dB entre unidades, e rejeição de ruído da fonte de −75 dBFS.
- **Faixa dinâmica:** ponto de sobrecarga acústica em 120 dB SPL.
- **Resposta em frequência:** plana de ~60 Hz a 15 kHz. Abaixo de 60 Hz há uma atenuação de passa-altas, que o sistema corrige por calibração com um padrão de folha de alumínio.
- **Integração:** alimentação de 1,8 a 3,3 V, consumo de 1,4 mA e dimensões de poucos milímetros, o que facilita a instalação dentro da célula fotoacústica.

## Síntese

| | STM32 Black Pill | OPT101 | INMP441 |
|---|---|---|---|
| Função | Controle, sincronismo e aquisição | Mede a intensidade do laser | Mede o sinal fotoacústico |
| Velocidade | 84 MHz; ADC de até 2,4 MS/s | Banda de 14 kHz | 32 kS/s; banda de até 15 kHz |
| Resolução no sistema | 14 bits (óptico) e 24 bits (áudio) | 14 bits via ADC | 24 bits nativos |
| Linearidade / precisão | Base de tempo comum aos dois canais | ±0,01 % FS | SNR de 61 dBA, ±1 dB |
| Vantagem principal | Baixo custo, DMA, I2S e USB nativos | Fotodiodo e amplificador integrados | Saída digital imune a interferência |

Os três componentes juntos formam um sistema compacto e de baixo custo. A demodulação lock-in é feita em software e recupera, em amplitude e fase, sinais de amplitude muito menor que a do ruído, na faixa de modulação de 0,1 Hz a alguns quilohertz.
