// Lock-in OPT101 / laser para STM32F401 Black Pill (framework Arduino-STM32).
//
// ADC1 (PA0) disparado por TIM3 a FS_HZ * OSR, transferido por DMA circular.
// Cada bloco de OSR amostras é somado e deslocado (oversampling + decimação):
// 12 bits + OVS_BITS bits de resolução efetiva (soma de 4^n amostras >> n).
// Quadro óptico enviado por USB CDC (compatível com lockin_dsp):
//   0x55 0xAA ADC_L ADC_H REF
// O valor ADC é de 12+OVS_BITS bits (OVS_BITS=2 -> 0..16380).
// O estado do laser (REF) é amostrado por DMA no mesmo gatilho do ADC, a partir
// do pino PB0 (que também serve de saída de sincronismo para o osciloscópio).
// I2S2: PB13=BCLK, PB12=WS, PB15=SD. Áudio em pacotes A5 5A 49 32,
// com PCM assinado de 24 bits.
// Marcador de modulação A5 5A 4D 4B + SEQ (4 bytes) + CRC16: número da amostra I2S em que a
// onda quadrada do laser começou (borda de subida). O lock-in do INMP441 mede a fase a partir dela.
#include <Arduino.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#define FIRMWARE_VERSION "1.0.0"         // versão do firmware (ver CHANGELOG.md)

static const uint32_t LASER_PIN = PA8;    // TIM1_CH1
#define LASER_PWM_HZ 5000UL              // portadora do PWM do laser

#define OVS_BITS 2                        // bits extras: 2 -> OSR=16, resultado 14 bits
#define OSR (1UL << (2 * OVS_BITS))
#define FS_HZ 12500UL                      // taxa de saída (amostras/s) -> ajuste FS no Python; ADC a 200 kHz
#define ADC_RATE_HZ (FS_HZ * OSR)         // taxa real do ADC
#define TIMER_CLK_HZ 84000000UL           // TIM3 (APB1 x2)
static_assert(ADC_RATE_HZ <= 200000UL, "ADC_RATE_HZ acima do limite (~218 kHz com 84 ciclos)");
static_assert(TIMER_CLK_HZ % ADC_RATE_HZ == 0, "ADC_RATE_HZ deve dividir 84 MHz para taxa exata");

#define AUDIO_FS_HZ 32000UL               // 48 kHz não cabia na banda do USB CDC junto com o óptico
#define AUDIO_HALF_FRAMES 256UL
#define AUDIO_HALFWORDS_PER_FRAME 4UL
#define AUDIO_DMA_HALFWORDS (2UL * AUDIO_HALF_FRAMES * AUDIO_HALFWORDS_PER_FRAME)
#define AUDIO_RING_FRAMES 4096UL
#define AUDIO_RING_MASK (AUDIO_RING_FRAMES - 1UL)
#define AUDIO_PACKET_HEADER_SIZE 10UL
#define AUDIO_PACKET_CRC_SIZE 2UL
#define AUDIO_PACKET_MAX_SIZE (AUDIO_PACKET_HEADER_SIZE + 3UL * AUDIO_HALF_FRAMES + AUDIO_PACKET_CRC_SIZE)
#define MOD_MARKER_SIZE 10UL
static_assert(AUDIO_FS_HZ == I2S_AUDIOFREQ_32K, "AUDIO_FS_HZ must match the I2S clock");

// Amostras por meia-janela do DMA (múltiplo de OSR): evita uma IRQ por amostra.
#define HALF_SAMPLES (OSR > 64UL ? OSR : 64UL)
#define FRAMES_PER_HALF (HALF_SAMPLES / OSR)

static const uint32_t PWM_RESOLUTION_BITS = 10;
static const uint32_t MAX_MOD_HZ = 5000;

// ---------------------------------------------------------------- Laser
char commandBuffer[24];
uint8_t commandLength = 0;
bool discardCommand = false;

double modulationHz = 5.0;               // 0 = contínuo
uint16_t powerTenthsPercent = 4;
volatile uint8_t laserOutputState = 0;

// Início da modulação alinhado ao I2S: startModulation() configura o TIM4 parado e a próxima
// interrupção do DMA do I2S liga o contador; o número da amostra I2S desse instante vai ao PC.
static bool audioReady = false;
static volatile bool modStartPending = false;
static volatile bool modMarkerPending = false;
static volatile uint32_t modMarkerSequence = 0;

// Escreve direto no comparador do TIM1 (sem preload) e no pino de referência PB0.
static inline void applyLaserOutput() {
  GPIOB->BSRR = laserOutputState ? GPIO_PIN_0 : (GPIO_PIN_0 << 16);
  TIM1->CCR1 = laserOutputState
                   ? ((uint32_t)powerTenthsPercent * (TIM1->ARR + 1UL)) / 1000UL
                   : 0;
}

// Onda quadrada 50% gerada por TIM4: a cada meio período inverte o estado,
// sem depender da latência do loop() (USB, etc.).
static HardwareTimer modTimer(TIM4);

// Estado do laser registrado na mesma grade de amostras do DMA do ADC (a DMA1 não lê GPIO,
// então não há DMA para o pino). refBuf[i] vale o estado do laser quando o DMA gravou dmaBuf[i].
#define REF_N (2 * HALF_SAMPLES)
static uint16_t refBuf[REF_N];
static volatile uint32_t refIdx = 0;  // próxima posição de refBuf a preencher

// Preenche refBuf com o estado atual até a posição 'idx' (circular). Chamar com IRQs bloqueadas
// ou de ISR de prioridade mais alta que as demais usuárias.
static inline void fillRefTo(uint32_t idx) {
  uint32_t i = refIdx;
  if (((idx + REF_N - i) % REF_N) > (3 * REF_N) / 4) {
    return;  // idx está "atrás" de refIdx: já foi preenchido
  }
  uint16_t st = laserOutputState;
  while (i != idx) {
    refBuf[i] = st;
    i = (i + 1) % REF_N;
  }
  refIdx = i;
}

// Posição atual de escrita do DMA do ADC (0 antes de ele iniciar).
static inline uint32_t adcDmaIndex() {
  return (REF_N - DMA2_Stream0->NDTR) % REF_N;
}

static inline void syncRefNow() {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  fillRefTo(adcDmaIndex());
  __set_PRIMASK(primask);
}

static void modulationToggle() {
  fillRefTo(adcDmaIndex());
  laserOutputState ^= 1;
  applyLaserOutput();
}

// Liga o contador do TIM4 (já configurado e zerado) e o laser. Chamar com o TIM4 parado.
// O contador é ligado primeiro: o instante da partida é a origem de fase, e o syncRefNow()
// tem duração variável. O laser já está ligado desde startModulation(), então a ordem não altera o REF.
static void launchModulation() {
  TIM4->CR1 |= TIM_CR1_CEN;
  syncRefNow();
  laserOutputState = 1;
  applyLaserOutput();
}

static void startModulation() {
  modStartPending = false;
  modTimer.detachInterrupt();
  modTimer.pause();
  syncRefNow();
  laserOutputState = 1;
  applyLaserOutput();
  if (modulationHz <= 0.0) {
    return;  // contínuo
  }
  // Acima de 100 Hz usa ticks do timer (prescaler 8 -> 95 ns) para não arredondar a frequência.
  if (modulationHz >= 100.0) {
    uint32_t tick = modTimer.getTimerClkFreq() / 8;
    uint32_t half = (uint32_t)((double)tick / (2.0 * modulationHz) + 0.5);
    modTimer.setPrescaleFactor(8);
    modTimer.setOverflow(half, TICK_FORMAT);
  } else {
    uint32_t halfUs = (uint32_t)(500000.0 / modulationHz + 0.5);
    modTimer.setPrescaleFactor(1);
    modTimer.setOverflow(halfUs, MICROSEC_FORMAT);
  }
  modTimer.setCount(0);
  TIM4->SR = 0;
  modTimer.attachInterrupt(modulationToggle);
  modTimer.setInterruptPriority(0, 0);
  modTimer.resume();
  // Para o contador e carrega PSC/ARR já (UG sem gerar interrupção): o primeiro meio período
  // sai exato, e a borda de subida fica onde o contador for ligado.
  TIM4->CR1 &= ~TIM_CR1_CEN;
  TIM4->CR1 |= TIM_CR1_URS;
  TIM4->EGR = TIM_EGR_UG;
  TIM4->SR = 0;
  if (audioReady) {
    modStartPending = true;   // launchModulation() na próxima interrupção do I2S
  } else {
    launchModulation();
  }
}

static void initModulation() {
  __HAL_RCC_GPIOB_CLK_ENABLE();
  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = GPIO_PIN_0;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOB, &gpio);

  TIM1->CCMR1 &= ~TIM_CCMR1_OC1PE;  // CCR1 vale imediatamente (sem esperar o período da portadora)
  startModulation();
}

void applyCommand(const char *command) {
  if ((command[0] != 'F' && command[0] != 'P') || command[1] == '\0') {
    return;
  }

  char *end = nullptr;
  double value = strtod(command + 1, &end);
  while (*end == ' ' || *end == '\t') {
    ++end;
  }
  if (end == command + 1 || *end != '\0' || !isfinite(value)) {
    return;
  }

  if (command[0] == 'F' && (value == 0.0 || (value >= 0.1 && value <= (double)MAX_MOD_HZ))) {
    modulationHz = value;
    startModulation();
  } else if (command[0] == 'P' && value >= 0.0 && value <= 100.0) {
    powerTenthsPercent = (uint16_t)(value * 10.0 + 0.5);
    applyLaserOutput();
  }
}

void receiveCommands() {
  while (Serial.available() > 0) {
    char incoming = (char)Serial.read();

    if (incoming == '\n') {
      if (!discardCommand && commandLength > 0) {
        commandBuffer[commandLength] = '\0';
        applyCommand(commandBuffer);
      }
      commandLength = 0;
      discardCommand = false;
      continue;
    }

    if (incoming == '\r' || discardCommand) {
      continue;
    }

    if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = incoming;
    } else {
      discardCommand = true;
    }
  }
}

// ------------------------------------------------- ADC + DMA + oversampling
static ADC_HandleTypeDef hadc1;
static DMA_HandleTypeDef hdmaAdc;
static uint16_t dmaBuf[2 * HALF_SAMPLES];

static const uint32_t FRAME_SIZE = 5;
static const uint32_t RING_FRAMES = 4096;  // potência de 2 (~41 ms a 100 kHz)
static uint8_t ring[RING_FRAMES * FRAME_SIZE];
static volatile uint32_t ringHead = 0;     // em quadros (escrito na ISR)
static volatile uint32_t ringTail = 0;     // em quadros (escrito no loop)

// Cada quadro I2S contém os dois slots estéreo; somente o slot esquerdo é usado.
static I2S_HandleTypeDef hi2s2;
static DMA_HandleTypeDef hdmaI2s2Rx;
static uint16_t i2sDmaBuf[AUDIO_DMA_HALFWORDS];
static int32_t audioRing[AUDIO_RING_FRAMES];
static volatile uint32_t audioHead = 0;
static volatile uint32_t audioTail = 0;
static volatile uint32_t audioTailSequence = 0;
static volatile uint32_t audioNextSequence = 0;
static bool audioDmaInitOk = false;

// Um único write USB agrega quadros ópticos e vários pacotes de áudio (menos overhead por transferência).
// O óptico tem prioridade: é drenado por inteiro a cada write (quadros perdidos quebram o PLL do lock-in);
// o áudio usa a banda que sobrar e, se faltar, o anel de áudio sobrescreve as amostras mais antigas.
#define TX_OPTICAL_MAX_FRAMES 1000UL
#define TX_AUDIO_MAX_PACKETS 3UL
#define TX_BUFFER_SIZE (TX_OPTICAL_MAX_FRAMES * 5UL + TX_AUDIO_MAX_PACKETS * AUDIO_PACKET_MAX_SIZE + MOD_MARKER_SIZE)
static uint8_t txBuffer[TX_BUFFER_SIZE];
static uint16_t txLength = 0;
static uint16_t txOffset = 0;

static void syncRefTo(uint32_t idx) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  fillRefTo(idx);
  __set_PRIMASK(primask);
}

static void pushFrames(const uint16_t *adc, const uint16_t *ref) {
  uint32_t head = ringHead;
  for (uint32_t k = 0; k < FRAMES_PER_HALF; ++k) {
    uint32_t sum = 0;
    uint32_t refSum = 0;
    for (uint32_t i = 0; i < OSR; ++i) {
      sum += adc[k * OSR + i];
      refSum += ref[k * OSR + i] & 1U;
    }
    uint16_t value = (uint16_t)(sum >> OVS_BITS);

    if (((head + 1) & (RING_FRAMES - 1)) == ringTail) {
      break;  // buffer cheio (host lento): descarta o restante do bloco
    }
    uint8_t *f = &ring[head * FRAME_SIZE];
    f[0] = 0x55;
    f[1] = 0xAA;
    f[2] = (uint8_t)(value & 0xFF);
    f[3] = (uint8_t)(value >> 8);
    f[4] = (2 * refSum >= OSR) ? 1 : 0;
    head = (head + 1) & (RING_FRAMES - 1);
    ringHead = head;
  }
}

static void pushAudioFrames(uint32_t firstFrame) {
  for (uint32_t frame = 0; frame < AUDIO_HALF_FRAMES; ++frame) {
    uint32_t offset = (firstFrame + frame) * AUDIO_HALFWORDS_PER_FRAME;
    uint32_t sample = ((uint32_t)i2sDmaBuf[offset] << 8) |
                      ((uint32_t)i2sDmaBuf[offset + 1] >> 8);
    int32_t signedSample = (sample & 0x00800000UL)
                               ? (int32_t)(sample | 0xFF000000UL)
                               : (int32_t)sample;

    uint32_t head = audioHead;
    uint32_t next = (head + 1) & AUDIO_RING_MASK;
    if (next == audioTail) {
      audioTail = (audioTail + 1) & AUDIO_RING_MASK;
      ++audioTailSequence;
    }
    audioRing[head] = signedSample;
    audioHead = next;
    ++audioNextSequence;
  }
}

static uint16_t crc16Ccitt(const uint8_t *data, uint32_t length) {
  uint16_t crc = 0xFFFF;
  for (uint32_t i = 0; i < length; ++i) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000U) ? (uint16_t)((crc << 1) ^ 0x1021U)
                             : (uint16_t)(crc << 1);
    }
  }
  return crc;
}

static uint16_t prepareAudioPacket(uint8_t *txBuffer) {
  int32_t samples[AUDIO_HALF_FRAMES];
  uint32_t sequence;
  // Bloqueia só a IRQ do I2S (prioridade 2) e as abaixo dela. O TIM4 (borda do laser) e o
  // ADC continuam atendidos durante a cópia das 256 amostras.
  uint32_t basepri = __get_BASEPRI();
  __set_BASEPRI_MAX(2UL << (8U - __NVIC_PRIO_BITS));
  uint32_t available = (audioHead - audioTail) & AUDIO_RING_MASK;
  if (available < AUDIO_HALF_FRAMES) {
    __set_BASEPRI(basepri);
    return 0;
  }

  sequence = audioTailSequence;
  for (uint32_t i = 0; i < AUDIO_HALF_FRAMES; ++i) {
    samples[i] = audioRing[(audioTail + i) & AUDIO_RING_MASK];
  }
  audioTail = (audioTail + AUDIO_HALF_FRAMES) & AUDIO_RING_MASK;
  audioTailSequence += AUDIO_HALF_FRAMES;
  __set_BASEPRI(basepri);

  txBuffer[0] = 0xA5;
  txBuffer[1] = 0x5A;
  txBuffer[2] = 0x49;
  txBuffer[3] = 0x32;
  txBuffer[4] = (uint8_t)(sequence & 0xFF);
  txBuffer[5] = (uint8_t)((sequence >> 8) & 0xFF);
  txBuffer[6] = (uint8_t)((sequence >> 16) & 0xFF);
  txBuffer[7] = (uint8_t)((sequence >> 24) & 0xFF);
  txBuffer[8] = (uint8_t)(AUDIO_HALF_FRAMES & 0xFF);
  txBuffer[9] = (uint8_t)(AUDIO_HALF_FRAMES >> 8);

  uint32_t pos = AUDIO_PACKET_HEADER_SIZE;
  for (uint32_t i = 0; i < AUDIO_HALF_FRAMES; ++i) {
    uint32_t sample = (uint32_t)samples[i] & 0x00FFFFFFUL;
    txBuffer[pos++] = (uint8_t)(sample & 0xFF);
    txBuffer[pos++] = (uint8_t)((sample >> 8) & 0xFF);
    txBuffer[pos++] = (uint8_t)((sample >> 16) & 0xFF);
  }
  uint16_t crc = crc16Ccitt(&txBuffer[4], pos - 4);
  txBuffer[pos++] = (uint8_t)(crc & 0xFF);
  txBuffer[pos++] = (uint8_t)(crc >> 8);
  return (uint16_t)pos;
}

static uint16_t prepareModMarker(uint8_t *out) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  bool pending = modMarkerPending;
  uint32_t sequence = modMarkerSequence;
  modMarkerPending = false;
  __set_PRIMASK(primask);
  if (!pending) {
    return 0;
  }
  out[0] = 0xA5;
  out[1] = 0x5A;
  out[2] = 0x4D;
  out[3] = 0x4B;
  out[4] = (uint8_t)(sequence & 0xFF);
  out[5] = (uint8_t)((sequence >> 8) & 0xFF);
  out[6] = (uint8_t)((sequence >> 16) & 0xFF);
  out[7] = (uint8_t)((sequence >> 24) & 0xFF);
  uint16_t crc = crc16Ccitt(&out[4], 4);
  out[8] = (uint8_t)(crc & 0xFF);
  out[9] = (uint8_t)(crc >> 8);
  return (uint16_t)MOD_MARKER_SIZE;
}

static uint16_t prepareOpticalFrames(uint8_t *out) {
  uint32_t tail = ringTail;
  uint32_t head = ringHead;
  if (head == tail) {
    return 0;
  }

  uint32_t frames = (head > tail) ? (head - tail) : (RING_FRAMES - tail);
  if (frames > TX_OPTICAL_MAX_FRAMES) {
    frames = TX_OPTICAL_MAX_FRAMES;
  }
  uint32_t bytes = frames * FRAME_SIZE;
  memcpy(out, &ring[tail * FRAME_SIZE], bytes);
  ringTail = (tail + frames) & (RING_FRAMES - 1);
  return (uint16_t)bytes;
}

static bool startAudio() {
  RCC_PeriphCLKInitTypeDef clock = {0};
  clock.PeriphClockSelection = RCC_PERIPHCLK_I2S;
  clock.PLLI2S.PLLI2SN = 258;
  clock.PLLI2S.PLLI2SR = 3;
  if (HAL_RCCEx_PeriphCLKConfig(&clock) != HAL_OK) {
    return false;
  }

  // O HAL deixa PLLI2SM = 0 neste chip; força M = 25 (entrada de 1 MHz) para o I2SCLK ser 86 MHz.
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
  if (HAL_I2S_Init(&hi2s2) != HAL_OK) {
    return false;
  }
  if (!audioDmaInitOk) {
    return false;
  }

  return HAL_I2S_Receive_DMA(&hi2s2, i2sDmaBuf, AUDIO_DMA_HALFWORDS / 2UL) == HAL_OK;
}

extern "C" void HAL_I2S_MspInit(I2S_HandleTypeDef *h) {
  if (h->Instance != SPI2) {
    return;
  }

  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_SPI2_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_15;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = GPIO_AF5_SPI2;
  HAL_GPIO_Init(GPIOB, &gpio);

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
  if (!audioDmaInitOk) {
    return;
  }
  __HAL_LINKDMA(h, hdmarx, hdmaI2s2Rx);

  HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);
}

extern "C" {
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h) {
  if (h->Instance == ADC1) {
    syncRefTo(HALF_SAMPLES);
    pushFrames(&dmaBuf[0], &refBuf[0]);
  }
}
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h) {
  if (h->Instance == ADC1) {
    syncRefTo(0);
    pushFrames(&dmaBuf[HALF_SAMPLES], &refBuf[HALF_SAMPLES]);
  }
}
// Posição atual de escrita do DMA do I2S, em meias-palavras (4 por quadro).
static inline uint32_t i2sDmaHalfwordIndex() {
  return (AUDIO_DMA_HALFWORDS - DMA1_Stream3->NDTR) % AUDIO_DMA_HALFWORDS;
}

// Liga a modulação pendente exatamente numa fronteira de quadro I2S. A ISR pode chegar atrasada
// (seções críticas, ISRs mais prioritárias), então não se supõe a fronteira de meio buffer:
// espera-se o DMA começar um quadro novo e o número desse quadro vira a origem de fase.
// 'boundaryFrame' é o primeiro quadro da metade que o DMA começou a gravar quando a IRQ disparou,
// e audioNextSequence (já atualizado por pushAudioFrames) é o número dele.
// Espera no máximo ~1,25 quadro (~40 us), só quando há partida pendente; o TIM4 está parado.
static void startPendingModulation(uint32_t boundaryFrame) {
  if (!modStartPending) {
    return;
  }
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  // Sai da fronteira atual (de idade desconhecida) e espera a próxima, para a borda ficar no início do quadro.
  while ((i2sDmaHalfwordIndex() % AUDIO_HALFWORDS_PER_FRAME) == 0) {}
  uint32_t idx;
  while (((idx = i2sDmaHalfwordIndex()) % AUDIO_HALFWORDS_PER_FRAME) != 0) {}
  launchModulation();
  uint32_t frame = idx / AUDIO_HALFWORDS_PER_FRAME;
  uint32_t lag = (frame + 2UL * AUDIO_HALF_FRAMES - boundaryFrame) % (2UL * AUDIO_HALF_FRAMES);
  modStartPending = false;
  modMarkerSequence = audioNextSequence + lag;
  modMarkerPending = true;
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
void DMA2_Stream0_IRQHandler(void) {
  HAL_DMA_IRQHandler(&hdmaAdc);
}
void DMA1_Stream3_IRQHandler(void) {
  HAL_DMA_IRQHandler(&hdmaI2s2Rx);
}
}

static void startAdc() {
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_ADC1_CLK_ENABLE();
  __HAL_RCC_DMA2_CLK_ENABLE();
  __HAL_RCC_TIM3_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = GPIO_PIN_0;
  gpio.Mode = GPIO_MODE_ANALOG;
  gpio.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &gpio);

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
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;  // 84/4 = 21 MHz
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

  // OPT101 tem ~15 kOhm de saída: amostragem longa (84 ciclos = 4 us).
  ADC_ChannelConfTypeDef ch = {0};
  ch.Channel = ADC_CHANNEL_0;
  ch.Rank = 1;
  ch.SamplingTime = ADC_SAMPLETIME_84CYCLES;
  HAL_ADC_ConfigChannel(&hadc1, &ch);

  // TIM3 gera TRGO (e pedido de DMA) a cada ADC_RATE_HZ; UG inicial antes de armar os DMAs
  TIM3->PSC = 0;
  TIM3->ARR = TIMER_CLK_HZ / ADC_RATE_HZ - 1;
  TIM3->EGR = TIM_EGR_UG;
  TIM3->SR = 0;

  HAL_ADC_Start_DMA(&hadc1, (uint32_t *)dmaBuf, 2 * HALF_SAMPLES);

  TIM3->CR2 = (TIM3->CR2 & ~TIM_CR2_MMS) | TIM_TRGO_UPDATE;
  TIM3->CR1 |= TIM_CR1_CEN;
}

extern "C" int _write(int, char *, int len) {  // newlib exige; sem printf neste firmware
  return len;
}

// ------------------------------------------------------------------ Main
void setup() {
  pinMode(LASER_PIN, OUTPUT);
  digitalWrite(LASER_PIN, LOW);
  analogWriteResolution(PWM_RESOLUTION_BITS);
  analogWriteFrequency(LASER_PWM_HZ);

  Serial.begin(115200);  // ignorado pelo USB CDC
  analogWrite(LASER_PIN, 1);  // inicializa TIM1/PA8; o duty passa a ser escrito direto em CCR1
  initModulation();
  startAdc();
  audioReady = startAudio(); //entrada de 25 MHz / 25 = 1 MHz, VCO de 258 MHz, I2SCLK de 86 MHz -> 86 MHz / (64 * 42) = 31994 Hz.
}

void loop() {
  receiveCommands();

  if (!Serial) {
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    ringTail = ringHead;
    audioTail = audioHead;
    audioTailSequence = audioNextSequence;
    __set_PRIMASK(primask);
    txLength = 0;
    txOffset = 0;
    return;
  }

  if (txOffset == txLength) {
    txLength = 0;
    txOffset = 0;
    uint16_t length = prepareOpticalFrames(txBuffer);
    length += prepareModMarker(&txBuffer[length]);
    if (audioReady) {
      for (uint32_t i = 0; i < TX_AUDIO_MAX_PACKETS; ++i) {
        uint16_t packet = prepareAudioPacket(&txBuffer[length]);
        if (packet == 0) {
          break;
        }
        length += packet;
      }
    }
    if (length == 0) {
      return;
    }
    txLength = length;
  }
  txOffset += (uint16_t)Serial.write(&txBuffer[txOffset], txLength - txOffset);
}
