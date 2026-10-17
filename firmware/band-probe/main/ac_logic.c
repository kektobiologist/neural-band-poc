#include "ac_logic.h"
#include <string.h>

ac_action_t ac_map_gesture(ac_gesture_filter_t *f, const band_gesture_t *e) {
    if (e->synthetic) return AC_NONE;
    ac_action_t action = AC_NONE;
    // The band emits raw and derived representations. Select exactly one:
    // derived doubleTap for fingers; raw left/right for thumb swipes.
    if (e->derived == 2 && e->action == 0) {
        if (e->finger == 2) action = AC_ON;
        if (e->finger == 3) action = AC_OFF;
    } else if (e->derived == 0 && (e->finger == 1 || e->finger == 4)) {
        if (e->action == 9) action = AC_UP;
        if (e->action == 8) action = AC_DOWN;
    }
    if (action == AC_NONE) return action;
    // Reject duplicate/replayed timestamps; suppress very close same actions.
    // A band timestamp reset is detected and resets the per-action history.
    if (f->seen[action] && e->timestamp_us < f->timestamp[action] &&
        f->timestamp[action] - e->timestamp_us > 10000000ULL)
        memset(f, 0, sizeof(*f));
    if (f->seen[action] && (e->timestamp_us <= f->timestamp[action] ||
        e->timestamp_us - f->timestamp[action] < 300000)) return AC_NONE;
    f->seen[action] = true;
    f->timestamp[action] = e->timestamp_us;
    return action;
}

static unsigned ones(uint8_t value) {
    unsigned n = 0;
    for (; value; value >>= 1) n += value & 1;
    return n;
}

size_t ac_make_frame(bool power, unsigned temp, bool extended, uint8_t out[21]) {
    // Samsung AC wire format and defaults verified against IRremoteESP8266 2.8.6.
    // Checksum nibbles are populated below, not taken from a fixed OFF capture.
    uint8_t first[7] = {0x02, 0x02, 0x00, 0, 0, 0, power ? 0xf0 : 0xc0};
    uint8_t settings[7] = {0x01, 0x02, 0xf0, 0x71, 0, 0x11, power ? 0xf0 : 0xc0};
    const uint8_t timers[7] = {0x01, 0x02, 0x00, 0, 0, 0, 0};
    if (temp < 16) temp = 16;
    if (temp > 30) temp = 30;
    settings[4] = (temp - 16) << 4;
    memcpy(out, first, 7);
    if (extended) memcpy(out + 7, timers, 7);
    memcpy(out + (extended ? 14 : 7), settings, 7);
    size_t length = extended ? 21 : 14;
    for (size_t i = 0; i < length; i += 7) {
        unsigned sum = ones(out[i]) + ones(out[i+1] & 0xf) + ones(out[i+2] & 0xf0);
        for (size_t j = 3; j < 7; j++) sum += ones(out[i+j]);
        uint8_t checksum = (uint8_t)~sum;
        out[i+1] = (out[i+1] & 0xf) | (checksum << 4);
        out[i+2] = (out[i+2] & 0xf0) | (checksum >> 4);
    }
    return length;
}

size_t ac_make_pulses(const uint8_t *frame, size_t bytes, ac_pulse_t out[175]) {
    if (bytes != 14 && bytes != 21) return 0;
    size_t n = 0;
    out[n++] = (ac_pulse_t){690, 17844};
    for (size_t section = 0; section < bytes; section += 7) {
        out[n++] = (ac_pulse_t){3086, 8864};
        for (size_t j = 0; j < 7; j++)
            for (unsigned bit = 0; bit < 8; bit++)
                out[n++] = (ac_pulse_t){586, (frame[section+j] >> bit) & 1 ? 1432 : 436};
        out[n++] = (ac_pulse_t){586, 2886};
    }
    return n;
}
