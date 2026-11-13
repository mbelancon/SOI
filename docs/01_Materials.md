# 1. Required materials

Items marked with ⚠ are not defined in the code. Confirm them on the bench and complete this table.

## Hardware

| Item | Qty | Notes |
|---|---|---|
| **WeAct Black Pill STM32F401CCU6** | 1 | Board `blackpill_f401cc` in PlatformIO. **25 MHz** HSE crystal: the firmware assumes this value to generate the I2S clock. |
| **ST-Link V2 programmer** (or clone) | 1 | Flashing over SWD (`upload_protocol = stlink`). |
| **USB-C data cable** | 1 | Communication with the PC (USB CDC). A charge-only cable will not work. |
| **OPT101** (photodiode + transimpedance amplifier) | 1 | Measures the laser intensity. Analog output connected to PA0. |
| **INMP441 module** (I2S MEMS microphone) | 1 | Measures the photoacoustic signal. 3.3 V supply. |
| **Laser + driver** | 1 | The driver receives the 3.3 V PWM from PA8. ⚠ Model of the laser, the driver/transistor and the power supply. |
| Photoacoustic cell | 1 | Holds the sample and the INMP441. ⚠ Describe. |
| Calibration references (e.g. thin **aluminum foil**, carbon black, matte black tape) | — | Used to calibrate the microphone (Modo Duplo tab, Calibração panel). |
| Breadboard / board, jumpers | — | Keep the I2S wires short (BCLK ≈ 2 MHz). |
| Power supply for the OPT101 | — | ⚠ Voltage used (see the warning in [02_Hardware_and_Wiring.md](02_Hardware_and_Wiring.md#opt101)). |
| Oscilloscope (optional) | — | To watch the sync on PB0 and the OPT101 signal. |

## Software

| Item | Use |
|---|---|
| Windows 10/11 | Tested environment. The code is cross-platform but has only been used on Windows. |
| x86-64-v2 CPU (SSE4.2) | Required by numpy 2.4+ and Qt 6.10+: Intel since 2009 or AMD since 2011. AMD Phenom II, Athlon II and Intel Core 2 will not work. See [04_Interface.md](04_Interface.md#installation-and-running). |
| **VS Code + PlatformIO extension** | Build and flash the firmware. It installs the `ststm32` platform and the STM32Cube framework (`framework-stm32cubef4`) automatically. Optional: STM32CubeProgrammer to flash the prebuilt `.bin`. |
| ST-Link driver | Usually installed by PlatformIO / STM32CubeProgrammer. |
| **Python 3.10 or newer** (Miniconda) | Run the interface. |
| Python packages | `numpy`, `scipy`, `pyserial`, `pyqtgraph`, `PySide6` (or PyQt5/PyQt6). See [requirements.txt](../requirements.txt). |
| PyInstaller (optional) | Build a `.exe` of the interface. |

The STM32 USB CDC uses the native Windows 10/11 serial driver. No driver needs to be installed for the COM port.
