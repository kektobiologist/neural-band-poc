# Client-controlled haptic feedback

The Mac client can trigger a buzz independently of gesture recognition and send
rapid sequences of buzzes. Wearer tests on October 20, 2026 confirmed playback.
Use **255 as the practical intensity ceiling**: higher tested values did not
produce a useful perceived increase. The exact firmware behavior above 255,
the RPC duration unit, and native pattern playback remain unverified.

## Use the local console

Start the dashboard with `python -m dashboard.server` and open
[localhost:8765](http://localhost:8765). Find/select the band using the existing
connection controls. An already enrolled band needs its existing owner identity
configured as described in [the Mac connection guide](mac-enrollment.md).

The **Try a buzz** panel connects automatically when a test button is pressed.
Keep the hand still to avoid confusing gesture feedback with the test. After
connection, a three-second countdown precedes playback.

- **Single buzz:** uses the selected intensity and raw duration value.
- **Double buzz:** repeats the selected intensity twice, with a short gap.
- **Compare 4 buzzes:** sends **128 → 255 → 256 → 384**, regardless of the
  intensity slider. All four use the selected duration value and gap.

Start with intensity 128 or 255 and duration value 150 or 300. Intensity is not
a percentage, and duration is deliberately not labeled in milliseconds. The
console permits raw intensity values 1–1023 for experiments, raw duration
values 50–1000, and gaps of 50–1000 ms. These are application limits, not a
specification of the band's supported range. Values above 255 are diagnostic.

Single-buzz mode sends an explicit stop after 1.5 seconds. Double-buzz and
four-buzz modes send stop after **150 ms per pulse**, then wait the selected
gap (100 ms by default). Both the preceding pulse and stop must be acknowledged
before the next pulse. With prompt Bluetooth replies, pulse starts are about
250 ms apart; a live four-pulse trial measured approximately 255 ms. These are
host command timings, not measurements of motor-on time or the device's duration
unit. The motor may finish earlier according to the duration field.

**Stop** cancels remaining pulses and queues stop for an active pulse. Each test
session disconnects after 20 seconds. Wait for the buttons to re-enable before
repeating. Status shows which commands were acknowledged and the tested values;
an acknowledgement alone does not prove physical vibration. A disconnected
transport cannot guarantee delivery of a stop command.

## CLI and client integration

Run from the repository root with the project's Python environment:

```sh
python instrumentation/haptic_probe.py BAND_COREBLUETOOTH_UUID \
  --amplitude 255 --duration 300 --count 2 --gap-ms 100 \
  --output captures/haptic-double.jsonl
```

The output file must be new. The owner-key flag is optional only where the
existing device setup supports a connection without it. This command reuses the
existing transport; it does not enroll, reset, or change persistent settings.

`--count` accepts 1, 2, or 4. Count 4 selects the fixed diagnostic comparison;
it does not send four identical pulses. `--amplitude` is ignored in that mode.
`--duration` is a raw protocol value. `--gap-ms` is a real host-side interval.
Ctrl-C follows the same cancellation path as the console's Stop button.

The dashboard accepts a same-origin JSON POST to `/api/haptics`:

```json
{"amplitude":255,"duration":300,"count":2,"gap_ms":100}
```

A started test returns HTTP 202; a busy dashboard returns 409; invalid settings
return 400. `/api/state` exposes an allowlisted `haptics` event list containing
countdown, sent-command, reply, and cancellation status without raw packets or
keys. `instrumentation/haptic_settings.py` shares validation between the CLI and
server; `instrumentation/haptic_probe.py` owns sequencing and reply matching.

For client-state feedback, choose a pulse or repeated-pulse sequence on a state
transition. The console currently opens a bounded connection for each test, so
it is not a low-latency feedback service for an already running gesture session.
A persistent integration should reuse its active authenticated transport and
allocate request IDs/channels without colliding with other requests. The test
probe shares the existing band connection lock and must not run alongside an
independent Bluetooth owner.

## Wire format

Recovered from generated `wearableinputservice.Haptics` classes in the locally
saved Meta AI Android APK, then exercised on the band:

- Service: `0xce56`; request type: `0x02000314`; response type: `0x02000315`.
- Probe channel: `0x8001`; reply channel: 1 after masking the direction bit.
- RpcRequest field 1: request ID; field 17: HapticsReq.
- HapticsReq field 1: VibrateReq; field 3: empty StopReq.
- VibrateReq field 1: 64-bit integer duration; field 2: float frequency;
  field 3: integer amplitude. Tested requests omit frequency.
- Replies match request ID/channel/type and carry outer status 1 plus field 18
  (HapticsResp). Tested HapticsResp messages were empty, without an explicit
  nested vibrate/stop result. These are outer RPC acknowledgements.

Generated classes also expose perform=2 (patternId=1) and hapticPattern=4
(pattern=1, autoPlay=2); patterns have name=1 and segments=2, and segments have
duration=1 and amplitude=2. **Native pattern upload/playback has not been tested.**
Repeated buzzes in this feature are separate host-issued RPCs.

## Hardware evidence and open questions

1. Duration=150, amplitude=128 produced a wearer-confirmed weak buzz in the
   interactive console. Earlier command-line trials were missed or not felt.
2. Rapid repeated pulses were confirmed by the wearer. Four-pulse trials
   received all eight pulse/stop acknowledgements.
3. The comparison **255 → 511 → 767 → 1023** felt the same to the wearer.
   Those integers all have low byte `0xFF`, so this alone cannot distinguish
   clamping from byte truncation.
4. The follow-up **128 → 255 → 256 → 384** received all eight acknowledgements.
   The wearer concluded that 255 seemed to be the limit, without reporting
   enough individual-pulse detail to establish clamping versus truncation.
   Therefore 255 is a practical working ceiling, not a proven firmware maximum.

Fresh settings discovery found `haptics` at ID 9, reading enum 3
(`all_enabled` / `enabled`), and `trigger-haptics` at ID 39. The latter describes
triggering haptics with a duration in ms and contains two integer constraints,
255 and 65535. Its write encoding and argument meanings were not established.
The settings help text does **not** establish the duration unit of the separate
VibrateReq RPC used here. No settings writes were needed.

The lead came from [Kinesis issue 11](https://github.com/callbacked/kinesis/issues/11#issuecomment-6151575420).
Kinesis at `5c78485f48c0758e2ce46ee11d3aaa070d827b75` did not implement custom
haptic playback. Its contributor's setting IDs differ from this band's, so
settings must be discovered by name.

Ignored local evidence includes `captures/haptics-20261019/` schema/discovery
files and `captures/mac-band-probe-dashboard-*.jsonl` trials. Captures contain
session material and must remain local. Automated tests cover encoding, higher
amplitudes without host truncation, ordering, gaps, acknowledgement gating,
cancellation, late connection, input bounds, and sanitized dashboard output.
