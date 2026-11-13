// Ligação entre a biblioteca USB Device da ST e o driver PCD do HAL (USB OTG FS do STM32F401).
#include "usbd_core.h"
#include "usbd_cdc.h"
#include "stm32f4xx_hal.h"

PCD_HandleTypeDef hpcd_USB_OTG_FS;

static USBD_StatusTypeDef toUsbd(HAL_StatusTypeDef s) {
  switch (s) {
    case HAL_OK: return USBD_OK;
    case HAL_BUSY: return USBD_BUSY;
    default: return USBD_FAIL;
  }
}

void HAL_PCD_MspInit(PCD_HandleTypeDef *hpcd) {
  if (hpcd->Instance != USB_OTG_FS) return;
  __HAL_RCC_GPIOA_CLK_ENABLE();
  GPIO_InitTypeDef g = {0};
  g.Pin = GPIO_PIN_11 | GPIO_PIN_12;   // PA11 = DM, PA12 = DP
  g.Mode = GPIO_MODE_AF_PP;
  g.Pull = GPIO_NOPULL;
  g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  g.Alternate = GPIO_AF10_OTG_FS;
  HAL_GPIO_Init(GPIOA, &g);
  __HAL_RCC_USB_OTG_FS_CLK_ENABLE();
  HAL_NVIC_SetPriority(OTG_FS_IRQn, 3, 0);   // abaixo do TIM4 (0), ADC (1) e I2S (2)
  HAL_NVIC_EnableIRQ(OTG_FS_IRQn);
}

void HAL_PCD_MspDeInit(PCD_HandleTypeDef *hpcd) {
  if (hpcd->Instance != USB_OTG_FS) return;
  __HAL_RCC_USB_OTG_FS_CLK_DISABLE();
  HAL_GPIO_DeInit(GPIOA, GPIO_PIN_11 | GPIO_PIN_12);
  HAL_NVIC_DisableIRQ(OTG_FS_IRQn);
}

void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_SetupStage((USBD_HandleTypeDef *)hpcd->pData, (uint8_t *)hpcd->Setup);
}
void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
  USBD_LL_DataOutStage((USBD_HandleTypeDef *)hpcd->pData, epnum, hpcd->OUT_ep[epnum].xfer_buff);
}
void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
  USBD_LL_DataInStage((USBD_HandleTypeDef *)hpcd->pData, epnum, hpcd->IN_ep[epnum].xfer_buff);
}
void HAL_PCD_SOFCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_SOF((USBD_HandleTypeDef *)hpcd->pData);
}
void HAL_PCD_ResetCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_SetSpeed((USBD_HandleTypeDef *)hpcd->pData, USBD_SPEED_FULL);
  USBD_LL_Reset((USBD_HandleTypeDef *)hpcd->pData);
}
void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_Suspend((USBD_HandleTypeDef *)hpcd->pData);
}
void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_Resume((USBD_HandleTypeDef *)hpcd->pData);
}
void HAL_PCD_ISOOUTIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
  USBD_LL_IsoOUTIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}
void HAL_PCD_ISOINIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
  USBD_LL_IsoINIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}
void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_DevConnected((USBD_HandleTypeDef *)hpcd->pData);
}
void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *hpcd) {
  USBD_LL_DevDisconnected((USBD_HandleTypeDef *)hpcd->pData);
}

USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *pdev) {
  hpcd_USB_OTG_FS.pData = pdev;
  pdev->pData = &hpcd_USB_OTG_FS;
  hpcd_USB_OTG_FS.Instance = USB_OTG_FS;
  hpcd_USB_OTG_FS.Init.dev_endpoints = 4;
  hpcd_USB_OTG_FS.Init.speed = PCD_SPEED_FULL;
  hpcd_USB_OTG_FS.Init.dma_enable = DISABLE;
  hpcd_USB_OTG_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
  hpcd_USB_OTG_FS.Init.Sof_enable = DISABLE;
  hpcd_USB_OTG_FS.Init.low_power_enable = DISABLE;
  hpcd_USB_OTG_FS.Init.lpm_enable = DISABLE;
  hpcd_USB_OTG_FS.Init.vbus_sensing_enable = DISABLE;   // a Black Pill não liga VBUS no PA9
  hpcd_USB_OTG_FS.Init.use_dedicated_ep1 = DISABLE;
  if (HAL_PCD_Init(&hpcd_USB_OTG_FS) != HAL_OK) return USBD_FAIL;
  // FIFO de 1,25 kB (320 palavras): RX 128, EP0 32, EP1 (dados) 144 = 9 pacotes, EP2 (notificação) 16.
  HAL_PCDEx_SetRxFiFo(&hpcd_USB_OTG_FS, 0x80);
  HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_FS, 0, 0x20);
  HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_FS, 1, 0x90);
  HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_FS, 2, 0x10);
  return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *pdev) {
  return toUsbd(HAL_PCD_DeInit((PCD_HandleTypeDef *)pdev->pData));
}
USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *pdev) {
  return toUsbd(HAL_PCD_Start((PCD_HandleTypeDef *)pdev->pData));
}
USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *pdev) {
  return toUsbd(HAL_PCD_Stop((PCD_HandleTypeDef *)pdev->pData));
}
USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t ep_type, uint16_t ep_mps) {
  return toUsbd(HAL_PCD_EP_Open((PCD_HandleTypeDef *)pdev->pData, ep_addr, ep_mps, ep_type));
}
USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  return toUsbd(HAL_PCD_EP_Close((PCD_HandleTypeDef *)pdev->pData, ep_addr));
}
USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  return toUsbd(HAL_PCD_EP_Flush((PCD_HandleTypeDef *)pdev->pData, ep_addr));
}
USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  return toUsbd(HAL_PCD_EP_SetStall((PCD_HandleTypeDef *)pdev->pData, ep_addr));
}
USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  return toUsbd(HAL_PCD_EP_ClrStall((PCD_HandleTypeDef *)pdev->pData, ep_addr));
}
uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  PCD_HandleTypeDef *hpcd = (PCD_HandleTypeDef *)pdev->pData;
  if ((ep_addr & 0x80U) == 0x80U) return hpcd->IN_ep[ep_addr & 0x7FU].is_stall;
  return hpcd->OUT_ep[ep_addr & 0x7FU].is_stall;
}
USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *pdev, uint8_t dev_addr) {
  return toUsbd(HAL_PCD_SetAddress((PCD_HandleTypeDef *)pdev->pData, dev_addr));
}
USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t *pbuf, uint32_t size) {
  return toUsbd(HAL_PCD_EP_Transmit((PCD_HandleTypeDef *)pdev->pData, ep_addr, pbuf, size));
}
USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t *pbuf, uint32_t size) {
  return toUsbd(HAL_PCD_EP_Receive((PCD_HandleTypeDef *)pdev->pData, ep_addr, pbuf, size));
}
uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *pdev, uint8_t ep_addr) {
  return HAL_PCD_EP_GetRxCount((PCD_HandleTypeDef *)pdev->pData, ep_addr);
}
void USBD_LL_Delay(uint32_t delay) {
  HAL_Delay(delay);
}

void *USBD_static_malloc(uint32_t size) {
  (void)size;
  static uint32_t mem[(sizeof(USBD_CDC_HandleTypeDef) / 4U) + 1U];
  return mem;
}
void USBD_static_free(void *p) {
  (void)p;
}
