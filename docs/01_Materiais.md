# 1. Materiais necessários

Itens marcados com ⚠ não estão definidos no código. Confirme na bancada e complete esta tabela.

## Hardware

| Item | Qtd | Observações |
|---|---|---|
| **WeAct Black Pill STM32F401CCU6** | 1 | Placa `blackpill_f401cc` no PlatformIO. Cristal HSE de **25 MHz**: o firmware assume esse valor para gerar o relógio do I2S. |
| **Programador ST-Link V2** (ou clone) | 1 | Gravação via SWD (`upload_protocol = stlink`). |
| Cabo **USB-C de dados** | 1 | Comunicação com o PC (USB CDC). Cabo só de carga não serve. |
| **OPT101** (fotodiodo + amplificador de transimpedância) | 1 | Mede a intensidade do laser. Saída analógica ligada ao PA0. |
| **Módulo INMP441** (microfone MEMS I2S) | 1 | Mede o sinal fotoacústico. Alimentação de 3,3 V. |
| **Laser + driver** | 1 | O driver recebe o PWM de 3,3 V do PA8. ⚠ Modelo do laser, do driver/transistor e da fonte. |
| Célula fotoacústica | 1 | Onde ficam a amostra e o INMP441. ⚠ Descrever. |
| Padrão de **folha de alumínio** (fina, livre) | 1 | Usado na calibração do microfone (aba Modo Duplo). |
| Protoboard / placa, jumpers | — | Fios curtos no I2S (BCLK ≈ 2 MHz). |
| Fonte para o OPT101 | — | ⚠ Tensão usada (ver o aviso em [02_Hardware_e_Ligacoes.md](02_Hardware_e_Ligacoes.md#opt101)). |
| Osciloscópio (opcional) | — | Para ver o sincronismo no PB0 e o sinal do OPT101. |

## Software

| Item | Uso |
|---|---|
| Windows 10/11 | Ambiente testado. O código é multiplataforma, mas só foi usado no Windows. |
| Processador x86-64-v2 (SSE4.2) | Exigido pelo numpy 2.4+ e pelo Qt 6.10+: Intel desde 2009 ou AMD desde 2011. AMD Phenom II, Athlon II e Intel Core 2 não servem. Veja [04_Interface.md](04_Interface.md#instalação-e-execução). |
| **VS Code + extensão PlatformIO** | Compilar e gravar o firmware. Instala sozinho a plataforma `ststm32` e o framework Arduino-STM32. |
| Driver do ST-Link | Normalmente instalado pelo PlatformIO / STM32CubeProgrammer. |
| **Python 3.10 ou superior** (Miniconda) | Rodar a interface. |
| Pacotes Python | `numpy`, `scipy`, `pyserial`, `pyqtgraph`, `PySide6` (ou PyQt5/PyQt6). Veja [requirements.txt](../requirements.txt). |
| PyInstaller (opcional) | Gerar um executável `.exe` da interface. |

O USB CDC do STM32 usa o driver serial nativo do Windows 10/11. Não é preciso instalar driver para a porta COM.
