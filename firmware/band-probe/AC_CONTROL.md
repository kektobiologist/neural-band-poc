# Band → ESP32 → Samsung AC

The `band-ac` PlatformIO environment combines the existing enrolled-owner BLE
client with hardware-timed Samsung AC IR on **GPIO4**. Wiring is the same as
[the IR bench circuit](../ac-ir-test/README.md); no rewiring is needed. The user
selected the following AC-only test mapping on 2026-10-17:

| Gesture | Action |
| --- | --- |
| Index double-tap | ON, initially Cool / 24 °C / Auto fan / swing off |
| Middle double-tap | OFF → 1 s pause → ON → 1 s pause → OFF |
| Thumb swipe right | Temperature +1 °C (warmer) |
| Thumb swipe left | Temperature −1 °C (cooler) |

Temperature commands require a previous ON and stay within 16–30 °C. Power and
temperature are requested settings, not feedback from the appliance. No IR is
sent on boot, reconnection or subscription. Gestures are enabled after boot.
The user confirmed the cleaning-cancel sequence on the standalone IR build;
keep the emitter aimed throughout its approximately three seconds.

At 115200 baud, serial commands are `on`, `off`, `off single`, `up`, `down`,
`temp 23`, `status`, `battery`, `help`, `gestures on`, and `gestures off`.
Disabling gestures does not interrupt an active shutdown sequence, so its final
OFF still goes out. It also does not disable manual serial AC commands.

Watch for `GESTURE`, then `BAND -> AC ON/OFF/TEMP_UP/TEMP_DOWN`, then `IR SENT`.
A successful OFF sequence ends with `SHUTDOWN sequence complete`.
These logs establish dispatch, not appliance reception; check the AC display.
The built-in VS1838B receiver remains connected but is not read by this build.
Use the standalone `ac-ir-test` firmware for capture/loopback diagnostics.

## Concurrency and duplicate handling

The BLE callback only maps events and submits work without waiting. A separate
FreeRTOS task owns the requested AC state and the shutdown sequence. RMT supplies
38 kHz / 50% modulation in hardware. Its 192-symbol allocation holds an entire
175-symbol extended frame, avoiding a mid-frame memory refill.

The mapping consumes derived doubleTap events for fingers, and raw left/right
swipe events for thumb or notApplicable finger identifiers. Other raw/derived
representations, synthetic cleanup events and unmapped actions do nothing.
Repeated same-action timestamps within 300 ms are suppressed. Commands arriving
while the worker is occupied are dropped with `AC BUSY`; they are not deferred
until after shutdown. Gesture submissions older than 1.5 s are dropped too.

## Build / flash / verify

Use the existing provisioned identity; do not erase NVS or re-enroll the band.
The original `esp32-s3` environment remains a Bluetooth-only diagnostic build.
Build output contains the private enrolled identity and must stay ignored.

```sh
uv run --with platformio==6.1.18 pio run -d firmware/band-probe -e band-ac
uv run --with platformio==6.1.18 pio run -d firmware/band-probe -e band-ac -t upload --upload-port /dev/cu.usbmodem1101
python3 firmware/band-probe/tests/test_ac_logic.py
```

The host test requires the pinned IRremoteESP8266 2.8.6 dependency installed by
building `firmware/ac-ir-test`. It compiles the actual native C frame builder
and compares emitted mark/space timings with the library's own sender, across
all 60 combinations of 16–30 °C, ON/OFF and 14/21-byte frames. It also checks
synthetic-event rejection, raw/derived duplicates, replay rejection and mapping.

2026-10-17: these tests passed, the combined firmware built and flashed, and live
BLE bonding, owner authentication and `GESTURES READY` passed. Battery read 100%.
No gestures arrived during the initial 100-second capture. The user subsequently
confirmed end-to-end operation and, on 2026-10-18, confirmed the transmitter-only
perfboard assembly works with the ESP32 mounted in female headers. Local capture:
`captures/band-ac-first-20261017.log`.

Protocol reference: [IRremoteESP8266 2.8.6 Samsung implementation](https://github.com/crankyoldgit/IRremoteESP8266/blob/v2.8.6/src/ir_Samsung.cpp).
RMT reference: [Espressif ESP32-S3 RMT driver](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/peripherals/rmt.html).

Perfboard assembly: [whole board](../ac-ir-test/diagrams/samsung-ac-perfboard-full.png) and
[component / solder sides](../ac-ir-test/diagrams/samsung-ac-perfboard.png).
The assembled circuit uses a 270 Ω LED resistor, 470 Ω base resistor, 10 kΩ
base–emitter pull-down and 100 µF supply capacitor; no receiver is fitted.
