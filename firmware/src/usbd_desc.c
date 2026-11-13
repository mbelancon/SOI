// Descritores USB. VID/PID iguais aos do firmware SOI atual (0483:5740, porta COM padrão da ST).
#include "usbd_core.h"
#include "usbd_desc.h"
#include "usbd_conf.h"
#include "usbd_ctlreq.h"

#define USBD_VID               0x0483U
#define USBD_PID_FS            0x5740U
#define USBD_LANGID_STRING     1033U
#define USBD_MANUFACTURER_STRING "LCTM"
#define USBD_PRODUCT_STRING    "SOI OPT101/INMP441 (STM32F401)"
#define USBD_CONFIGURATION_STRING "CDC Config"
#define USBD_INTERFACE_STRING  "CDC Interface"
#define USB_SIZ_STRING_SERIAL  0x1AU

static uint8_t *DeviceDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *LangIDStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *ManufacturerStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *ProductStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *SerialStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *ConfigStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);
static uint8_t *InterfaceStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length);

USBD_DescriptorsTypeDef FS_Desc = {
  DeviceDescriptor, LangIDStrDescriptor, ManufacturerStrDescriptor, ProductStrDescriptor,
  SerialStrDescriptor, ConfigStrDescriptor, InterfaceStrDescriptor
};

__ALIGN_BEGIN static uint8_t deviceDesc[USB_LEN_DEV_DESC] __ALIGN_END = {
  0x12, USB_DESC_TYPE_DEVICE, 0x00, 0x02,
  0x02, 0x02, 0x00,                 // classe CDC
  USB_MAX_EP0_SIZE,
  LOBYTE(USBD_VID), HIBYTE(USBD_VID), LOBYTE(USBD_PID_FS), HIBYTE(USBD_PID_FS),
  0x00, 0x02,
  USBD_IDX_MFC_STR, USBD_IDX_PRODUCT_STR, USBD_IDX_SERIAL_STR,
  USBD_MAX_NUM_CONFIGURATION
};

__ALIGN_BEGIN static uint8_t langIdDesc[USB_LEN_LANGID_STR_DESC] __ALIGN_END = {
  USB_LEN_LANGID_STR_DESC, USB_DESC_TYPE_STRING, LOBYTE(USBD_LANGID_STRING), HIBYTE(USBD_LANGID_STRING)
};

__ALIGN_BEGIN static uint8_t strDesc[USBD_MAX_STR_DESC_SIZ] __ALIGN_END;
__ALIGN_BEGIN static uint8_t serialDesc[USB_SIZ_STRING_SERIAL] __ALIGN_END = {
  USB_SIZ_STRING_SERIAL, USB_DESC_TYPE_STRING
};

static uint8_t *DeviceDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  *length = sizeof(deviceDesc);
  return deviceDesc;
}

static uint8_t *LangIDStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  *length = sizeof(langIdDesc);
  return langIdDesc;
}

static uint8_t *ManufacturerStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  USBD_GetString((uint8_t *)USBD_MANUFACTURER_STRING, strDesc, length);
  return strDesc;
}

static uint8_t *ProductStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  USBD_GetString((uint8_t *)USBD_PRODUCT_STRING, strDesc, length);
  return strDesc;
}

static uint8_t *ConfigStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  USBD_GetString((uint8_t *)USBD_CONFIGURATION_STRING, strDesc, length);
  return strDesc;
}

static uint8_t *InterfaceStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  USBD_GetString((uint8_t *)USBD_INTERFACE_STRING, strDesc, length);
  return strDesc;
}

// Número de série a partir do ID único do chip (12 dígitos hexadecimais).
static void intToUnicode(uint32_t value, uint8_t *pbuf, uint8_t len) {
  for (uint8_t idx = 0; idx < len; idx++) {
    uint8_t nibble = (uint8_t)(value >> 28);
    pbuf[2U * idx] = (nibble < 10U) ? (uint8_t)('0' + nibble) : (uint8_t)('A' + nibble - 10U);
    pbuf[2U * idx + 1U] = 0;
    value <<= 4;
  }
}

static uint8_t *SerialStrDescriptor(USBD_SpeedTypeDef speed, uint16_t *length) {
  (void)speed;
  uint32_t id0 = *(uint32_t *)(UID_BASE);
  uint32_t id1 = *(uint32_t *)(UID_BASE + 4U);
  uint32_t id2 = *(uint32_t *)(UID_BASE + 8U);
  id0 += id2;
  intToUnicode(id0, &serialDesc[2], 8);
  intToUnicode(id1, &serialDesc[18], 4);
  *length = USB_SIZ_STRING_SERIAL;
  return serialDesc;
}
