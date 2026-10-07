# ESP32-S3 gesture serial monitor

Standalone BLE/L2CAP, AirShield encryption, enrolled-owner authentication, and
gesture decoding for the neural band. The ESP32 runs the protocol; no Mac
Bluetooth connection or Python bridge is required during normal operation.

## Current hardware status — 2026-10-07

**Owner authentication and gesture subscription now succeed on ESP32-S3.**
After re-pairing the band in Meta on the rooted OnePlus, a new enrolled signing
key was recovered locally. The Mac accepted this key and recorded 29 gesture
messages and 22,284 motion messages with a clean stream shutdown. The same key
was provisioned into the ESP32, which reports `OWNER AUTHENTICATION ACCEPTED`
and `GESTURES READY`. The USB capture recorded 39 real gesture messages,
including index press, hold, and release events, directly from the ESP32. The
user subsequently confirmed gestures working in Arduino Serial Monitor.

The earlier saved key was stale: the Mac rejected it with `0x03001043`, and
no-owner attempts disconnected before subscription. Re-pairing also invalidated
the old Mac and ESP32 Bluetooth bonds; the Mac bond was forgotten and only the
ESP32 NVS partition was cleared before reconnecting. The phone's Meta enrollment
was preserved, Meta was force-stopped, and phone Bluetooth was switched off.
Do not unpair in Meta after recovering the key.

Verified directly on ESP32-S3:

- BLE bonding/encryption, GATT discovery, and L2CAP CoC on PSM 129.
- Local MTU 512 / peer MTU 970; AirShield TX 27 / RX 26.
- Enrolled-owner acceptance, peer link setup, and gesture-enable acknowledgement.

Local evidence (ignored by Git):
`captures/oneplus/repaired-20261007/mac-gestures-fresh.jsonl` and
`captures/oneplus/repaired-20261007/esp32-fresh.log`.
The recovered PEM is private in that same ignored directory; do not publish
it, the generated owner header, or the compiled firmware.
The original full 16 MB ESP32 flash backup is
`captures/esp32-s3-original-20261007.bin`.

## Arduino Serial Monitor

The firmware is flashed using PlatformIO/ESP-IDF. Arduino IDE can read its USB
serial output without compiling or uploading an Arduino sketch.

1. Select the native USB Serial/JTAG port (on this Mac `/dev/cu.usbmodem2101`).
2. Open Serial Monitor and set **115200 baud**.
3. Press the ESP32's **RESET** button to see the full connection sequence.
4. A working subscription prints `GESTURES READY`. Only then try index/middle
   taps, pinches/holds, releases, and thumb swipes.

An actual line from the hardware capture:

```text
GESTURE seq=24 finger=index action=release derived=unknown synthetic=0 band_us=1791380578902740
```

Every five seconds a running stream prints its gesture and authenticated-packet
counts. Every actual band gesture is printed, including raw/derived and synthetic
flags; this is a diagnostic display, not deduplicated appliance actions.

Protocol/authentication failures stop the client and require RESET after the
cause is corrected. No generated gestures are substituted. Ordinary disconnects
trigger a fresh scan and handshake. Connection setup has a 45-second timeout;
streaming itself has no preset duration. Close other serial monitors before
flashing or capturing.

## Build and provision

Run from the repository root. Python 3.12, PlatformIO 6.2.0, PlatformIO
espressif32 6.12.0, and ESP-IDF 5.5.0 were used.

```sh
python3 -m venv .venv-esp
.venv-esp/bin/pip install platformio==6.2.0 esptool==5.4.0 cryptography
.venv-esp/bin/python firmware/band-probe/provision_identity.py /absolute/path/to/enrolled-owner.pem
.venv-esp/bin/pio run -d firmware/band-probe
.venv-esp/bin/pio run -d firmware/band-probe -t upload --upload-port /dev/cu.usbmodem2101
```

Owner authentication is enabled by `CONFIG_BAND_OWNER_AUTH=y` in
`sdkconfig.defaults`. Existing generated sdkconfig files must enable it too.

The provisioning script generates `main/owner_identity.h` with mode 0600 and
never prints the private key. That header and build outputs are ignored by Git.
**The compiled firmware contains the owner key: keep it private.** Provisioning
copies an existing key into the ESP32 build; it does not enroll the band or
change ownership. A current valid key is required for the enrolled path.

The board profile targets ESP32-S3 with 16 MB flash and native USB Serial/JTAG
console. The attached board has 8 MB PSRAM, but this firmware does not need or
enable it. BLE bonds persist in NVS. HKDF is enabled and the NimBLE host stack
is sized for the crypto/protocol callbacks. No appliance GPIOs are configured.

Optional bounded serial capture (new output file required):

```sh
.venv-esp/bin/python firmware/band-probe/capture.py --reset --seconds 60 --output captures/esp32-gestures-new.log
```

## Recovery and continuation notes

Keep the Android Meta pairing intact and its Bluetooth off while the ESP32 is
connected. Re-pairing in Meta can change the enrolled owner key and invalidate
Bluetooth bonds. If owner authentication rejects with `0x03001043`, first test
the same PEM using the Mac probe; changing the ESP32 signature code does not
repair a stale identity.

The successful October 7 recovery used the rooted OnePlus (NE2211), Meta
292.1.0.19.164 / build 969202234, and Frida 17.15.5. A build-checked native hook
observed the signing identity during an ordinary Android reconnect. Local-only
recovery script and candidate PEM are in
`captures/oneplus/repaired-20261007/recover_identity.py` and
`captures/oneplus/repaired-20261007/owner-candidate-1.pem`. Native offsets are
build-specific; do not reuse them after an app update without checking anchors.
The prior September PEM is stale. The abandoned Meta sign-in/enrollment helper
is archived under ignored `captures/esp32-enrollment/experimental-source/` and
was not used to obtain the working key.

After recovering the key, Meta was force-stopped and Android Bluetooth disabled
without unpairing. The Mac test used `mac_band_probe.py --stream-control dial`
with the new `--identity-key`, then ended before the ESP32 test. The dashboard's
local identity mapping and selected band were updated on disk; an already
running dashboard may need a restart to load the new selection. Keep Mac band
clients stopped while using the ESP32.

If macOS reports “Peer removed pairing information,” forget only the band in
Mac Bluetooth settings, rescan, and use the fresh CoreBluetooth identifier.
The ESP32's stale bond produced encryption failure before owner authentication.
For this exact probe build, clearing only its NVS partition (`0x9000`, size
`0x6000`) allowed a fresh bond. Verify the partition table before any erase;
these addresses are not a general recipe for other firmware. NVS erasure also
removes other data in that partition. The original full flash backup is noted
above. Do not factory-reset or unpair the band to fix a host's stale bond.

The current firmware is a serial diagnostic. Next work is the appliance gesture
state machine and ESP-NOW/IR/output integration. Raw and derived events can
represent the same physical gesture; deduplicate them and ignore synthetic
cleanup events before triggering appliance actions. No appliance GPIOs or
latency claims have been validated by this test.

## Protocol and verification

`main/band_protocol.c` ports the repository's `BandHandshake`, `OwnerTrust`, and
`InputService` gesture subset: ephemeral P-256 ECDH, HKDF-SHA256, AES-256-CBC,
truncated HMAC verification, owner ECDSA proof, DataX reassembly, gesture-only
subscription, and sequence/timestamp/finger/action decoding. It retains partial
frames across SDUs, bounds buffers, handles L2CAP credit stalls, and fails closed
on invalid MACs or owner rejection. No session/private keys are logged.

Like the existing Mac client, this port does not pin/verify the band's identity
signature; it logs that limitation. Acceptance of the host's owner proof and
transport MAC verification are separate facts. No motion/EMG streams, config
changes, enrollment, or appliance outputs are requested.

The actual C protocol passed independent host-side integration tests against the
Python cryptography/protocol implementation using a synthetic test identity:

- Parameter-26 and parameter-3 receive modes and the selected transmit modes.
- One-byte-fragmented setup and encrypted packets, plus coalesced DataX messages.
- Independent verification of the C-generated enrolled-owner proof.
- Encrypted startup/RPC subscription and named gesture/timestamp decoding.
- Replay rejection without releasing an extra gesture; owner rejection without
  starting a stream.

These tests validate code interoperability, not successful physical gestures.
To reproduce, build a host copy of the bundled mbedTLS and run:

```sh
cmake -S "$HOME/.platformio/packages/framework-espidf/components/mbedtls/mbedtls" -B /tmp/band-mbedtls -DENABLE_PROGRAMS=OFF -DENABLE_TESTING=OFF
cmake --build /tmp/band-mbedtls -j 8
.venv-esp/bin/python firmware/band-probe/tests/test_protocol.py --mbedtls-source "$HOME/.platformio/packages/framework-espidf/components/mbedtls/mbedtls" --mbedtls-build /tmp/band-mbedtls
```

## References

- [Espressif's NimBLE L2CAP CoC central example](https://github.com/espressif/esp-idf/tree/v5.5/examples/bluetooth/nimble/ble_l2cap_coc/coc_blecent)
- Repository `instrumentation/mac_band_probe.py`, `airshield.py`, `owner_auth.py`,
  `input_service.py`, and `scan_band.py`.
