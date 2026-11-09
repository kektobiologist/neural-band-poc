# Mac capture tools

Use the [connection guide](mac-enrollment.md) for the current Keychain identity and
band UUID. Normal captures reuse that identity. Enrollment/recovery is handled
by `instrumentation/enroll_band.py`; no phone-side capture is required.
Commands below run from the repository root in the project's Python environment.
Use a new output filename for each run. Raw captures include session material
and must remain in ignored local storage.

## Discovery and connection

```sh
mkdir -p captures
python instrumentation/scan_band.py --output captures/scan.json
python instrumentation/read_band_status.py BAND_UUID --output captures/status.json
python instrumentation/mac_band_probe.py BAND_UUID \
  --query-device-info --query-config --seconds 35 --output captures/mac-info.jsonl
```

The probe reads the advertised L2CAP PSM, negotiates AirShield parameters 3, 26
or 27, authenticates the enrolled owner, then opens the input service. Packet
MACs are checked before plaintext is interpreted. Owner-key acceptance is
verified; the current client does not verify the band's identity signature.
The no-key identity query exists for enrollment bootstrap, not ordinary capture.

## Raw EMG and gestures

```sh
python instrumentation/mac_band_probe.py BAND_UUID \
  --query-device-info --stream-control raw-emg --seconds 60 \
  --output captures/mac-emg.jsonl
python instrumentation/mac_band_probe.py BAND_UUID \
  --query-device-info --stream-control dial --seconds 60 \
  --output captures/mac-dial.jsonl
```

Raw mode queries configuration, enables stream field 2, and disables the same
subscription before disconnecting. Dial mode uses fields 3/6/8 for gestures,
gyroscope, and quaternion samples. Follow-up requests retain the same DataX
channel; opening another channel creates another subscription. Ctrl-C requests
shutdown and allows a drain interval; an abrupt disconnect may prevent it.

The raw decoder supports the observed eight-channel, 2,048 Hz, 16-bit ADC,
16-samples-per-batch configuration (encoding 0, 256 sample bytes). Values are
experimental ADC counts, not calibrated voltages or established electrode maps.
Check `probe_result` for owner acceptance, sample counts, missing batches, and
stream-disable acknowledgement. Transport reception alone does not prove usable
sensor data. Use separate raw-EMG and dial sessions; combined framing remains
unresolved.

## Dashboard

```sh
python -m dashboard.server --port 8765
```

Open [localhost:8765](http://localhost:8765), find/select the band and choose a
stream. The dashboard resolves the selected band's Keychain reference from
`~/Library/Application Support/NeuralBand/identities.json`, shared across
worktrees on this Mac. Stop active streams before enrollment or another hardware client.
See [haptics](haptics.md) and [handedness](handedness.md) for their controls.

### Direct handwriting (verified 2026-10-19)

`--stream-control handwriting` discovers `data-collection` and
`data-collection-model` by name, snapshots both values, enables stream fields
4/22/23, writes collection=1/model=5, and verifies both with separate reads.
On this firmware their IDs are **7/8**, and the original values are **0/4**.
Never hardcode the reference implementation's IDs or default model 2.
The first live check received 69 normalized 100-class distributions on pipeline
3 without sequence gaps; it then restored 0/4, read both back, and confirmed
streams off. Idle output contained no text. A subsequent labeled “this is wild” sample
decoded live as `thisiswild.` (249 samples, no sequence gaps). All letters
were recognized, but spaces were absent. The wearer confirmed that the trailing
period was intentionally written; it was not an extra decoder insertion. Settings 0/4 and stream disable were verified afterward. This is one
successful sample, not a general accuracy benchmark.

```sh
.venv/bin/python instrumentation/mac_band_probe.py BAND_UUID \
  --stream-control handwriting \
  --seconds 120 --output captures/handwriting-new.jsonl
```

Wait for `handwriting_ready`, then write. The duration begins when at least five
valid samples arrive. `handwriting_text` reports a basic greedy CTC transcript;
raw scores remain in `handwriting_sample` events. Blanks, repeated predictions,
spaces, deletion, newline, and shift are handled, with no language model.
SIGINT/SIGTERM and the normal duration limit initiate restoration with readbacks.
A transport loss or process crash can prevent restoration; the capture records
original values before any setting writes, and unconfirmed restoration is an
error. Captures contain session secrets and remain local/ignored (mode 0600).

Protocol and character mapping reference: [Rokid Lumen at 4fe2376](https://github.com/beyondlevi/rokid-lumen/tree/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core/src),
itself crediting Kinesis. The reference license is retained under
`instrumentation/licenses/rokid-lumen-MIT.txt`.

## Offline analysis

`analyze_capture.py`, `decrypt_capture.py`, and `extract_telemetry.py` remain for
analyzing existing local research recordings. They do not connect, enroll, or
recover a current owner key. `decrypt_capture.py` expects the historical
recording schema with correlated key observations, not arbitrary Mac JSONL.
`extract_telemetry.py` consumes its authenticated plaintext and checks file
lengths, Adler-32, and decompression before reporting recorded SDK events.
These delayed telemetry events are distinct from the direct live sensor stream.

For current inference recordings use `analyze_inference.py`; interpretation is
pipeline-specific. Three-logit outputs must not be interpreted with the older
nine-logit labels. See [gesture models](gesture-models.md).
