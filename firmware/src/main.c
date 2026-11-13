// Firmware SOI 2.0.0: lock-in OPT101 / INMP441 / laser no STM32F401 Black Pill (STM32Cube, sem STM32duino).
//
// OPT101: ADC1 (PA0) disparado pelo TIM3 a 200 kS/s, transferido por DMA circular. Cada amostra vai
// crua ao PC, sem sobreamostragem (a interface soma o número de amostras que o usuário escolher).
// Cada palavra de 16 bits leva o ADC (bits 0-11) e o estado do laser naquele instante (bit 15);
// os bits 12-14 valem 0.
//
// Pacote óptico:  A5 5A 4F 50 | SEQ (uint32) | N (uint16) | N x uint16 | CRC16
//   SEQ = número da primeira amostra desde a partida (sobe N a cada pacote; um salto = amostras perdidas).
// Pacote de áudio (INMP441 por I2S2: PB13=BCLK, PB12=WS, PB15=SD, 48 kHz, 24 bits):
//                  A5 5A 49 32 | SEQ (uint32) | N (uint16) | N x int24 | CRC16
// Marcador de modulação: A5 5A 4D 4B | SEQ (uint32) | CRC16
//   SEQ = número da amostra I2S em que a onda quadrada do laser começou (borda de subida).
// CRC16 = CRC-16/CCITT-FALSE dos bytes entre o cabeçalho de 4 bytes e o próprio CRC. Tudo little-endian.
//
// Comandos do PC (texto terminado em \n): "F<Hz>" frequência da modulação (0 = contínuo, 0,1 a 5000 Hz),
// "P<%>" potência do laser (PWM de 5 kHz em PA8, 0 a 100 %, passo de 0,1 %).
// PB0 repete o estado do laser (referência e sincronismo para osciloscópio).
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "stm32f4xx_hal.h"
#include "usbd_core.h"
#include "usbd_cdc.h"
#include "usbd_desc.h"
#include "usbd_cdc_if.h"

#define FIRMWARE_VERSION "2.0.0"          // versão do firmware (ver CHANGELOG.md)

#define TIMER_CLK_HZ 84000000UL           // TIM1 (APB2) e TIM3/TIM4 (APB1 x2)
#define LASER_PWM_HZ 5000UL               // portadora do PWM do laser
#define ADC_RATE_HZ 200000UL              // = RAW_FS da interface
#define MAX_MOD_HZ 5000.0
_Static_assert(TIMER_CLK_HZ % ADC_RATE_HZ == 0, "ADC_RATE_HZ deve dividir 84 MHz para taxa exata");

// ADC: meia janela do DMA = um pacote óptico (2,56 ms a 200 kS/s, 390 interrupções/s).
#define HALF_SAMPLES 512UL
#define OPT_RING 8192UL                   // amostras (41 ms); potência de 2
#define OPT_PACKET_MAX HALF_SAMPLES
#define OPT_PACKET_MIN 64UL               // não envia pacotes menores que isto (0,32 ms)
#define PACKET_HEADER 10UL
#define PACKET_CRC 2UL

#define AUDIO_FS_HZ 48000UL
#define AUDIO_HALF_FRAMES 256UL
#define AUDIO_HALFWORDS_PER_FRAME 4UL
#define AUDIO_DMA_HALFWORDS (2UL * AUDIO_HALF_FRAMES * AUDIO_HALFWORDS_PER_FRAME)
#define AUDIO_RING 2048UL                 // quadros (43 ms); potência de 2
#define AUDIO_PACKET_SIZE (PACKET_HEADER + 3UL * AUDIO_HALF_FRAMES + PACKET_CRC)
#define MOD_MARKER_SIZE 10UL
_Static_assert(AUDIO_FS_HZ == I2S_AUDIOFREQ_48K, "AUDIO_FS_HZ deve ser uma taxa do I2S");

// USB: dois buffers; enquanto um é enviado, o outro recebe os pacotes seguintes.
#define TX_BUF_SIZE 6144UL

USBD_HandleTypeDef hUsbDeviceFS;
ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdmaAdc;
I2S_HandleTypeDef hi2s2;
DMA_HandleTypeDef hdmaI2s2Rx;

// ---------------------------------------------------------------- CRC-16/CCITT-FALSE (tabela)
static uint16_t crcTable[256];

static void crcInit(void) {
  for (uint32_t i = 0; i < 256; ++i) {
    uint16_t c = (uint16_t)(i << 8);
    for (int b = 0; b < 8; ++b) c = (c & 0x8000U) ? (uint16_t)((c << 1) ^ 0x1021U) : (uint16_t)(c << 1);
    crcTable[i] = c;
  }
}

static uint16_t crc16(const uint8_t *d, uint32_t n) {
  uint16_t crc = 0xFFFF;
  while (n--) crc = (uint16_t)((crc << 8) ^ crcTable[((crc >> 8) ^ *d++) & 0xFFU]);
  return crc;
}

static inline void put16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }

// ---------------------------------------------------------------- Laser e modulação
static double modulationHz = 5.0;            // 0 = contínuo
static uint16_t powerTenthsPercent = 4;
static volatile uint8_t laserOutputState = 0;

// Início da modulação alinhado ao I2S: startModulation() deixa o TIM4 parado e a próxima interrupção
// do DMA do I2S liga o contador; o número da amostra I2S desse instante vai ao PC (marcador).
static int audioReady = 0;
static volatile int modStartPending = 0;
static volatile int modMarkerPending = 0;
static volatile uint32_t modMarkerSequence = 0;

// Escreve direto no comparador do TIM1 (sem preload) e no pino de referência PB0.
static inline void applyLaserOutput(void) {
  GPIOB->BSRR = laserOutputState ? GPIO_PIN_0 : (GPIO_PIN_0 << 16);
  TIM1->CCR1 = laserOutputState ? ((uint32_t)powerTenthsPercent * (TIM1->ARR + 1UL)) / 1000UL : 0;
}

// Estado do laser na mesma grade de amostras do DMA do ADC (o DMA não lê o pino de saída):
// refBuf[i] vale o estado do laser quando o DMA gravou dmaBuf[i].
#define REF_N (2UL * HALF_SAMPLES)
static uint16_t dmaBuf[REF_N];
static uint8_t refBuf[REF_N];
static volatile uint32_t refIdx = 0;      // próxima posição de refBuf a preencher

static inline uint32_t adcDmaIndex(void) {
  return (REF_N - DMA2_Stream0->NDTR) % REF_N;
}

// Preenche refBuf com o estado atual até 'idx' (circular). Chamar com IRQs bloqueadas ou de ISR.
static inline void fillRefTo(uint32_t idx) {
  uint32_t i = refIdx;
  if (((idx + REF_N - i) % REF_N) > (3UL * REF_N) / 4UL) return;   // idx "atrás" de refIdx: já feito
  uint8_t st = laserOutputState;
  while (i != idx) {
    refBuf[i] = st;
    i = (i + 1UL) % REF_N;
  }
  refIdx = i;
}

static void syncRefTo(uint32_t idx) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  fillRefTo(idx);
  __set_PRIMASK(primask);
}

static inline void syncRefNow(void) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  fillRefTo(adcDmaIndex());
  __set_PRIMASK(primask);
}

// Chamada pela interrupção do TIM4 (stm32f4xx_it.c), prioridade mais alta do sistema.
void modulationToggle(void) {
  fillRefTo(adcDmaIndex());
  laserOutputState ^= 1U;
  applyLaserOutput();
}

// Liga o contador do TIM4 (já configurado e zerado). O contador vem primeiro: o instante da partida
// é a origem de fase. O laser já está ligado desde startModulation(), então a ordem não altera o REF.
static void launchModulation(void) {
  TIM4->CR1 |= TIM_CR1_CEN;
  syncRefNow();
  laserOutputState = 1;
  applyLaserOutput();
}

// Configura o TIM4 com os mesmos arredondamentos da versão 1.0.0 (HardwareTimer do STM32duino),
// que a função actual_mod_freq() da interface reproduz.
static void startModulation(void) {
  modStartPending = 0;
  TIM4->DIER = 0;
  TIM4->CR1 = 0;
  syncRefNow();
  laserOutputState = 1;
  applyLaserOutput();
  if (modulationHz <= 0.0) return;   // contínuo

  uint32_t psc, arr;
  if (modulationHz >= 100.0) {
    // Ticks de 95 ns (prescaler 8) para não arredondar a frequência.
    uint32_t tick = TIMER_CLK_HZ / 8UL;
    uint32_t half = (uint32_t)((double)tick / (2.0 * modulationHz) + 0.5);
    psc = 8;
    arr = half;
  } else {
    uint32_t halfUs = (uint32_t)(500000.0 / modulationHz + 0.5);
    uint32_t cycles = halfUs * (TIMER_CLK_HZ / 1000000UL);
    psc = cycles / 0x10000UL + 1UL;
    arr = cycles / psc;
  }
  TIM4->PSC = psc - 1UL;
  TIM4->ARR = arr - 1UL;
  TIM4->CNT = 0;
  // Carrega PSC/ARR já (UG sem interrupção): o primeiro meio período sai exato e a borda de subida
  // fica onde o contador for ligado.
  TIM4->CR1 = TIM_CR1_URS;
  TIM4->EGR = TIM_EGR_UG;
  TIM4->SR = 0;
  TIM4->DIER = TIM_DIER_UIE;
  if (audioReady) {
    modStartPending = 1;   // launchModulation() na próxima interrupção do I2S
  } else {
    launchModulation();
  }
}

static void laserInit(void) {
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_TIM1_CLK_ENABLE();
  __HAL_RCC_TIM4_CLK_ENABLE();

  GPIO_InitTypeDef g = {0};
  g.Pin = GPIO_PIN_0;                     // PB0: referência
  g.Mode = GPIO_MODE_OUTPUT_PP;
  g.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOB, &g);

  // TIM1_CH1 (PA8): PWM de 5 kHz. CCR1 sem preload: vale imediatamente.
  TIM1->CR1 = 0;
  TIM1->PSC = 0;
  TIM1->ARR = TIMER_CLK_HZ / LASER_PWM_HZ - 1UL;
  TIM1->CCR1 = 0;
  TIM1->CCMR1 = (TIM1->CCMR1 & ~(TIM_CCMR1_OC1M | TIM_CCMR1_OC1PE | TIM_CCMR1_CC1S))
                | (6UL << TIM_CCMR1_OC1M_Pos);   // PWM modo 1
  TIM1->CCER |= TIM_CCER_CC1E;
  TIM1->BDTR |= TIM_BDTR_MOE;
  TIM1->EGR = TIM_EGR_UG;
  TIM1->CR1 |= TIM_CR1_CEN;

  g.Pin = GPIO_PIN_8;
  g.Mode = GPIO_MODE_AF_PP;
  g.Pull = GPIO_NOPULL;
  g.Speed = GPIO_SPEED_FREQ_HIGH;
  g.Alternate = GPIO_AF1_TIM1;
  HAL_GPIO_Init(GPIOA, &g);

  HAL_NVIC_SetPriority(TIM4_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(TIM4_IRQn);
}

static void applyCommand(const char *command) {
  if ((command[0] != 'F' && command[0] != 'P') || command[1] == '\0') return;
  char *end = NULL;
  double value = strtod(command + 1, &end);
  while (*end == ' ' || *end == '\t') ++end;
  if (end == command + 1 || *end != '\0' || !isfinite(value)) return;

  if (command[0] == 'F' && (value == 0.0 || (value >= 0.1 && value <= MAX_MOD_HZ))) {
    modulationHz = value;
    startModulation();
  } else if (command[0] == 'P' && value >= 0.0 && value <= 100.0) {
    powerTenthsPercent = (uint16_t)(value * 10.0 + 0.5);
    applyLaserOutput();
  }
}

static void receiveCommands(void) {
  static char buf[24];
  static uint32_t len = 0;
  static int discard = 0;
  int c;
  while ((c = cdcReadByte()) >= 0) {
    if (c == '\n') {
      if (!discard && len > 0) {
        buf[len] = '\0';
        applyCommand(buf);
      }
      len = 0;
      discard = 0;
    } else if (c == '\r' || discard) {
      continue;
    } else if (len < sizeof(buf) - 1U) {
      buf[len++] = (char)c;
    } else {
      discard = 1;
    }
  }
}

// ---------------------------------------------------------------- ADC (OPT101)
static uint16_t optRing[OPT_RING];
static volatile uint32_t optHead = 0;     // nº absoluto da próxima amostra (escrito na ISR)
static volatile uint32_t optTail = 0;     // nº absoluto da próxima amostra a enviar (escrito no loop)

static void pushOptical(const uint16_t *adc, const uint8_t *ref) {
  uint32_t head = optHead;
  for (uint32_t i = 0; i < HALF_SAMPLES; ++i) {
    // Se o PC atrasar, a amostra mais antiga é descartada: o salto de SEQ avisa a interface.
    if (head - optTail >= OPT_RING) optTail = head - OPT_RING + 1UL;
    optRing[head & (OPT_RING - 1UL)] = (uint16_t)((adc[i] & 0x0FFFU) | ((uint16_t)(ref[i] & 1U) << 15));
    ++head;
  }
  optHead = head;
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h) {
  if (h->Instance == ADC1) {
    syncRefTo(HALF_SAMPLES);
    pushOptical(&dmaBuf[0], &refBuf[0]);
  }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h) {
  if (h->Instance == ADC1) {
    syncRefTo(0);
    pushOptical(&dmaBuf[HALF_SAMPLES], &refBuf[HALF_SAMPLES]);
  }
}

static void adcInit(void) {
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_ADC1_CLK_ENABLE();
  __HAL_RCC_DMA2_CLK_ENABLE();
  __HAL_RCC_TIM3_CLK_ENABLE();

  GPIO_InitTypeDef g = {0};
  g.Pin = GPIO_PIN_0;
  g.Mode = GPIO_MODE_ANALOG;
  g.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &g);

  hdmaAdc.Instance = DMA2_Stream0;
  hdmaAdc.Init.Channel = DMA_CHANNEL_0;
  hdmaAdc.Init.Direction = DMA_PERIPH_TO_MEMORY;
  hdmaAdc.Init.PeriphInc = DMA_PINC_DISABLE;
  hdmaAdc.Init.MemInc = DMA_MINC_ENABLE;
  hdmaAdc.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
  hdmaAdc.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
  hdmaAdc.Init.Mode = DMA_CIRCULAR;
  hdmaAdc.Init.Priority = DMA_PRIORITY_HIGH;
  hdmaAdc.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
  HAL_DMA_Init(&hdmaAdc);
  __HAL_LINKDMA(&hadc1, DMA_Handle, hdmaAdc);
  HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);

  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;   // 84/4 = 21 MHz
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
  hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T3_TRGO;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  hadc1.Init.DMAContinuousRequests = ENABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  HAL_ADC_Init(&hadc1);

  // Amostragem longa (84 ciclos = 4 us), igual à 1.0.0: 96 ciclos por conversão cabem nos 105 do período.
  ADC_ChannelConfTypeDef ch = {0};
  ch.Channel = ADC_CHANNEL_0;
  ch.Rank = 1;
  ch.SamplingTime = ADC_SAMPLETIME_84CYCLES;
  HAL_ADC_ConfigChannel(&hadc1, &ch);

  // TIM3 gera o TRGO a cada 1/ADC_RATE_HZ; UG antes de armar o DMA.
  TIM3->PSC = 0;
  TIM3->ARR = TIMER_CLK_HZ / ADC_RATE_HZ - 1UL;
  TIM3->EGR = TIM_EGR_UG;
  TIM3->SR = 0;
  HAL_ADC_Start_DMA(&hadc1, (uint32_t *)dmaBuf, REF_N);
  TIM3->CR2 = (TIM3->CR2 & ~TIM_CR2_MMS) | TIM_TRGO_UPDATE;
  TIM3->CR1 |= TIM_CR1_CEN;
}

// ---------------------------------------------------------------- I2S (INMP441)
// Cada quadro I2S tem os dois slots estéreo; só o esquerdo é usado.
static uint16_t i2sDmaBuf[AUDIO_DMA_HALFWORDS];
static int32_t audioRing[AUDIO_RING];
static volatile uint32_t audioHead = 0;
static volatile uint32_t audioTail = 0;
static volatile uint32_t audioTailSequence = 0;
static volatile uint32_t audioNextSequence = 0;
static int audioDmaInitOk = 0;

static void pushAudioFrames(uint32_t firstFrame) {
  for (uint32_t frame = 0; frame < AUDIO_HALF_FRAMES; ++frame) {
    uint32_t off = (firstFrame + frame) * AUDIO_HALFWORDS_PER_FRAME;
    uint32_t s = ((uint32_t)i2sDmaBuf[off] << 8) | ((uint32_t)i2sDmaBuf[off + 1] >> 8);
    int32_t v = (s & 0x00800000UL) ? (int32_t)(s | 0xFF000000UL) : (int32_t)s;
    uint32_t head = audioHead;
    uint32_t next = (head + 1UL) & (AUDIO_RING - 1UL);
    if (next == audioTail) {               // anel cheio: descarta a mais antiga
      audioTail = (audioTail + 1UL) & (AUDIO_RING - 1UL);
      ++audioTailSequence;
    }
    audioRing[head] = v;
    audioHead = next;
    ++audioNextSequence;
  }
}

static inline uint32_t i2sDmaHalfwordIndex(void) {
  return (AUDIO_DMA_HALFWORDS - DMA1_Stream3->NDTR) % AUDIO_DMA_HALFWORDS;
}

// Liga a modulação pendente exatamente numa fronteira de quadro I2S e registra o número desse quadro
// (ver a explicação na versão 1.0.0). Espera no máximo ~1,25 quadro (~40 us), só com partida pendente.
static void startPendingModulation(uint32_t boundaryFrame) {
  if (!modStartPending) return;
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  while ((i2sDmaHalfwordIndex() % AUDIO_HALFWORDS_PER_FRAME) == 0) {}
  uint32_t idx;
  while (((idx = i2sDmaHalfwordIndex()) % AUDIO_HALFWORDS_PER_FRAME) != 0) {}
  launchModulation();
  uint32_t frame = idx / AUDIO_HALFWORDS_PER_FRAME;
  uint32_t lag = (frame + 2UL * AUDIO_HALF_FRAMES - boundaryFrame) % (2UL * AUDIO_HALF_FRAMES);
  modStartPending = 0;
  modMarkerSequence = audioNextSequence + lag;
  modMarkerPending = 1;
  __set_PRIMASK(primask);
}

void HAL_I2S_RxHalfCpltCallback(I2S_HandleTypeDef *h) {
  if (h->Instance == SPI2) {
    pushAudioFrames(0);
    startPendingModulation(AUDIO_HALF_FRAMES);
  }
}

void HAL_I2S_RxCpltCallback(I2S_HandleTypeDef *h) {
  if (h->Instance == SPI2) {
    pushAudioFrames(AUDIO_HALF_FRAMES);
    startPendingModulation(0);
  }
}

void HAL_I2S_MspInit(I2S_HandleTypeDef *h) {
  if (h->Instance != SPI2) return;
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_SPI2_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  GPIO_InitTypeDef g = {0};
  g.Pin = GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_15;
  g.Mode = GPIO_MODE_AF_PP;
  g.Pull = GPIO_NOPULL;
  g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  g.Alternate = GPIO_AF5_SPI2;
  HAL_GPIO_Init(GPIOB, &g);

  hdmaI2s2Rx.Instance = DMA1_Stream3;
  hdmaI2s2Rx.Init.Channel = DMA_CHANNEL_0;
  hdmaI2s2Rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
  hdmaI2s2Rx.Init.PeriphInc = DMA_PINC_DISABLE;
  hdmaI2s2Rx.Init.MemInc = DMA_MINC_ENABLE;
  hdmaI2s2Rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
  hdmaI2s2Rx.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
  hdmaI2s2Rx.Init.Mode = DMA_CIRCULAR;
  hdmaI2s2Rx.Init.Priority = DMA_PRIORITY_HIGH;
  hdmaI2s2Rx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
  audioDmaInitOk = HAL_DMA_Init(&hdmaI2s2Rx) == HAL_OK;
  if (!audioDmaInitOk) return;
  __HAL_LINKDMA(h, hdmarx, hdmaI2s2Rx);
  HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);
}

// Entrada de 25 MHz / 25 = 1 MHz, VCO de 384 MHz, I2SCLK = 384 / 5 = 76,8 MHz
// -> 76,8 MHz / (64 * 25) = 48000 Hz exatos (I2SDIV = 12, ODD = 1).
static int audioInit(void) {
  RCC_PeriphCLKInitTypeDef clock = {0};
  clock.PeriphClockSelection = RCC_PERIPHCLK_I2S;
  clock.PLLI2S.PLLI2SN = 384;
  clock.PLLI2S.PLLI2SR = 5;
  if (HAL_RCCEx_PeriphCLKConfig(&clock) != HAL_OK) return 0;
  // O HAL deixa PLLI2SM = 0 neste chip; força M = 25 (entrada de 1 MHz).
  __HAL_RCC_PLLI2S_DISABLE();
  while (RCC->CR & RCC_CR_PLLI2SRDY) {}
  RCC->PLLI2SCFGR = (RCC->PLLI2SCFGR & ~0x3FUL) | 25UL;
  __HAL_RCC_PLLI2S_ENABLE();
  while (!(RCC->CR & RCC_CR_PLLI2SRDY)) {}

  hi2s2.Instance = SPI2;
  hi2s2.Init.Mode = I2S_MODE_MASTER_RX;
  hi2s2.Init.Standard = I2S_STANDARD_PHILIPS;
  hi2s2.Init.DataFormat = I2S_DATAFORMAT_24B;
  hi2s2.Init.MCLKOutput = I2S_MCLKOUTPUT_DISABLE;
  hi2s2.Init.AudioFreq = AUDIO_FS_HZ;
  hi2s2.Init.CPOL = I2S_CPOL_LOW;
  hi2s2.Init.ClockSource = I2S_CLOCK_PLL;
  hi2s2.Init.FullDuplexMode = I2S_FULLDUPLEXMODE_DISABLE;
  if (HAL_I2S_Init(&hi2s2) != HAL_OK || !audioDmaInitOk) return 0;
  // Garante o divisor exato (o HAL calcula o mesmo, mas a partir da sua leitura dos registradores do PLL).
  SPI2->I2SPR = 12U | SPI_I2SPR_ODD;
  return HAL_I2S_Receive_DMA(&hi2s2, i2sDmaBuf, AUDIO_DMA_HALFWORDS / 2UL) == HAL_OK;
}

// ---------------------------------------------------------------- Pacotes
static uint32_t prepareOptical(uint8_t *out, uint32_t room) {
  if (room < PACKET_HEADER + 2UL * OPT_PACKET_MIN + PACKET_CRC) return 0;
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  uint32_t tail = optTail, head = optHead;
  __set_PRIMASK(primask);
  uint32_t n = head - tail;
  if (n < OPT_PACKET_MIN) return 0;
  uint32_t fit = (room - PACKET_HEADER - PACKET_CRC) / 2UL;
  if (n > OPT_PACKET_MAX) n = OPT_PACKET_MAX;
  if (n > fit) n = fit;
  out[0] = 0xA5; out[1] = 0x5A; out[2] = 0x4F; out[3] = 0x50;
  put32(&out[4], tail);
  put16(&out[8], n);
  uint8_t *p = &out[PACKET_HEADER];
  for (uint32_t i = 0; i < n; ++i, p += 2) put16(p, optRing[(tail + i) & (OPT_RING - 1UL)]);
  // A ISR pode ter sobrescrito o começo do trecho durante a cópia (PC muito atrasado): descarta.
  primask = __get_PRIMASK();
  __disable_irq();
  int overrun = (optTail != tail);
  if (!overrun) optTail = tail + n;
  __set_PRIMASK(primask);
  if (overrun) return 0;
  put16(p, crc16(&out[4], (uint32_t)(p - &out[4])));
  return PACKET_HEADER + 2UL * n + PACKET_CRC;
}

static uint32_t prepareAudio(uint8_t *out, uint32_t room) {
  if (!audioReady || room < AUDIO_PACKET_SIZE) return 0;
  static int32_t samples[AUDIO_HALF_FRAMES];
  // Bloqueia só a IRQ do I2S (prioridade 2) e as abaixo dela; TIM4 e ADC continuam atendidos.
  uint32_t basepri = __get_BASEPRI();
  __set_BASEPRI_MAX(2UL << (8U - __NVIC_PRIO_BITS));
  if (((audioHead - audioTail) & (AUDIO_RING - 1UL)) < AUDIO_HALF_FRAMES) {
    __set_BASEPRI(basepri);
    return 0;
  }
  uint32_t sequence = audioTailSequence;
  for (uint32_t i = 0; i < AUDIO_HALF_FRAMES; ++i) samples[i] = audioRing[(audioTail + i) & (AUDIO_RING - 1UL)];
  audioTail = (audioTail + AUDIO_HALF_FRAMES) & (AUDIO_RING - 1UL);
  audioTailSequence += AUDIO_HALF_FRAMES;
  __set_BASEPRI(basepri);

  out[0] = 0xA5; out[1] = 0x5A; out[2] = 0x49; out[3] = 0x32;
  put32(&out[4], sequence);
  put16(&out[8], AUDIO_HALF_FRAMES);
  uint8_t *p = &out[PACKET_HEADER];
  for (uint32_t i = 0; i < AUDIO_HALF_FRAMES; ++i) {
    uint32_t s = (uint32_t)samples[i];
    *p++ = (uint8_t)s; *p++ = (uint8_t)(s >> 8); *p++ = (uint8_t)(s >> 16);
  }
  put16(p, crc16(&out[4], (uint32_t)(p - &out[4])));
  return AUDIO_PACKET_SIZE;
}

static uint32_t prepareMarker(uint8_t *out, uint32_t room) {
  if (room < MOD_MARKER_SIZE) return 0;
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  int pending = modMarkerPending;
  uint32_t sequence = modMarkerSequence;
  modMarkerPending = 0;
  __set_PRIMASK(primask);
  if (!pending) return 0;
  out[0] = 0xA5; out[1] = 0x5A; out[2] = 0x4D; out[3] = 0x4B;
  put32(&out[4], sequence);
  put16(&out[8], crc16(&out[4], 4));
  return MOD_MARKER_SIZE;
}

// Descarta tudo o que estiver pendente (porta fechada no PC).
static void flushPending(void) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  optTail = optHead;
  audioTail = audioHead;
  audioTailSequence = audioNextSequence;
  __set_PRIMASK(primask);
}

// ---------------------------------------------------------------- Relógio e USB
static void clockInit(void) {
  // HSE 25 MHz -> PLL: VCO 336 MHz, SYSCLK 84 MHz, USB 48 MHz.
  RCC_OscInitTypeDef osc = {0};
  RCC_ClkInitTypeDef clk = {0};
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);
  osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  osc.HSEState = RCC_HSE_ON;
  osc.PLL.PLLState = RCC_PLL_ON;
  osc.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  osc.PLL.PLLM = 25;
  osc.PLL.PLLN = 336;
  osc.PLL.PLLP = RCC_PLLP_DIV4;
  osc.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&osc) != HAL_OK) while (1) {}
  clk.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
  clk.APB1CLKDivider = RCC_HCLK_DIV2;
  clk.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_2) != HAL_OK) while (1) {}
}

static void usbInit(void) {
  USBD_Init(&hUsbDeviceFS, &FS_Desc, DEVICE_FS);
  USBD_RegisterClass(&hUsbDeviceFS, &USBD_CDC);
  USBD_CDC_RegisterInterface(&hUsbDeviceFS, &USBD_Interface_fops_FS);
  USBD_Start(&hUsbDeviceFS);
}

static uint8_t txBuf[2][TX_BUF_SIZE] __attribute__((aligned(4)));

int main(void) {
  HAL_Init();
  clockInit();
  crcInit();
  laserInit();
  usbInit();
  startModulation();          // sem áudio ainda: liga a modulação na hora
  adcInit();
  audioReady = audioInit();
  if (audioReady && modulationHz > 0.0) startModulation();   // repete alinhado ao I2S (marcador)

  uint32_t fill = 0;          // buffer sendo preenchido
  uint32_t len = 0;           // bytes já no buffer 'fill'
  while (1) {
    receiveCommands();
    if (!cdcHostOpen) {
      flushPending();
      len = 0;
      continue;
    }
    uint8_t *buf = txBuf[fill];
    // O óptico vem primeiro (perdas quebram o PLL do lock-in); depois o marcador e o áudio.
    uint32_t k;
    while ((k = prepareOptical(&buf[len], TX_BUF_SIZE - len)) > 0) len += k;
    len += prepareMarker(&buf[len], TX_BUF_SIZE - len);
    while ((k = prepareAudio(&buf[len], TX_BUF_SIZE - len)) > 0) len += k;
    if (len > 0 && cdcTransmit(buf, len)) {
      fill ^= 1U;
      len = 0;
    }
  }
}
