#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "band_protocol.h"

typedef enum { AC_NONE, AC_ON, AC_OFF, AC_UP, AC_DOWN, AC_TEMP, AC_STATUS, AC_OFF_SINGLE } ac_action_t;
typedef struct { uint64_t timestamp[5]; bool seen[5]; } ac_gesture_filter_t;
ac_action_t ac_map_gesture(ac_gesture_filter_t *filter, const band_gesture_t *event);
// Cool, automatic fan, both swings off; matches the standalone Arduino test.
size_t ac_make_frame(bool power, unsigned temp, bool extended, uint8_t out[21]);
typedef struct { uint16_t mark_us, space_us; } ac_pulse_t;
// Last space excludes the additional 97,114 us inter-message gap.
size_t ac_make_pulses(const uint8_t *frame, size_t bytes, ac_pulse_t out[175]);
