// Interface CDC: comandos do PC (fila de bytes), DTR e envio em transferências longas.
#include "usbd_cdc_if.h"

extern USBD_HandleTypeDef hUsbDeviceFS;

volatile uint8_t cdcHostOpen = 0;

static uint8_t rxPacket[CDC_DATA_FS_OUT_PACKET_SIZE];
static USBD_CDC_LineCodingTypeDef lineCoding = {115200, 0, 0, 8};

#define RX_RING 256U
static volatile uint8_t rxRing[RX_RING];
static volatile uint32_t rxHead = 0, rxTail = 0;

static int8_t CDC_Init_FS(void) {
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, NULL, 0);
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, rxPacket);
  return USBD_OK;
}

static int8_t CDC_DeInit_FS(void) {
  cdcHostOpen = 0;
  return USBD_OK;
}

static int8_t CDC_Control_FS(uint8_t cmd, uint8_t *pbuf, uint16_t length) {
  (void)length;
  switch (cmd) {
    case CDC_SET_LINE_CODING:
      lineCoding.bitrate = (uint32_t)pbuf[0] | ((uint32_t)pbuf[1] << 8) |
                           ((uint32_t)pbuf[2] << 16) | ((uint32_t)pbuf[3] << 24);
      lineCoding.format = pbuf[4];
      lineCoding.paritytype = pbuf[5];
      lineCoding.datatype = pbuf[6];
      break;
    case CDC_GET_LINE_CODING:
      pbuf[0] = (uint8_t)lineCoding.bitrate;
      pbuf[1] = (uint8_t)(lineCoding.bitrate >> 8);
      pbuf[2] = (uint8_t)(lineCoding.bitrate >> 16);
      pbuf[3] = (uint8_t)(lineCoding.bitrate >> 24);
      pbuf[4] = lineCoding.format;
      pbuf[5] = lineCoding.paritytype;
      pbuf[6] = lineCoding.datatype;
      break;
    case CDC_SET_CONTROL_LINE_STATE: {
      // Sem dados, a classe passa o próprio pedido SETUP: wValue bit 0 = DTR.
      USBD_SetupReqTypedef *req = (USBD_SetupReqTypedef *)pbuf;
      cdcHostOpen = (req->wValue & 0x0001U) ? 1U : 0U;
      break;
    }
    default:
      break;
  }
  return USBD_OK;
}

static int8_t CDC_Receive_FS(uint8_t *buf, uint32_t *len) {
  for (uint32_t i = 0; i < *len; i++) {
    uint32_t next = (rxHead + 1U) % RX_RING;
    if (next != rxTail) {
      rxRing[rxHead] = buf[i];
      rxHead = next;
    }
  }
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, rxPacket);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);
  return USBD_OK;
}

static int8_t CDC_TransmitCplt_FS(uint8_t *buf, uint32_t *len, uint8_t epnum) {
  (void)buf; (void)len; (void)epnum;
  return USBD_OK;
}

int cdcReadByte(void) {
  if (rxTail == rxHead) return -1;
  uint8_t c = rxRing[rxTail];
  rxTail = (rxTail + 1U) % RX_RING;
  return c;
}

int cdcTxIdle(void) {
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if (hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED || hcdc == NULL) return 0;
  return *(volatile uint32_t *)&hcdc->TxState == 0U;
}

int cdcTransmit(uint8_t *buf, uint32_t len) {
  if (!cdcTxIdle()) return 0;
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, buf, len);
  return USBD_CDC_TransmitPacket(&hUsbDeviceFS) == USBD_OK;
}

USBD_CDC_ItfTypeDef USBD_Interface_fops_FS = {
  CDC_Init_FS, CDC_DeInit_FS, CDC_Control_FS, CDC_Receive_FS, CDC_TransmitCplt_FS
};
