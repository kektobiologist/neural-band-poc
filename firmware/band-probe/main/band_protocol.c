/* Port of the repo's verified AirShield, OwnerTrust and InputService subset. */
#include "band_protocol.h"
#include "esp_log.h"
#include "esp_random.h"
#include "mbedtls/aes.h"
#include "mbedtls/ecdh.h"
#include "mbedtls/ecdsa.h"
#include "mbedtls/hkdf.h"
#include "mbedtls/md.h"
#include "mbedtls/platform_util.h"
#include "mbedtls/sha256.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_BAND_OWNER_AUTH
#define USE_OWNER 1
#else
#define USE_OWNER 0
#endif
#if USE_OWNER
#ifndef BAND_OWNER_HEADER
#define BAND_OWNER_HEADER "owner_identity.h"
#endif
#include BAND_OWNER_HEADER
#endif
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#define WIRE_CAP 8192
#define DATAX_CAP 32772
#define CHANNEL_CAP 64
#define FRAME_CAP 512
static const char *TAG = "band";
static struct {
    bool initialized, failed, peer_request, encrypted, owner_ok, peer_setup, peer_proof, started, streaming;
    const char *error;
    band_send_fn send;
    mbedtls_ecp_keypair ephemeral;
    uint8_t public[64], challenge[16], seed[32], tx_iv[16], rx_iv[16];
    uint8_t peer_public[64], peer_challenge[16], tx_key[32], rx_key[32];
    uint32_t tx_counter, rx_counter;
    unsigned tx_parameters, rx_parameters;
    uint8_t wire[WIRE_CAP], datax[DATAX_CAP];
    size_t wire_len, datax_len;
    struct {
        uint16_t channel;
        uint32_t kind;
    } types[CHANNEL_CAP];
    size_t type_count;
    uint32_t packets, gestures;
} s;
// Used only by the serialized NimBLE host callbacks; keep large buffers off its stack.
static uint8_t plaintext[4096], authenticated[4105], ciphertext[4106];

static bool fail(const char *why) {
    if (!s.failed)
        ESP_LOGE(TAG, "SESSION ERROR: %s", why);
    s.failed = true;
    s.streaming = false;
    s.error = why;
    return false;
}
static int rng(void *unused, unsigned char *out, size_t len) {
    esp_fill_random(out, len);
    return 0;
}
static uint16_t be16(const uint8_t *p) { return ((uint16_t)p[0] << 8) | p[1]; }
static uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static void put16(uint8_t *p, uint16_t n) {
    p[0] = n >> 8;
    p[1] = n;
}
static void put32(uint8_t *p, uint32_t n) {
    for (int i = 3; i >= 0; i--) {
        p[i] = n;
        n >>= 8;
    }
}
static void little32(uint8_t *p, uint32_t n) {
    for (int i = 0; i < 4; i++) {
        p[i] = n;
        n >>= 8;
    }
}
static bool sha(const uint8_t *p, size_t n, uint8_t out[32]) {
    return !mbedtls_sha256(p, n, out, 0) || fail("SHA256");
}
static bool hmac(const uint8_t key[32], const uint8_t *data, size_t len, uint8_t out[32]) {
    return !mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, 32, data, len, out) ||
           fail("HMAC");
}
static bool equal(const uint8_t *a, const uint8_t *b, size_t n) {
    uint8_t diff = 0;
    for (size_t i = 0; i < n; i++)
        diff |= a[i] ^ b[i];
    return diff == 0;
}
static bool derive(const uint8_t secret[32], const uint8_t challenge[16], const uint8_t seed[32],
                   unsigned mode, uint8_t out[32]) {
    uint8_t ikm[32], salt_input[80], salt[32];
    size_t n = 0;
    if (mode == 3) {
        if (!sha(secret, 32, ikm))
            return false;
        memcpy(salt_input, ikm, 32);
        n = 32;
    } else if (mode == 26 || mode == 27)
        memcpy(ikm, secret, 32);
    else
        return fail("Unsupported AirShield mode");
    memcpy(salt_input + n, challenge, 16);
    memcpy(salt_input + n + 16, seed, 32);
    bool ok =
        sha(salt_input, n + 48, salt) && !mbedtls_hkdf(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), salt, 32,
                                                       ikm, 32, (const uint8_t *)"AirShield", 9, out, 32);
    mbedtls_platform_zeroize(ikm, sizeof(ikm));
    return ok || fail("HKDF");
}
// Strict, bounded protobuf scalar/bytes reader, retaining uint64 timestamps.
typedef struct {
    bool present;
    unsigned wire;
    uint64_t value;
    const uint8_t *bytes;
    size_t len;
} Field;
static bool varint_read(const uint8_t *p, size_t n, size_t *at, uint64_t *v) {
    *v = 0;
    for (unsigned shift = 0; shift < 70; shift += 7) {
        if (*at >= n)
            return false;
        uint8_t b = p[(*at)++];
        if (shift == 63 && (b & 0xfe))
            return false;
        *v |= (uint64_t)(b & 127) << shift;
        if (!(b & 128))
            return true;
    }
    return false;
}
static bool fields(const uint8_t *p, size_t n, Field *out, size_t count) {
    memset(out, 0, count * sizeof(*out));
    size_t at = 0;
    while (at < n) {
        uint64_t tag, v = 0;
        if (!varint_read(p, n, &at, &tag) || !(tag >> 3))
            return fail("Malformed protobuf tag");
        unsigned w = tag & 7;
        uint64_t number = tag >> 3;
        const uint8_t *bytes = NULL;
        size_t len = 0;
        if (w == 0) {
            if (!varint_read(p, n, &at, &v))
                return fail("Malformed protobuf varint");
        } else if (w == 2) {
            if (!varint_read(p, n, &at, &v) || v > n - at)
                return fail("Malformed protobuf bytes");
            len = (size_t)v;
            bytes = p + at;
            at += len;
        } else if (w == 1 || w == 5) {
            len = w == 1 ? 8 : 4;
            if (len > n - at)
                return fail("Truncated protobuf fixed value");
            bytes = p + at;
            at += len;
        } else
            return fail("Unsupported protobuf wire type");
        if (number < count) {
            if (out[number].present)
                return fail("Duplicate protobuf field");
            out[number] = (Field){true, w, v, bytes, len};
        }
    }
    return true;
}
static bool blob(Field f, size_t len) { return f.present && f.wire == 2 && f.len == len; }
static uint64_t scalar(Field f, uint64_t fallback) { return f.present && f.wire == 0 ? f.value : fallback; }
typedef struct {
    uint8_t data[FRAME_CAP];
    size_t len;
    bool bad;
} Buffer;
static void add(Buffer *b, const void *p, size_t n) {
    if (b->bad || n > sizeof(b->data) - b->len) {
        b->bad = true;
        return;
    }
    if (n)
        memcpy(b->data + b->len, p, n);
    b->len += n;
}
static void vi(Buffer *b, uint64_t v) {
    do {
        uint8_t x = v & 127;
        v >>= 7;
        if (v)
            x |= 128;
        add(b, &x, 1);
    } while (v);
}
static void fv(Buffer *b, unsigned n, uint64_t v) {
    vi(b, (uint64_t)n << 3);
    vi(b, v);
}
static void fb(Buffer *b, unsigned n, const void *p, size_t len) {
    vi(b, ((uint64_t)n << 3) | 2);
    vi(b, len);
    add(b, p, len);
}
static bool emit(const uint8_t *data, size_t len) {
    return s.send(data, len) || fail("L2CAP transmit queue full");
}
static bool encrypt_send(const uint8_t *frame, size_t len) {
    if (!s.encrypted || !len || len > FRAME_CAP)
        return fail("Invalid outgoing encrypted frame");
    size_t pad = (-len) & 15, n = len + pad;
    memcpy(plaintext, frame, len);
    memset(plaintext + len, 0xc0 + pad, pad);
    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    int rc = mbedtls_aes_setkey_enc(&aes, s.tx_key, 256);
    if (!rc)
        rc = mbedtls_aes_crypt_cbc(&aes, MBEDTLS_AES_ENCRYPT, n, s.tx_iv, plaintext, ciphertext + 10);
    mbedtls_aes_free(&aes);
    if (rc)
        return fail("AES encrypt");
    ciphertext[0] = 0x40;
    ciphertext[9] = n / 16 - 1;
    size_t at = 0;
    if (s.tx_parameters == 26 || s.tx_parameters == 27) {
        memcpy(authenticated, "\x02\x02\0\0", 4);
        at = 4;
    }
    little32(authenticated + at, s.tx_counter);
    at += 4;
    memcpy(authenticated + at, ciphertext + 9, n + 1);
    uint8_t mac[32];
    if (!hmac(s.tx_key, authenticated, at + n + 1, mac))
        return false;
    memcpy(ciphertext + 1, mac, 8);
    s.tx_counter++;
    return emit(ciphertext, n + 10);
}
static bool frame(uint16_t channel, const uint32_t *words, size_t word_count, const Buffer *payload,
                  bool encrypted) {
    Buffer b = {0};
    uint8_t header[4];
    size_t n = word_count * 4 + (payload ? payload->len : 0);
    if (payload && payload->bad)
        return fail("Outgoing protobuf overflow");
    put16(header, n | (word_count ? 0x8000 : 0));
    put16(header + 2, channel);
    add(&b, header, 4);
    for (size_t i = 0; i < word_count; i++) {
        put32(header, words[i]);
        add(&b, header, 4);
    }
    if (payload)
        add(&b, payload->data, payload->len);
    if (b.bad)
        return fail("Outgoing frame overflow");
    return encrypted ? encrypt_send(b.data, b.len) : emit(b.data, b.len);
}
#if USE_OWNER
static bool owner_proof(void) {
    uint8_t transcript[96], digest_pair[64], digest[32], hint[32], signature[64];
    memcpy(transcript, s.peer_challenge, 16);
    memcpy(transcript + 16, s.peer_public, 64);
    if (!sha(transcript, 80, digest_pair))
        return false;
    memcpy(transcript, s.seed, 32);
    memcpy(transcript + 32, s.public, 64);
    if (!sha(transcript, 96, digest_pair + 32) || !sha(digest_pair, 64, digest) ||
        !sha(owner_public, 64, hint))
        return false;
    mbedtls_ecp_group group;
    mbedtls_mpi d, r, ss;
    mbedtls_ecp_group_init(&group);
    mbedtls_mpi_init(&d);
    mbedtls_mpi_init(&r);
    mbedtls_mpi_init(&ss);
    int rc = mbedtls_ecp_group_load(&group, MBEDTLS_ECP_DP_SECP256R1);
    if (!rc)
        rc = mbedtls_mpi_read_binary(&d, owner_private, 32);
    if (!rc)
        rc = mbedtls_ecdsa_sign(&group, &r, &ss, &d, digest, 32, rng, NULL);
    if (!rc)
        rc = mbedtls_mpi_write_binary(&r, signature, 32);
    if (!rc)
        rc = mbedtls_mpi_write_binary(&ss, signature + 32, 32);
    mbedtls_ecp_group_free(&group);
    mbedtls_mpi_free(&d);
    mbedtls_mpi_free(&r);
    mbedtls_mpi_free(&ss);
    if (rc)
        return fail("Owner signature");
    Buffer p = {0};
    fb(&p, 1, hint, 32);
    fb(&p, 2, signature, 64);
    fv(&p, 3, 2);
    const uint32_t w[] = {0x81000024, 0x02001000};
    ESP_LOGI(TAG, "Sending enrolled-owner proof");
    return frame(0x8002, w, 2, &p, true);
}
#endif
static bool start_input(void);
static bool setup(const uint8_t *data, size_t len) {
    if (len < 8)
        return fail("Short setup frame");
    size_t at = 4;
    uint32_t kind = 0;
    do {
        if (len - at < 4)
            return fail("Truncated setup type");
        kind = be32(data + at);
        at += 4;
    } while (kind & 0x80000000);
    Field f[8];
    if (!fields(data + at, len - at, f, 8))
        return false;
    if (kind == 0x02000001) {
        if (s.peer_request || !blob(f[1], 64) || !blob(f[2], 16) || scalar(f[3], 0) != 0)
            return fail("Invalid peer encryption request");
        unsigned mask = scalar(f[4], 0);
        if (USE_OWNER && (mask & 27) == 27)
            s.tx_parameters = 27;
        else if ((mask & 26) == 26)
            s.tx_parameters = 26;
        else if ((mask & 3) == 3)
            s.tx_parameters = 3;
        else
            return fail("No compatible AirShield mode");
        s.peer_request = true;
        memcpy(s.peer_public, f[1].bytes, 64);
        memcpy(s.peer_challenge, f[2].bytes, 16);
        Buffer p = {0};
        fb(&p, 1, s.public, 64);
        fb(&p, 2, s.seed, 32);
        fb(&p, 3, s.tx_iv, 16);
        fv(&p, 4, s.tx_counter);
        fv(&p, 5, s.tx_parameters);
        const uint32_t w[] = {0x02000002};
        return frame(1, w, 1, &p, false);
    }
    if (kind != 0x02000002 || !s.peer_request || !blob(f[1], 64) || !equal(f[1].bytes, s.peer_public, 64) ||
        !blob(f[2], 32) || !blob(f[3], 16) || scalar(f[4], 0) > UINT32_MAX)
        return fail("Invalid peer encryption enable");
    s.rx_parameters = scalar(f[5], 0);
    if (s.rx_parameters != 3 && s.rx_parameters != 26)
        return fail("Unsupported receive parameters");
    uint8_t encoded[65] = {4}, secret[32];
    memcpy(encoded + 1, s.peer_public, 64);
    mbedtls_ecp_point peer;
    mbedtls_mpi z;
    mbedtls_ecp_point_init(&peer);
    mbedtls_mpi_init(&z);
    int rc = mbedtls_ecp_point_read_binary(&s.ephemeral.MBEDTLS_PRIVATE(grp), &peer, encoded, 65);
    if (!rc)
        rc = mbedtls_ecp_check_pubkey(&s.ephemeral.MBEDTLS_PRIVATE(grp), &peer);
    if (!rc)
        rc = mbedtls_ecdh_compute_shared(&s.ephemeral.MBEDTLS_PRIVATE(grp), &z, &peer,
                                         &s.ephemeral.MBEDTLS_PRIVATE(d), rng, NULL);
    if (!rc)
        rc = mbedtls_mpi_write_binary(&z, secret, 32);
    mbedtls_ecp_point_free(&peer);
    mbedtls_mpi_free(&z);
    if (rc)
        return fail("ECDH peer key");
    bool ok = derive(secret, s.peer_challenge, s.seed, s.tx_parameters, s.tx_key) &&
              derive(secret, s.challenge, f[2].bytes, s.rx_parameters, s.rx_key);
    mbedtls_platform_zeroize(secret, sizeof(secret));
    if (!ok)
        return false;
    memcpy(s.rx_iv, f[3].bytes, 16);
    s.rx_counter = scalar(f[4], 0);
    s.encrypted = true;
    ESP_LOGI(TAG, "AirShield established: TX=%u RX=%u", s.tx_parameters, s.rx_parameters);
#if USE_OWNER
    return owner_proof();
#else
    const uint32_t identity[] = {0x81000024, 0x02003000};
    ESP_LOGI(TAG, "Starting unpaired-band session (no enrolled-owner proof)");
    return frame(0x8002, identity, 2, NULL, true) && start_input();
#endif
}
static bool start_input(void) {
    if (s.started || (USE_OWNER && (!s.owner_ok || !s.peer_setup)))
        return true;
    s.started = true;
    uint8_t random[32];
    esp_fill_random(random, 32);
    Buffer p = {0};
    fv(&p, 1, 1);
    fb(&p, 2, random, 16);
    if (USE_OWNER)
        fb(&p, 3, random + 16, 16);
    const uint32_t end[] = {0x02001000};
    if (!frame(0x8001, end, 1, &p, true))
        return false;
    // Open one RPC subscription channel, then enable only the gesture field (3).
    p = (Buffer){0};
    fv(&p, 1, 2);
    fb(&p, 4, NULL, 0);
    const uint32_t rpc[] = {0x8100ce56, 0x02000314};
    if (!frame(0x8005, rpc, 2, &p, true))
        return false;
    Buffer control = {0};
    fv(&control, 3, 1);
    p = (Buffer){0};
    fv(&p, 1, 3);
    fb(&p, 4, control.data, control.len);
    ESP_LOGI(TAG, "Subscribing to gestures");
    return frame(0x8005, NULL, 0, &p, true);
}
static const char *named(uint64_t value, const char *const *names, size_t count, char unknown[32]) {
    if (value < count)
        return names[value];
    snprintf(unknown, 32, "unrecognized:%" PRIu64, value);
    return unknown;
}
static bool datax_frame(const uint8_t *data, size_t len) {
    uint16_t channel = be16(data + 2);
    uint32_t words[8];
    size_t nw = 0, at = 4;
    if (data[0] & 0x80)
        do {
            if (len - at < 4 || nw == 8)
                return fail("Invalid DataX typed header");
            words[nw++] = be32(data + at);
            at += 4;
        } while (words[nw - 1] & 0x80000000);
    uint32_t kind = 0;
    size_t idx = 0;
    while (idx < s.type_count && s.types[idx].channel != channel)
        idx++;
    if (nw) {
        kind = words[nw - 1];
        if (idx == s.type_count) {
            if (idx == CHANNEL_CAP)
                return fail("Too many DataX channels");
            s.types[idx].channel = channel;
            s.type_count++;
        }
        s.types[idx].kind = kind;
    } else if (idx < s.type_count)
        kind = s.types[idx].kind;
    Field f[16];
    const uint8_t *payload = data + at;
    size_t n = len - at;
    if (USE_OWNER && nw == 2 && words[0] == 0x81000024 && kind == 0x02001001) {
        if (s.peer_proof || !(channel & 0x8000) || !fields(payload, n, f, 16) || !blob(f[2], 64))
            return fail("Malformed/duplicate band trust offer");
        // Match the existing client: no pinned band identity key is available here.
        // This is an owner proof acceptance flow, not band identity verification.
        s.peer_proof = true;
        const uint32_t ack[] = {0x03001000};
        ESP_LOGI(TAG, "Band trust offer received (peer identity unverified)");
        if (!frame(channel & 0x7fff, ack, 1, NULL, true))
            return false;
    } else if (USE_OWNER && nw == 2 && words[0] == 0x8100004f && kind == 0x02000001) {
        const uint32_t ack[] = {0x0300c001};
        if (!frame(channel & 0x7fff, ack, 1, NULL, true))
            return false;
    } else if (USE_OWNER && channel == 2 && nw && kind >> 24 == 3) {
        if (kind != 0x03001000) {
            ESP_LOGE(TAG, "Owner result=0x%08" PRIx32, kind);
            return fail("Enrolled owner identity rejected");
        }
        s.owner_ok = true;
        ESP_LOGI(TAG, "OWNER AUTHENTICATION ACCEPTED");
    } else if (nw == 1 && kind == 0x02001000) {
        if (!fields(payload, n, f, 16) || scalar(f[1], 0) > 1 || !blob(f[2], 16))
            return fail("Invalid peer link setup");
        s.peer_setup = true;
        ESP_LOGI(TAG, "Band link setup received");
    } else if (kind == 0x02000315) {
        if (!fields(payload, n, f, 16))
            return false;
        uint64_t id = scalar(f[1], UINT64_MAX), status = scalar(f[2], UINT64_MAX);
        ESP_LOGI(TAG, "Input response id=%" PRIu64 " status=%" PRIu64, id, status);
        if ((channel & 0x7fff) == 5 && id == 3) {
            if (status != 1)
                return fail("Gesture subscription rejected");
            Field flags[8];
            if (!f[5].present || f[5].wire != 2 || !fields(f[5].bytes, f[5].len, flags, 8) ||
                scalar(flags[3], 0) != 1)
                return fail("Gesture subscription not acknowledged");
            s.streaming = true;
            ESP_LOGI(TAG, "GESTURES READY - tap/pinch index or middle finger; try thumb swipes");
        }
    } else if (kind == 0x0200020d) {
        if (!s.started || !fields(payload, n, f, 16) || !f[1].present || f[1].wire != 0 || !f[2].present ||
            f[2].wire != 0)
            return fail("Invalid gesture message");
        static const char *const fingers[] = {"unknown", "thumb", "index", "middle", "notApplicable"};
        static const char *const actions[] = {"unknown",      "press",     "release",      "tap",
                                              "doubletap",    "click",     "up",           "down",
                                              "left",         "right",     "wake",         "swipeIn",
                                              "swipeOut",     "ia",        "partialPress", "partialRelease",
                                              "partialClick", "partialUp", "partialDown",  "partialLeft",
                                              "partialRight"};
        static const char *const derived[] = {
            "unknown",    "singleTap",  "doubleTap",   "buttonHold",  "buttonRelease",    "buttonUp",
            "buttonDown", "buttonLeft", "buttonRight", "buttonPress", "buttonHoldRelease"};
        char a[32], b[32], c[32];
        s.gestures++;
        ESP_LOGI(TAG, "GESTURE seq=%" PRIu64 " finger=%s action=%s derived=%s synthetic=%u band_us=%" PRIu64,
                 f[1].value, named(scalar(f[3], 0), fingers, 5, a), named(scalar(f[4], 0), actions, 21, b),
                 named(scalar(f[5], 0), derived, 11, c), (unsigned)(scalar(f[12], 0) != 0), f[2].value);
    }
    return start_input();
}
static bool datax_plain(const uint8_t *data, size_t len) {
    if (!len || (len & 15))
        return fail("Non-aligned decrypted record");
    unsigned pad = data[len - 1] - 0xc0;
    if (pad >= 1 && pad <= 16 && pad <= len) {
        bool match = true;
        for (unsigned i = 0; i < pad; i++)
            if (data[len - 1 - i] != data[len - 1])
                match = false;
        if (match)
            len -= pad;
    }
    if (len > DATAX_CAP - s.datax_len)
        return fail("DataX receive overflow");
    memcpy(s.datax + s.datax_len, data, len);
    s.datax_len += len;
    while (s.datax_len >= 4) {
        size_t n = (be16(s.datax) & 0x7fff) + 4;
        if (s.datax_len < n)
            break;
        if (!datax_frame(s.datax, n))
            return false;
        memmove(s.datax, s.datax + n, s.datax_len - n);
        s.datax_len -= n;
    }
    return true;
}
static bool decrypt_record(const uint8_t *record, size_t len) {
    size_t n = len - 10, at = 0;
    uint8_t mac[32];
    if (s.rx_parameters == 26) {
        memcpy(authenticated, "\x02\x02\0\0", 4);
        at = 4;
    }
    little32(authenticated + at, s.rx_counter);
    at += 4;
    memcpy(authenticated + at, record + 9, n + 1);
    if (!hmac(s.rx_key, authenticated, at + n + 1, mac))
        return false;
    if (!equal(mac, record + 1, 8))
        return fail("AirShield MAC mismatch; plaintext rejected");
    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    int rc = mbedtls_aes_setkey_dec(&aes, s.rx_key, 256);
    if (!rc)
        rc = mbedtls_aes_crypt_cbc(&aes, MBEDTLS_AES_DECRYPT, n, s.rx_iv, record + 10, plaintext);
    mbedtls_aes_free(&aes);
    if (rc)
        return fail("AES decrypt");
    s.rx_counter++;
    s.packets++;
    return datax_plain(plaintext, n);
}
bool band_protocol_feed(const uint8_t *data, size_t len) {
    if (s.failed)
        return false;
    if (len > WIRE_CAP - s.wire_len)
        return fail("Transport receive overflow");
    memcpy(s.wire + s.wire_len, data, len);
    s.wire_len += len;
    while (s.wire_len) {
        size_t n = 0;
        if (!s.encrypted) {
            if (s.wire_len < 4)
                break;
            if (!(s.wire[0] & 0x80))
                return fail("Expected encryption setup frame");
            n = (be16(s.wire) & 0x7fff) + 4;
            if (n > WIRE_CAP)
                return fail("Oversized setup frame");
            if (s.wire_len < n)
                break;
            if (!setup(s.wire, n))
                return false;
        } else {
            uint8_t m = s.wire[0];
            if (s.wire_len < 2)
                break;
            if ((m == 0x81 || m == 0x82) && s.wire[1] <= 1)
                n = 2;
            else if (m == 1 || m == 2)
                n = 3 + s.wire[1];
            else if (m == 0x40 || m == 0x41 || m == 0x42) {
                if (s.wire_len < 10)
                    break;
                n = 10 + 16 * (s.wire[9] + 1);
            } else
                return fail("Unsupported transport marker");
            if (s.wire_len < n)
                break;
            // Relay channels are not authenticated by this session and are ignored.
            if (m == 0x40 && !decrypt_record(s.wire, n))
                return false;
        }
        memmove(s.wire, s.wire + n, s.wire_len - n);
        s.wire_len -= n;
    }
    return true;
}
void band_protocol_close(void) {
    if (s.initialized)
        mbedtls_ecp_keypair_free(&s.ephemeral);
    mbedtls_platform_zeroize(&s, sizeof(s));
}
bool band_protocol_start(band_send_fn send) {
    band_protocol_close();
    s.send = send;
    s.initialized = true;
    mbedtls_ecp_keypair_init(&s.ephemeral);
    int rc = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, &s.ephemeral, rng, NULL);
    uint8_t encoded[65];
    size_t n = 0;
    if (!rc)
        rc =
            mbedtls_ecp_point_write_binary(&s.ephemeral.MBEDTLS_PRIVATE(grp), &s.ephemeral.MBEDTLS_PRIVATE(Q),
                                           MBEDTLS_ECP_PF_UNCOMPRESSED, &n, encoded, 65);
    if (rc || n != 65)
        return fail("Generate ephemeral P-256 key");
    memcpy(s.public, encoded + 1, 64);
    esp_fill_random(s.challenge, 16);
    esp_fill_random(s.seed, 32);
    esp_fill_random(s.tx_iv, 16);
    esp_fill_random(&s.tx_counter, 4);
    Buffer p = {0};
    fb(&p, 1, s.public, 64);
    fb(&p, 2, s.challenge, 16);
    fv(&p, 3, 0);
    fv(&p, 4, USE_OWNER ? 31 : 27);
    fv(&p, 7, 16);
    const uint32_t w[] = {0x81000005, 0x02000001};
    return frame(0x8001, w, 2, &p, false);
}
bool band_protocol_streaming(void) { return s.streaming; }
uint32_t band_protocol_gestures(void) { return s.gestures; }
uint32_t band_protocol_packets(void) { return s.packets; }
const char *band_protocol_error(void) { return s.error; }
