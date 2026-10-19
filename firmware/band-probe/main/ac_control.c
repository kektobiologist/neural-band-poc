#ifdef BAND_AC_CONTROL
#include "ac_control.h"
#include "ac_logic.h"
#include "driver/gpio.h"
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "band_ac";
static rmt_channel_handle_t tx;
static rmt_encoder_handle_t encoder;
static QueueHandle_t queue;
static atomic_bool busy, armed = true;
static ac_gesture_filter_t filter;
// Only the IR worker owns requested AC settings.
static bool power, known;
static unsigned temperature = 24;
typedef struct { ac_action_t action; unsigned temp; bool gesture; int64_t queued_us; } command_t;

static void status(void) {
    ESP_LOGI(TAG, "AC requested=%s temp=%uC cool/auto/swing-off gestures=%s (no appliance feedback)",
             known ? (power ? "ON" : "OFF") : "UNKNOWN", temperature,
             atomic_load(&armed) ? "ON" : "OFF");
}

static bool emit(bool on, bool extended) {
    uint8_t frame[21];
    ac_pulse_t pulses[175];
    rmt_symbol_word_t symbols[175];
    size_t length = ac_make_frame(on, temperature, extended, frame);
    size_t count = ac_make_pulses(frame, length, pulses);
    for (size_t i = 0; i < count; i++) {
        symbols[i] = (rmt_symbol_word_t){.level0=1, .duration0=pulses[i].mark_us,
                                       .level1=0, .duration1=pulses[i].space_us};
    }
    rmt_transmit_config_t cfg = {.loop_count=0, .flags.eot_level=0};
    esp_err_t err = rmt_transmit(tx, encoder, symbols, count * sizeof(*symbols), &cfg);
    if (err == ESP_OK) err = rmt_tx_wait_all_done(tx, 2000);
    // On a driver failure, restart rather than reuse an in-flight stack buffer.
    ESP_ERROR_CHECK(err);
    // Match the library's 100 ms final gap (2,886 us already in the last symbol).
    vTaskDelay(pdMS_TO_TICKS(98));
    power = on;
    known = true;
    ESP_LOGI(TAG, "IR SENT %s temp=%u bytes=%u GPIO4 carrier=38000Hz", on ? "ON" : "OFF",
             temperature, (unsigned)length);
    return true;
}

static void worker(void *arg) {
    command_t c;
    for (;;) {
        xQueueReceive(queue, &c, portMAX_DELAY);
        if (c.gesture && (!atomic_load(&armed) || esp_timer_get_time() - c.queued_us > 1500000)) {
            ESP_LOGW(TAG, "Dropped disabled/stale gesture");
        } else if (c.action == AC_STATUS) {
            status();
        } else if (c.action == AC_ON) {
            emit(true, true);
        } else if (c.action == AC_OFF_SINGLE) {
            emit(false, true);
        } else if (c.action == AC_OFF) {
            ESP_LOGI(TAG, "SHUTDOWN OFF -> ON -> OFF; 1 second gaps");
            emit(false, true);
            vTaskDelay(pdMS_TO_TICKS(1000));
            emit(true, true);
            vTaskDelay(pdMS_TO_TICKS(1000));
            emit(false, true);
            ESP_LOGI(TAG, "SHUTDOWN sequence complete");
        } else {
            int next = c.action == AC_TEMP ? (int)c.temp :
                       (int)temperature + (c.action == AC_UP ? 1 : -1);
            if (!known || !power) ESP_LOGW(TAG, "Temperature ignored: send ON first");
            else if (next < 16 || next > 30) ESP_LOGW(TAG, "Temperature limit 16..30 C; nothing sent");
            else { temperature = (unsigned)next; emit(true, false); }
        }
        atomic_store(&busy, false);
    }
}

static void submit(ac_action_t action, unsigned temp, bool gesture) {
    if (atomic_exchange(&busy, true)) {
        ESP_LOGW(TAG, "AC BUSY: command dropped; retry after IR sequence finishes");
        return;
    }
    command_t c = {action, temp, gesture, esp_timer_get_time()};
    if (xQueueSend(queue, &c, 0) != pdTRUE) {
        atomic_store(&busy, false);
        ESP_LOGE(TAG, "AC command queue full");
    }
}

void ac_control_gesture(const band_gesture_t *event) {
    // TODO: Implement band-ac idle standby and wake handling per ../STANDBY.md.
    // Schedule acknowledged device-state RPCs on the BLE context (1 standby,
    // 2 active), keeping the gesture-only subscription. The wake middle double
    // tap is consumed by the band; never synthesize it as AC_OFF or re-arm
    // disabled controls. Preserve deduplication and any running IR sequence.
    ac_action_t action = ac_map_gesture(&filter, event);
    if (action == AC_NONE || !atomic_load(&armed)) return;
    const char *names[] = {"NONE", "ON", "OFF", "TEMP_UP", "TEMP_DOWN"};
    ESP_LOGI(TAG, "BAND -> AC %s", names[action]);
    submit(action, 0, true);
}

bool ac_control_command(const char *line) {
    if (!strcmp(line, "gestures on") || !strcmp(line, "gestures off")) {
        bool enable = !strcmp(line, "gestures on");
        atomic_store(&armed, enable);
        ESP_LOGI(TAG, "Gesture AC control %s; any running shutdown will finish", enable ? "ON" : "OFF");
    } else if (!strcmp(line, "on")) submit(AC_ON, 0, false);
    else if (!strcmp(line, "off")) submit(AC_OFF, 0, false);
    else if (!strcmp(line, "off single")) submit(AC_OFF_SINGLE, 0, false);
    else if (!strcmp(line, "up") || !strcmp(line, "+")) submit(AC_UP, 0, false);
    else if (!strcmp(line, "down") || !strcmp(line, "-")) submit(AC_DOWN, 0, false);
    else if (!strcmp(line, "status")) submit(AC_STATUS, 0, false);
    else if (!strncmp(line, "temp ", 5)) {
        char *end;
        long temp = strtol(line + 5, &end, 10);
        if (end == line+5 || *end || temp < 16 || temp > 30)
            ESP_LOGW(TAG, "Use temp 16..30");
        else submit(AC_TEMP, (unsigned)temp, false);
    } else if (!strcmp(line, "help")) {
        ESP_LOGI(TAG, "AC: on, off (OFF/ON/OFF), off single, up, down, temp 16..30, status, gestures on/off");
        ESP_LOGI(TAG, "Mapping: index double-tap ON; middle double-tap OFF; thumb right +1C / left -1C");
        ESP_LOGI(TAG, "Band: battery. Receiver capture is available in the separate ac-ir-test firmware.");
    } else return false;
    return true;
}

void ac_control_init(void) {
    gpio_set_level(GPIO_NUM_4, 0);
    gpio_set_direction(GPIO_NUM_4, GPIO_MODE_OUTPUT);
    rmt_tx_channel_config_t config = {
        .gpio_num = GPIO_NUM_4, .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 1000000, .mem_block_symbols = 192, .trans_queue_depth = 1,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&config, &tx));
    rmt_carrier_config_t carrier = {.frequency_hz=38000, .duty_cycle=0.5};
    ESP_ERROR_CHECK(rmt_apply_carrier(tx, &carrier));
    rmt_copy_encoder_config_t copy = {};
    ESP_ERROR_CHECK(rmt_new_copy_encoder(&copy, &encoder));
    ESP_ERROR_CHECK(rmt_enable(tx));
    queue = xQueueCreate(1, sizeof(command_t));
    assert(queue);
    assert(xTaskCreate(worker, "ac_ir", 6144, NULL, 4, NULL) == pdPASS);
    band_protocol_set_gesture_handler(ac_control_gesture);
    ESP_LOGI(TAG, "BAND + AC READY: GPIO4 hardware IR; no transmission on boot/connect");
    ac_control_command("help");
}
#endif
