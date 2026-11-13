#include "stm32f4xx_hal.h"

extern PCD_HandleTypeDef hpcd_USB_OTG_FS;
extern DMA_HandleTypeDef hdmaAdc;
extern DMA_HandleTypeDef hdmaI2s2Rx;
void modulationToggle(void);

void SysTick_Handler(void) { HAL_IncTick(); }
void OTG_FS_IRQHandler(void) { HAL_PCD_IRQHandler(&hpcd_USB_OTG_FS); }
void DMA2_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&hdmaAdc); }
void DMA1_Stream3_IRQHandler(void) { HAL_DMA_IRQHandler(&hdmaI2s2Rx); }

// TIM4: meio período da onda quadrada do laser.
void TIM4_IRQHandler(void) {
  if (TIM4->SR & TIM_SR_UIF) {
    TIM4->SR = ~TIM_SR_UIF;
    modulationToggle();
  }
}

void HardFault_Handler(void) { while (1) {} }
