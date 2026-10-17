#pragma once
#include <stdbool.h>
#include "band_protocol.h"
void ac_control_init(void);
void ac_control_gesture(const band_gesture_t *event);
bool ac_control_command(const char *line);
