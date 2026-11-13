#ifndef USBD_CDC_IF_H
#define USBD_CDC_IF_H

#include "usbd_cdc.h"

extern USBD_CDC_ItfTypeDef USBD_Interface_fops_FS;

// 1 enquanto o programa no PC mantém a porta aberta (DTR alto).
extern volatile uint8_t cdcHostOpen;

// Próximo byte recebido do PC, ou -1 se não houver.
int cdcReadByte(void);

// 1 se o USB está configurado e livre para uma nova transferência.
int cdcTxIdle(void);

// Envia 'len' bytes de 'buf' numa transferência (o buffer deve ficar intacto até cdcTxIdle()).
int cdcTransmit(uint8_t *buf, uint32_t len);

#endif
