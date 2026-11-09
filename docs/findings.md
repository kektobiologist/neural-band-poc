# Verified hardware findings

## Current connection — November 9, 2026

The default is a direct Mac connection using the existing Mac-enrolled owner
Keychain identity. See the [connection guide](mac-enrollment.md) for its location, UUID,
commands, and recovery. Native Meta login, signed ownership receipts, and owner
trust on a fresh connection all succeeded on Meta Band 00Z9 without Android or
a factory reset. A further raw-EMG connection negotiated AirShield parameter 27
and received 898 messages / 14,368 sample frames with zero missing batches;
stream shutdown was acknowledged. The dashboard uses the verified Keychain identity.

Owner-key acceptance and transport packet integrity are established. The
current client does not verify the band's identity signature. Host Bluetooth
bond failures are separate from owner-key rejection; preserve a valid owner
identity when diagnosing a bond problem. CoreBluetooth UUIDs can change after
bond repair and are local to the Mac.

The old phone-extraction procedures, speculative connection diagnostics and
build-specific capture hooks have been removed. Protocol definitions remain in
[protocol](protocol.md), [enrollment](enrollment-flow.md), and
[owner trust](trust-handshake.md). Earlier source versions are in Git history;
private recordings remain local.

## Raw EMG

The observed configuration is eight channels at 2,048 Hz, 16-bit ADC, 16 samples
per batch, encoding 0, and 256 sample bytes. `input_service.py` interprets those
bytes as interleaved little-endian values. Electrode mapping, voltage scaling,
and comparison against the native consumer remain unresolved. This is an
experimental ADC view, not calibrated muscle voltage. Nominal sampling rate
is separate from achieved host delivery rate.

Stream control is RPC field 4; raw EMG is its field 2. Query, enable and disable
must use the same DataX channel. Follow-ups use untyped continuations retaining
the RPC type. An acknowledgement on a different subscription does not stop the
original one. Sequence gaps and unconfirmed shutdown must be reported.

Earlier direct captures established glasses-off / phone-Bluetooth-off operation
under user-confirmed isolation conditions. One September capture received
24,240 sample frames but missed 919 batches; clean results from another session
do not erase that delivery limitation. An October dashboard capture received
56,336 sample frames without missing frames and acknowledged shutdown.

## Handwriting — October 19, 2026

Direct Mac handwriting and the dashboard were verified on firmware
`7fada0507764+`, using pipeline 3 with 100 classes. Ordinary inference on that
firmware reported pipeline 1 with three logits and stride 72; the old nine-logit
interpretation must not be applied to it. See [capture commands](capture-tools.md).

### Handwriting evidence and corrections

The activation sequence came from community source code, especially Rokid Lumen's
`model_capture.rs`, followed by local hardware verification. It was not extracted
from the incomplete phone tutorial recording. See the [wire sequence and source
lineage](protocol.md#handwriting-wire-sequence-and-decoding).

The first idle check received 69 samples without gaps and emitted no text. The
following direct Mac recordings also had no sequence gaps, and each finished with
saved settings restored and stream disable confirmed:

| Trial | Samples | Literal greedy transcript | Interpretation limits |
| --- | ---: | --- | --- |
| Labeled phrase | 249 | `thisiswild.` | Wearer wrote “this is wild” and explicitly added the period. Spatial separation of words did not produce explicit spaces here. |
| Blind 1 | 279 | `iloveyouastra` | Word segmentation was a conversational interpretation, not received space events. |
| Blind 2 | 264 | `apooruaiscrazy!!!!` | “Apoorva is crazy!!!!” was an unconfirmed guess; the ambiguous sample favored u (52.1%) over v (8.1%). |
| Blind 3 | 268 | `eoveyouappy` | “love you appy” was an unconfirmed guess; the ambiguous sample favored e (56.9%) over l (21.1%). A question mark followed by backspace was also observed. |

These are protocol/decoder checks, not a controlled accuracy benchmark. We do not
know all intended blind phrases. The pause/blank-duration spacing hypothesis was
rejected by the wearer and removed from code and UI. Long blanks do not insert
spaces; only explicit space classes do. Meta's implicit word segmentation and
emoji-picker protocol remain unknown. No dictionary corrections are applied.

Live dashboard checks on this firmware verified handwriting readiness and
restoration (45 samples in one run), gesture/motion delivery (43 gestures and
2,664 motion records, including right-hand pinch dial control), and raw EMG
(56,336 eight-channel frames at 2,048 Hz, no missing frames, stream disable
acknowledged). Normal stop and SIGINT/SIGTERM request restoration; transport loss or a
process crash can still prevent cleanup and must be reported as unconfirmed.

## Gestures, motion, and the hand display

A September direct capture under user-confirmed glasses-off and
phone-Bluetooth-off conditions received 153 gesture messages, 38,023 gyro
samples, and 1,580 quaternion samples. Requested fields 3/6/8 were acknowledged
enabled and disabled. Later October dashboard checks recorded 43 gestures and
2,664 motion records, including right-hand pinch-dial control.

Gesture type is `0x0200020d`; gyro is `0x0200020f` (three little-endian int16
values); quaternion is `0x02000212` (four little-endian floats). Gesture timestamps
appear to be epoch microseconds, while gyro timestamps use device uptime. The
dial integrates differences between gyro timestamps, not across those clocks.
Physical gyro units/axes and quaternion ordering still require confirmation.

The skinned hand illustrates recognized events; it does not infer measured
finger-joint angles. Its asset provenance is in
[the model README](../dashboard/static/models/README.md). Ring/pinky geometry
does not establish recognition; personal classifiers remain experimental.
See [gesture references](gestures.md), [handedness](handedness.md), and
[pinch-learning results](pinch-learning.md).

A combined raw-EMG/gesture/motion experiment failed when an independent gesture
record arrived during an unfinished sensor DataX frame. Subsequent combined
runs stalled or did not confirm shutdown. Separate modes remain the supported
workflow. Host process activity hints reduce App Nap exposure but are not a
proven cure for radio or delivery stalls.
