/* Standalone BLE/L2CAP band gesture monitor. No appliance GPIOs. */
#include "band_protocol.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_system.h"
#include "host/ble_hs.h"
#include "host/ble_l2cap.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nvs_flash.h"
#include <stdio.h>
#include <string.h>

#define MTU 512
#define BLOCK_SIZE 600
#define BLOCK_COUNT 8
static const char *TAG = "band_probe";
static uint8_t own_addr_type;
static uint16_t connection = BLE_HS_CONN_HANDLE_NONE;
static uint16_t svc_start, svc_end, psm_handle;
static unsigned candidates;
static ble_addr_t candidate;
static struct ble_npl_callout deadline;
static os_membuf_t pool_memory[OS_MEMPOOL_SIZE(BLOCK_COUNT, BLOCK_SIZE)];
static struct os_mempool mempool;
static struct os_mbuf_pool mbuf_pool;
static struct ble_l2cap_chan *channel;
static struct ble_npl_callout retry;
static bool tx_stalled;
static unsigned handshake_ticks;
static uint16_t peer_mtu;
#define TX_COUNT 16
static struct {
    uint8_t data[512];
    size_t len;
} tx[TX_COUNT];
static unsigned tx_head, tx_count;
static void scan(void);
static void drop(const char *reason) {
    ESP_LOGE(TAG, "%s; disconnecting", reason);
    if (connection != BLE_HS_CONN_HANDLE_NONE)
        ble_gap_terminate(connection, BLE_ERR_REM_USER_CONN_TERM);
}
static bool enqueue(const uint8_t *data, size_t len) {
    if (!channel || !peer_mtu)
        return false;
    size_t chunk = peer_mtu < sizeof(tx[0].data) ? peer_mtu : sizeof(tx[0].data);
    if ((len + chunk - 1) / chunk > TX_COUNT - tx_count)
        return false;
    while (len) {
        size_t n = len < chunk ? len : chunk;
        unsigned i = (tx_head + tx_count) % TX_COUNT;
        memcpy(tx[i].data, data, n);
        tx[i].len = n;
        tx_count++;
        data += n;
        len -= n;
    }
    return true;
}
static void pump(void) {
    while (channel && !tx_stalled && tx_count) {
        struct os_mbuf *buf = os_mbuf_get_pkthdr(&mbuf_pool, 0);
        if (!buf) {
            drop("TX buffer exhausted");
            return;
        }
        int rc = os_mbuf_append(buf, tx[tx_head].data, tx[tx_head].len);
        if (rc) {
            os_mbuf_free_chain(buf);
            drop("TX append failed");
            return;
        }
        rc = ble_l2cap_send(channel, buf);
        if (rc == BLE_HS_EBUSY || rc == BLE_HS_EBADDATA)
            os_mbuf_free_chain(buf);
        if (rc && rc != BLE_HS_ESTALLED) {
            drop("L2CAP send failed");
            return;
        }
        tx_head = (tx_head + 1) % TX_COUNT;
        tx_count--;
        if (rc == BLE_HS_ESTALLED)
            tx_stalled = true;
    }
}
static bool security_attempted;
void ble_store_config_init(void);
static int gap_event(struct ble_gap_event *event, void *arg);

static void finish(struct ble_npl_event *event) {
    if (band_protocol_streaming()) {
        ESP_LOGI(TAG, "STREAMING gestures=%lu authenticated_packets=%lu - waiting for your gestures",
                 (unsigned long)band_protocol_gestures(), (unsigned long)band_protocol_packets());
    } else if (++handshake_ticks >= 9) {
        drop("Handshake timed out");
        if (connection == BLE_HS_CONN_HANDLE_NONE)
            ble_gap_conn_cancel();
        return;
    }
    ble_npl_callout_reset(&deadline, ble_npl_time_ms_to_ticks32(5000));
}
static void retry_scan(struct ble_npl_event *event) { scan(); }
static int coc_event(struct ble_l2cap_event *event, void *arg) {
    switch (event->type) {
    case BLE_L2CAP_EVENT_COC_CONNECTED: {
        ESP_LOGI(TAG, "L2CAP_CONNECT status=%d", event->connect.status);
        if (event->connect.status) {
            drop("L2CAP connection failed");
            break;
        }
        struct ble_l2cap_chan_info info;
        int rc = ble_l2cap_get_chan_info(event->connect.chan, &info);
        if (rc) {
            ESP_LOGE(TAG, "CHANNEL_INFO_ERROR rc=%d", rc);
            break;
        }
        ESP_LOGI(TAG, "L2CAP_OPEN psm=%u local_mtu=%u peer_mtu=%u", info.psm, info.our_coc_mtu,
                 info.peer_coc_mtu);
        channel = event->connect.chan;
        peer_mtu = info.peer_coc_mtu;
        if (!band_protocol_start(enqueue)) {
            drop(band_protocol_error());
            break;
        }
        pump();
        break;
    }
    case BLE_L2CAP_EVENT_COC_DATA_RECEIVED: {
        struct os_mbuf *rx = event->receive.sdu_rx;
        uint16_t len = OS_MBUF_PKTLEN(rx);
        uint8_t incoming[MTU];
        bool valid = len <= sizeof(incoming) && os_mbuf_copydata(rx, 0, len, incoming) == 0;
        os_mbuf_free_chain(rx);
        struct os_mbuf *next = os_mbuf_get_pkthdr(&mbuf_pool, 0);
        if (!next) {
            drop("RX buffer exhausted");
            break;
        }
        int rc = ble_l2cap_recv_ready(event->receive.chan, next);
        if (rc) {
            if (rc == BLE_HS_EBUSY || rc == BLE_HS_EINVAL)
                os_mbuf_free_chain(next);
            drop("Cannot rearm L2CAP receive");
            break;
        }
        if (!valid || !band_protocol_feed(incoming, len)) {
            drop(valid ? band_protocol_error() : "Invalid L2CAP SDU");
            break;
        }
        pump();
        break;
    }
    case BLE_L2CAP_EVENT_COC_TX_UNSTALLED:
        if (event->tx_unstalled.status) {
            drop("L2CAP stalled TX failed");
            break;
        }
        tx_stalled = false;
        pump();
        break;
    case BLE_L2CAP_EVENT_COC_DISCONNECTED:
        channel = NULL;
        ESP_LOGI(TAG, "L2CAP_CLOSED");
        break;
    default:
        break;
    }
    return 0;
}
static int psm_read(uint16_t conn, const struct ble_gatt_error *error, struct ble_gatt_attr *attr,
                    void *arg) {
    if (error->status) {
        ESP_LOGE(TAG, "PSM_READ_ERROR status=%d", error->status);
        if (!security_attempted && (error->status == BLE_HS_ATT_ERR(BLE_ATT_ERR_INSUFFICIENT_AUTHEN) ||
                                    error->status == BLE_HS_ATT_ERR(BLE_ATT_ERR_INSUFFICIENT_ENC))) {
            security_attempted = true;
            int rc = ble_gap_security_initiate(conn);
            ESP_LOGI(TAG, "BLE_SECURITY_STARTED rc=%d", rc);
        }
        return 0;
    }
    uint8_t value[2];
    if (!attr || OS_MBUF_PKTLEN(attr->om) != 2 || os_mbuf_copydata(attr->om, 0, 2, value)) {
        ESP_LOGE(TAG, "PSM_INVALID_LENGTH");
        return 0;
    }
    uint16_t psm = value[0] | ((uint16_t)value[1] << 8);
    ESP_LOGI(TAG, "PSM_READ value=%u", psm);
    struct os_mbuf *rx = os_mbuf_get_pkthdr(&mbuf_pool, 0);
    if (!rx) {
        ESP_LOGE(TAG, "L2CAP_ALLOC_ERROR");
        return 0;
    }
    int rc = ble_l2cap_connect(conn, psm, MTU, rx, coc_event, NULL);
    // IDF 5.5 consumes/frees rx on some immediate failure paths, but not all.
    // On an immediate error restart to reclaim buffers with ambiguous SDK ownership.
    // The BLE bond remains in NVS; no keys or enrollment are erased.
    ESP_LOGI(TAG, "L2CAP_CONNECT_STARTED rc=%d", rc);
    if (rc)
        esp_restart();
    return 0;
}
static int characteristic(uint16_t conn, const struct ble_gatt_error *error, const struct ble_gatt_chr *chr,
                          void *arg) {
    if (!error->status && chr) {
        psm_handle = chr->val_handle;
        ESP_LOGI(TAG, "PSM_CHARACTERISTIC handle=%u", psm_handle);
    } else if (error->status == BLE_HS_EDONE && psm_handle) {
        int rc = ble_gattc_read(conn, psm_handle, psm_read, NULL);
        ESP_LOGI(TAG, "PSM_READ_STARTED rc=%d", rc);
    } else
        ESP_LOGW(TAG, "CHAR_DISCOVERY status=%d handle=%u", error->status, psm_handle);
    return 0;
}
static int service(uint16_t conn, const struct ble_gatt_error *error, const struct ble_gatt_svc *svc,
                   void *arg) {
    if (!error->status && svc) {
        svc_start = svc->start_handle;
        svc_end = svc->end_handle;
        ESP_LOGI(TAG, "BAND_SERVICE start=%u end=%u", svc_start, svc_end);
    } else if (error->status == BLE_HS_EDONE && svc_start) {
        const ble_uuid128_t uuid = BLE_UUID128_INIT(0x1a, 0xcc, 0xf8, 0x1d, 0xe0, 0xe2, 0x4e, 0xb3, 0xaa,
                                                    0x42, 0xb6, 0x82, 0x7c, 0xda, 0x41, 0x2d);
        int rc = ble_gattc_disc_chrs_by_uuid(conn, svc_start, svc_end, &uuid.u, characteristic, NULL);
        ESP_LOGI(TAG, "CHAR_DISCOVERY_STARTED rc=%d", rc);
    } else
        ESP_LOGW(TAG, "SERVICE_DISCOVERY status=%d start=%u", error->status, svc_start);
    return 0;
}
static int gap_event(struct ble_gap_event *event, void *arg) {
    switch (event->type) {
    case BLE_GAP_EVENT_DISC: {
        struct ble_hs_adv_fields f;
        if (ble_hs_adv_parse_fields(&f, event->disc.data, event->disc.length_data))
            break;
        bool named = f.name_len >= 9 && !memcmp(f.name, "Meta Band", 9);
        bool fd5f = false;
        for (int i = 0; i < f.num_uuids16; i++)
            if (f.uuids16[i].value == 0xfd5f)
                fd5f = true;
        const uint8_t hint[] = {0xab, 0x01, 0x80, 0x01, 0x06};
        bool unnamed =
            !f.name_len && fd5f && f.mfg_data_len >= sizeof(hint) && !memcmp(f.mfg_data, hint, sizeof(hint));
        if (!named && !unnamed)
            break;
        if (event->disc.event_type != BLE_HCI_ADV_RPT_EVTYPE_ADV_IND &&
            event->disc.event_type != BLE_HCI_ADV_RPT_EVTYPE_SCAN_RSP)
            break;
        if (!candidates || memcmp(&candidate, &event->disc.addr, sizeof(candidate))) {
            candidates++;
            candidate = event->disc.addr;
            ESP_LOGI(TAG, "BAND_CANDIDATE name=%.*s addr=%02x:%02x:%02x:%02x:%02x:%02x type=%u rssi=%d",
                     f.name_len, f.name ? (char *)f.name : "", candidate.val[5], candidate.val[4],
                     candidate.val[3], candidate.val[2], candidate.val[1], candidate.val[0], candidate.type,
                     event->disc.rssi);
        }
        break;
    }
    case BLE_GAP_EVENT_DISC_COMPLETE: {
        ESP_LOGI(TAG, "SCAN_COMPLETE candidates=%u", candidates);
        if (candidates != 1) {
            ESP_LOGW(TAG, "Need exactly one band candidate; rescanning in 5 seconds");
            ble_npl_callout_reset(&retry, ble_npl_time_ms_to_ticks32(5000));
            break;
        }
        int rc = ble_gap_connect(own_addr_type, &candidate, 15000, NULL, gap_event, NULL);
        ESP_LOGI(TAG, "BLE_CONNECT_STARTED rc=%d", rc);
        if (rc) {
            ble_npl_callout_reset(&retry, ble_npl_time_ms_to_ticks32(5000));
            break;
        }
        ble_npl_callout_reset(&deadline, ble_npl_time_ms_to_ticks32(5000));
        break;
    }
    case BLE_GAP_EVENT_CONNECT: {
        ESP_LOGI(TAG, "BLE_CONNECT status=%d", event->connect.status);
        if (event->connect.status) {
            ble_npl_callout_stop(&deadline);
            ble_npl_callout_reset(&retry, ble_npl_time_ms_to_ticks32(5000));
            break;
        }
        connection = event->connect.conn_handle;
        const ble_uuid16_t uuid = BLE_UUID16_INIT(0xfeb8);
        int rc = ble_gattc_disc_svc_by_uuid(connection, &uuid.u, service, NULL);
        ESP_LOGI(TAG, "SERVICE_DISCOVERY_STARTED rc=%d", rc);
        break;
    }
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        int rc = ble_gap_conn_find(event->enc_change.conn_handle, &desc);
        ESP_LOGI(TAG, "BLE_ENCRYPTION status=%d encrypted=%d bonded=%d", event->enc_change.status,
                 rc ? -1 : desc.sec_state.encrypted, rc ? -1 : desc.sec_state.bonded);
        if (!event->enc_change.status && !rc && desc.sec_state.encrypted && psm_handle) {
            rc = ble_gattc_read(connection, psm_handle, psm_read, NULL);
            ESP_LOGI(TAG, "PSM_READ_RETRY rc=%d", rc);
        }
        break;
    }
    case BLE_GAP_EVENT_PASSKEY_ACTION:
        ESP_LOGW(TAG, "PASSKEY_ACTION_REQUIRED action=%u", event->passkey.params.action);
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "BLE_DISCONNECTED reason=%d", event->disconnect.reason);
        connection = BLE_HS_CONN_HANDLE_NONE;
        ble_npl_callout_stop(&deadline);
        channel = NULL;
        tx_count = tx_head = 0;
        tx_stalled = false;
        bool protocol_failed = band_protocol_error() != NULL;
        band_protocol_close();
        if (protocol_failed)
            ESP_LOGE(TAG, "Protocol failure; press RESET after correcting the cause");
        else
            ble_npl_callout_reset(&retry, ble_npl_time_ms_to_ticks32(5000));
        break;
    default:
        break;
    }
    return 0;
}
static void scan(void) {
    candidates = 0;
    svc_start = svc_end = psm_handle = 0;
    security_attempted = false;
    handshake_ticks = 0;
    struct ble_gap_disc_params params = {.itvl = 0x50, .window = 0x30, .filter_duplicates = 1, .passive = 0};
    int rc = ble_gap_disc(own_addr_type, 5000, &params, gap_event, NULL);
    ESP_LOGI(TAG, "Scanning for band (5 seconds), rc=%d", rc);
    if (rc)
        ble_npl_callout_reset(&retry, ble_npl_time_ms_to_ticks32(5000));
}
static void sync_host(void) {
    int rc = ble_hs_util_ensure_addr(0);
    if (!rc)
        rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc) {
        ESP_LOGE(TAG, "ADDRESS_ERROR rc=%d", rc);
        return;
    }
    scan();
}
static void reset_host(int reason) { ESP_LOGE(TAG, "HOST_RESET reason=%d", reason); }
static void host_task(void *param) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}
void app_main(void) {
    ESP_LOGI(TAG, "BAND GESTURE MONITOR: connect -> authenticate -> live gestures at 115200 baud");
    ESP_ERROR_CHECK(nvs_flash_init());
    assert(os_mempool_init(&mempool, BLOCK_COUNT, BLOCK_SIZE, pool_memory, "coc") == 0);
    assert(os_mbuf_pool_init(&mbuf_pool, &mempool, BLOCK_SIZE, BLOCK_COUNT) == 0);
    esp_log_level_set("NimBLE", ESP_LOG_WARN);
    ESP_ERROR_CHECK(nimble_port_init());
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_NO_INPUT_OUTPUT;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_sc = 1;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_store_config_init();
    ble_hs_cfg.sync_cb = sync_host;
    ble_hs_cfg.reset_cb = reset_host;
    ble_npl_callout_init(&deadline, nimble_port_get_dflt_eventq(), finish, NULL);
    ble_npl_callout_init(&retry, nimble_port_get_dflt_eventq(), retry_scan, NULL);
    nimble_port_freertos_init(host_task);
}
