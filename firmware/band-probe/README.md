# ESP32-S3 gesture serial monitor

Standalone BLE/L2CAP, AirShield encryption, enrolled-owner authentication, and
gesture decoding for the neural band. The ESP32 runs the protocol; no Mac
Bluetooth connection or Python bridge is required during normal operation.

## Combined AC test — 2026-10-17

The connected board now runs the `band-ac` environment. Index double-tap turns
the AC on, middle double-tap sends OFF → ON → OFF, and thumb right/left raises
or lowers temperature. Build, waveform comparison tests, upload, and live band
authentication passed. The user subsequently confirmed end-to-end operation and the completed
transmitter-only perfboard build on 2026-10-18. See [AC control](AC_CONTROL.md) for commands
and test instructions. The `esp32-s3` environment retains the BLE-only probe.

## Identity and hardware status

Use the current Mac-enrolled Keychain identity documented in the
[connection guide](../../docs/mac-enrollment.md). The November 9, 2026 identity
was verified for Mac owner trust and raw EMG; it has **not yet been provisioned
or verified on the ESP32**. Existing flashed firmware may contain the old key.

The October 7 ESP32 test verified BLE bonding, L2CAP CoC on PSM 129, AirShield
TX 27 / RX 26, owner acceptance, and gesture subscription. It recorded 39 real
gesture messages; the user also confirmed gestures in Arduino Serial Monitor.
That validates the firmware implementation, not the currently embedded key.

Provision the current Keychain identity using the instructions below. Keep private PEMs,
generated owner headers, and firmware binaries containing them out of Git.
The original full flash backup remains local at
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

## Serial commands

Type `battery` in Arduino Serial Monitor and press Send. Wait for
`GESTURES READY` first. The ESP32 reads the band's standard Battery Level
characteristic (`0x2a19`) over the existing GATT connection and prints, for
example:

```text
BATTERY 77% (fresh band reading)
```

This is a new read for each command, not a cached estimate. It does not restart
the gesture stream. `help` lists commands. Commands ignore case and surrounding
spaces; Newline, Carriage return, Both NL & CR, and No line ending are supported.
With no line ending, a 300 ms input pause completes the command. Commands longer
than 63 characters are discarded. While disconnected or still authenticating,
`battery` reports that state; send it again once ready.

Hardware validation on 2026-10-09 returned 77% through the serial command while
streaming remained active. This is a historical reading, not a current battery
estimate. The local test log is `captures/esp32-battery-20261009.log`.

## Build and provision

Run from the repository root. Python 3.12, PlatformIO 6.2.0, PlatformIO
espressif32 6.12.0, and ESP-IDF 5.5.0 were used.

```sh
python3 -m venv .venv-esp
.venv-esp/bin/pip install platformio==6.2.0 esptool==5.4.0 cryptography
.venv-esp/bin/python firmware/band-probe/provision_identity.py keychain:BAND_UUID:PUBLIC_KEY_SHA256
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

Keep other band clients disconnected while the ESP32 is using the band.
If owner authentication rejects with `0x03001043`, first verify the PEM with
`instrumentation/enroll_band.py BAND_UUID --verify-key keychain:BAND_UUID:PUBLIC_KEY_SHA256`.
If accepted on the Mac, provision that same key into the ESP32 and rebuild;
changing signature code or enrolling yet another identity does not repair a
stale embedded key. If the key is rejected on the Mac too, follow the
[Mac recovery flow](../../docs/mac-enrollment.md#recovery).

If macOS reports “Peer removed pairing information,” forget only the band in
Mac Bluetooth settings, rescan, and use the fresh CoreBluetooth identifier.
The ESP32's stale bond produced encryption failure before owner authentication.
For this exact probe build, clearing only its NVS partition (`0x9000`, size
`0x6000`) allowed a fresh bond. Verify the partition table before any erase;
these addresses are not a general recipe for other firmware. NVS erasure also
removes other data in that partition. The original full flash backup is noted
above. Do not factory-reset or unpair the band to fix a host's stale bond.

The original `esp32-s3` environment is a serial diagnostic. The `band-ac`
environment now adds AC-only gesture mapping and IR; broader appliance and
ESP-NOW integration remains future work. Raw and derived events can
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
