#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef bool (*band_send_fn)(const uint8_t *, size_t);
bool band_protocol_start(band_send_fn send);
bool band_protocol_feed(const uint8_t *data, size_t len);
void band_protocol_close(void);
bool band_protocol_streaming(void);
uint32_t band_protocol_gestures(void);
uint32_t band_protocol_packets(void);
const char *band_protocol_error(void);
