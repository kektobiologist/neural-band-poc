# protocol sources

Checked September 13, 2026 (local date). Read-only research; no device calls. Local inputs: `captures/native-inspection-20260913.json` and `captures/bluetooth-20260913-startup.log`. All cited community repositories were last updated **October 26, 2025**, per GitHub commit metadata.

## Current local verification

The public sources below supplied the starting schema and parameter-31 vectors. Subsequent hardware work now verifies both the band (parameters 3) and glasses (31): the latest complete capture authenticates **850 channel-zero packets** with independently derived keys matching the companion app. See [findings.md](findings.md) for the measured formulas, relay framing, capture files, and limits. Statements below about what the public repositories do not document remain limitations of those sources, not current blockers to phone-link decryption.

## Decisive public lead

Zhuowei Zhang published **SimStella**, **Starcruiser-mac**, and Android Frida notes implementing/researching the Meta Ray-Ban **AirShield + DataX** protocol. These provide an actual setup protobuf schema and reproducible key-derivation vectors. This is substantially more specific than inferring AES-GCM from imports or packet lengths. It is community reverse-engineering evidence, not an official Meta protocol specification or a proven complete band driver.

Exact pinned sources:

- [SimStella setup schema, `atc.proto`](https://github.com/zhuowei/SimStella/blob/5c603b2957c8d51ba134dd51b580ee7a06d76c83/app/src/main/proto/com/oculus/atc/atc.proto).
- [Starcruiser `Datax.swift`: framing, handshake, crypto](https://github.com/zhuowei/Starcruiser-mac/blob/1bc6f9418ad85a10991817c74e15a84f85078f53/Sources/starcruiser/Datax.swift).
- [Starcruiser `key_derivation_test.swift`: public vectors](https://github.com/zhuowei/Starcruiser-mac/blob/1bc6f9418ad85a10991817c74e15a84f85078f53/key_derivation_test.swift).
- [Android Frida instrumentation](https://github.com/zhuowei/meta-ray-ban-android-app-frida/blob/6bfcf7ca873bb636bec8ff9560d3057a203c7062/dump_pairing.js) and [nonmultiplexed trace/derivation notes](https://github.com/zhuowei/meta-ray-ban-android-app-frida/blob/6bfcf7ca873bb636bec8ff9560d3057a203c7062/notes/non_multiplexed_differences.txt).

The [Starcruiser README](https://github.com/zhuowei/Starcruiser-mac/blob/1bc6f9418ad85a10991817c74e15a84f85078f53/README.md) documents receiving `RequestEncryption` from glasses over service `FD5F`, characteristic `05ACBE9F-6F61-4CA9-80BF-C8BBB52991C0`, and an L2CAP channel. It describes limited functionality; do not assume full end-to-end control.

## Schema and fresh-capture comparison

Public `com.oculus.atc` setup IDs: request encryption `1`, enable encryption `2`, link setup config `3`, end link setup `0x1000`. The schema contains these protobuf fields:

| Message | Fields |
| --- | --- |
| RequestEncryption | `1 bytes public_key`; `2 bytes challenge`; `3 int32 elliptic_curve`; `4 int32 supported_parameters`; `5 repeated bytes key_hint`; `6 int32 quirks` |
| EnableEncryption | `1 bytes public_key`; `2 bytes seed`; `3 bytes iv`; `4 uint32 base`; `5 int32 parameters`; `6 int32 quirks`; `7 bool phased_link_setup_supported`; `8 int64 supported_link_setup_services` |

[Schema source](https://github.com/zhuowei/SimStella/blob/5c603b2957c8d51ba134dd51b580ee7a06d76c83/app/src/main/proto/com/oculus/atc/atc.proto).

An independent offline wire-type parse of the local startup capture consumed **all eight plaintext setup frames without leftovers** using protobuf offset 12 for requests and 8 for enables. Source code selects these offsets via the high bit of byte 2. All eight also satisfy the locally observed `(u16be(first2) & 0x7fff) + 4 == length` rule. Preserve that observed length rule: the public sample's request encoder does not consistently account for its extra four-byte header.

| Local capture sequences | Observations |
| --- | --- |
| Glasses 8, 9 | Type 1; public key 64 bytes, challenge 16 bytes, curve 0, supported parameters 31. Unknown field 7 is 17/16. |
| Glasses 10, 12 | Type 2; key 64, seed 32, field 3 length 16, base varint, parameters 31. Glasses response additionally has fields 7=1 and 8=1. |
| Band 96, 97 | Type 1; phone offers 31, band offers **3**; band key hint is 12 bytes. Phone includes unknown field 7=16. |
| Band 98, 106 | Type 2; key 64, seed 32, field 3 length 16, base varint, parameters **3** in both directions. |

The field-3-as-IV interpretation now has a concrete matching schema. The public implementation distinguishes parameters **0, 7, 31**; it does not document what changes for the band's **3**. Unknown request field 7 and a general definition of every parameter bit remain unresolved. The later local native-key/MAC checks, rather than this schema parse, establish decryption for values 3 and 31.

## Candidate algorithms and exact roles

For the published **31** vector, let `S` be the raw P-256 ECDH shared secret. For a sender, `C` is the receiver's RequestEncryption challenge; `R` is the sender's EnableEncryption seed. The vectors implement:

```text
Kenc = HKDF-SHA256(IKM=S, salt=SHA256(C || R),
                  info=UTF8("AirShield"), output=32 bytes)
Kmac = HKDF-SHA256(IKM=S, salt=SHA256(R || C || UTF8("hmac_derive")),
                  info=UTF8("AirShield"), output=32 bytes)
```

TX uses remote challenge/local seed; RX uses local challenge/remote seed. **Offline validation reproduced the two published key values and packet's eight-byte HMAC: 3/3 checks passed**, using Python `hashlib`/`hmac` and the public vector constants. This verifies that example, not the live session. [Vector source](https://github.com/zhuowei/Starcruiser-mac/blob/1bc6f9418ad85a10991817c74e15a84f85078f53/key_derivation_test.swift).

The separate **7** notes use `H=SHA256(S)` as HKDF input, encryption salt `SHA256(H || C || R)`, and MAC salt `SHA256(R || C || "hmac_derive" || H)`. The notes omit the multiplexing header from the MAC input. Later local checks confirm that parameter 3 uses this encryption-key branch but reuses the encryption key as its MAC key; it does not use this separate parameter-7 MAC derivation. [Primary experiment notes](https://github.com/zhuowei/meta-ray-ban-android-app-frida/blob/6bfcf7ca873bb636bec8ff9560d3057a203c7062/notes/non_multiplexed_differences.txt).

The Swift implementation uses AES-CBC and truncated HMAC-SHA256. For 31, the MAC input is `02 02 00 00 || LE32(base) || metadata_byte || ciphertext`; wire output prepends `40` and the first eight MAC bytes. Initial directional IV/base come from the sender's EnableEncryption. **Do not copy this as a working driver:** receive uses TX keys, advances IV from plaintext, omits MAC rejection, assumes reads equal frames, and uses fixed test randomness. Its header logic and negotiation also need validation. [Inspected implementation](https://github.com/zhuowei/Starcruiser-mac/blob/1bc6f9418ad85a10991817c74e15a84f85078f53/Sources/starcruiser/Datax.swift).

## Parameter-bit limits

**No explicit parameter-3 definition was found in the pinned sources.** SimStella contains a comment attributing multiplexing to `1 << 1`, but its actual implementation treats 31 as multiplexed and 7 as nonmultiplexed. Both contain that bit, so the comment is internally insufficient and must not become a protocol constant. Its only named protocol variants are 0, 7, and 31. [Pinned Kotlin implementation](https://github.com/zhuowei/SimStella/blob/5c603b2957c8d51ba134dd51b580ee7a06d76c83/app/src/main/java/net/zhuoweizhang/simstella/MainActivity.kt).

## Relay framing: public evidence and limits

A final bounded pass found **primary evidence for a separate Relay framing layer, but no public grammar for the standalone `81 00` or `01 <length>` records**. All three previously pinned repositories were searched for relay/framing handlers; their current heads remain the October 26, 2025 commits. Their implementations handle the initial DataX headers and the encrypted `40` prefix, but do not implement the new relay/control forms observed locally. The public fork list did not expose a newer implementation in this pass.

The researcher's **October 19, 2025** app log explicitly says the RequestEncryption handler enables TX Relay framing when multiplexing is enabled; the EnableEncryption handler then enables RX Relay framing. In the same log, the app sends 26 encrypted bytes on the wire but reports a complete received frame of 25 bytes. That is consistent with one byte being consumed by an outer framing layer; it does not by itself define arbitrary relay records. [Direct first-party experiment post](https://notnow.dev/notice/AzMB113Mv5m2mwwmf2).

A separate **October 11, 2025** post identifies the Android native wrapper as `com.facebook.wearable.airshield.stream.Framing`. This matches the `airshield::stream::Framing` type seen in the local iOS inventory. [Direct first-party post](https://notnow.dev/notice/Az7D7HydWy3E12VWMa). The captured iOS string at `0x896ca80` also specifically names Substream Advertising Relay between AirShield 1.1+ devices; that is local static evidence, not a wire-format definition.

Local captures established authenticated outer-channel crypto in both band directions, plus byte-for-byte forwarding of an inner handshake between band and glasses. Those are newer local results and supersede the earlier research-only uncertainty about parameter 3. The reported `01 71 + 114 bytes` and `01 73 + 116 bytes` support a payload-length-minus-one interpretation **for those examples only**. Public research here does not establish the general length encoding, the meaning of `81 00`, stream-number bits, or control-opcode assignments. Keep outer authenticated records, relay payloads, and control records distinct; inner authentication is a separate session and is not proved by outer-channel MAC success.


### Subsequent local framing results (September 13, 2026)

Local MAC verification established these record boundaries. These are **observations from this project, not a published AirShield specification**, and refine the limits of the earlier public-source pass:

| Observed prefix | Local interpretation and evidence |
| --- | --- |
| `40` | Authenticated channel 0 record: `40 || MAC[8] || block_count_minus_1[1] || ciphertext[16 × (block_count_minus_1 + 1)]`. Every one of **850 authenticated channel 0 packets** satisfied the ciphertext block-count rule. The count byte is byte 9 with zero-based indexing. |
| `01` | Clear relay record: `01 || payload_length_minus_1[1] || payload[payload_length_minus_1 + 1]`. Subsequent authenticated-record boundaries verified this length rule in the observed stream. |
| `81 00` | Observed standalone control record. Its exact control meaning remains unresolved. |
| `41` | Observed encrypted relay/channel 1 records, forwarded byte-for-byte between peers after the forwarded handshake. The decoder preserves these as opaque records using the same block-count rule; outer channel 0 authentication does not authenticate the inner session. |

The public sample's fixed `00` byte after its eight-byte MAC therefore corresponds to **one ciphertext block** in these captures. Treating it as an arbitrary constant or metadata byte loses record boundaries for longer ciphertext. This correction comes from local authenticated packets; the cited public example happens to encrypt a 16-byte identity request.

The live parameter-3 branch was authenticated in both directions: with `H = SHA256(S)`, `Kenc = HKDF-SHA256(IKM=H, salt=SHA256(H || C || R), info="AirShield", output=32)` and `Kmac = Kenc`. This supersedes the earlier candidate-only status of parameter 3. Session secrets are intentionally omitted here.

## Community research update — 2026-10-19

This update separates source-code evidence from tests on our band (firmware
`7fada0507764+`). Earlier sections describe older firmware and historical findings.

### Sources and lineage

- **Zhuowei Zhang / Starcruiser and SimStella:** the earlier glasses work supplies
  AirShield setup, crypto vectors and DataX schema. These are transport references,
  not a complete consumer-band driver. [Starcruiser](https://github.com/zhuowei/Starcruiser-mac),
  [SimStella](https://github.com/zhuowei/SimStella).
- **Kinesis**, inspected at `5c78485f48c0758e2ce46ee11d3aaa070d827b75`, is the native
  Swift continuation of this POC. Its enrollment code and newer handwriting code
  are useful additions, but its older protocol document still describes parameter
  3 and must not be treated as the latest firmware specification.
  [Source](https://github.com/callbacked/kinesis/tree/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/KinesisCore).
- **Air Gestures**, inspected at `7de74f049f636f059f98f35772598ea5121593c2`, ports
  Kinesis into a Rust core and Linux/Android applications. Its hardware notes add
  concrete observations on changing addresses, parameter 26 and channel flags.
  [Hardware findings](https://gitlab.com/896kb/air-gestures/-/blob/7de74f049f636f059f98f35772598ea5121593c2/docs/hardware-day.md).
- **Rokid Lumen**, inspected at `4fe237668683cbe7e613e3c0121723a9f176102a`, extends
  that lineage with handwriting and a host-side writing assistant. Shared code is
  not independent confirmation. Our direct Mac recordings provide local hardware
  confirmation of the handwriting activation and output format.
  [Band core](https://github.com/beyondlevi/rokid-lumen/tree/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core/src).

### Findings that refine our understanding

**Pairing, enrollment and session authentication are different steps.** Kinesis
implements a Meta-approved ownership ceremony as well as reconnecting with an
existing owner key. The host proves ownership by signing the fresh session
transcript; cloud enrollment is not necessary on every connection. Our dashboard
uses the already-enrolled key recovered earlier and does not reset or re-enroll
the band. Kinesis can additionally verify the band's proof when it has the band's
identity public key. Our current owner-trust implementation does not perform that
peer-identity verification. Encrypted packet MAC verification and the band accepting
our owner key are not a substitute for that additional check.
[Enrollment and trust](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/docs/enrollment.md).

**Bluetooth identifiers and channel flags can vary.** Air Gestures reports private
advertising addresses changing after bond removal, and channel identifiers with
additional connection-dependent bits, routed using `channel & 0x80ff`. It also
observed full-block padding on aligned records and parameter-26 key derivation.
These are specific hardware observations, not evidence that every band uses that
routing mask. Our latest captures use ordinary channels and parameter 27 in both
directions; they have not required a routing-mask change. The dashboard's saved
CoreBluetooth UUID did become stale after re-pairing and was updated locally.
[Hardware findings](https://gitlab.com/896kb/air-gestures/-/blob/7de74f049f636f059f98f35772598ea5121593c2/docs/hardware-day.md).

**Charging can be queried over the input service.** Kinesis sends an empty
`BatteryInfoReq` as RPC field 2, with a request ID in field 1, on a separately
opened channel `0x8008`. Its decoder distinguishes an absent charging value from
false. This is a concrete extension point for live battery status without another
GATT connection; we have not tested this RPC on the current band. The dashboard
currently uses the verified GATT battery and firmware read before streaming.
[Request](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/KinesisCore/BandSession.swift),
[Decoder](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/KinesisCore/BandBatteryStatus.swift).

**The 100-class alphabet has a research source, not an official consumer protocol
specification.** Meta's research `CharacterSet` orders ASCII letters, digits and
punctuation, then backspace, enter, space, shift and `Key.pause`; the CTC null
class follows. Consequently class 98's pinch glyph represents a pause key, not
proof of emoji insertion. The research mapping also translates the right-arrow
explicit-space gesture to underscore (class 88). Kinesis's wearer tests interpret
88 as space and 87/98 as tentative boundaries. We retain that consumer
interpretation, but have not validated every special action on this firmware.
[Meta character mapping](https://github.com/facebookresearch/generic-neuromotor-interface/blob/main/generic_neuromotor_interface/handwriting_utils.py),
[Kinesis decoder](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/KinesisCore/ExperimentalHandwritingDecoder.swift).

**Better host decoding need not discard runner-up letters.** Lumen's writing
assistant preserves character distributions, averages repeated samples, searches
lexicon candidates with substitution/insertion/deletion costs, and supports
personal adaptation after confirmation. That gives a concrete route beyond our
greedy decoder for confusions such as u/v or e/l. It is Lumen's implementation,
not evidence of how Meta's app performs corrections. The dashboard deliberately
keeps literal recognized characters and explicit space events; it does not
silently apply a dictionary or the conversational guesses used in blind tests.
[Distribution handling](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/rust/writing/src/channel.rs),
[Lexicon search](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/rust/writing/src/search.rs).

### Verified locally and still unknown

The tested handwriting sequence discovers setting names, saves their values,
enables streams 4/22/23, writes collection=1/model=5, and reads both back. Our
setting IDs are **7/8**, not the reference devices' 27/28 or 28/29. Our original
values are **0/4**, not the reference default model 2. Stopping restores these
exact originals and verifies both reads and stream disable. Pipeline 3 carries
100 little-endian float32 log-probabilities per sample at roughly 6.4 Hz.

Four earlier writing recordings replay through the decoder without sequence gaps.
The pause/blank-duration spacing hypothesis was rejected by the user. Its initial
matches on two short phrases were not evidence of a protocol rule. The heuristic
has been removed from the decoder and dashboard; only explicit space classes
insert spaces. Meta's implicit word segmentation remains unknown.

The reviewed sources do **not** settle the individual semantics of stream flags
22/23, the complete meaning of boundary class 87 on consumer firmware, Meta's
implicit word segmentation, emoji-picker messages, or the latest haptic command
format. We have not claimed those gaps are solved. Next useful captures would
compare explicit space/pause gestures, emoji selection in the official app, and
handwriting entry/exit while observing both phone and band/glasses traffic.

### Handwriting wire sequence and decoding

The settings transaction sequence was adapted from [Lumen's model capture
implementation](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core/src/model_capture.rs),
then verified on our firmware. It was not recovered from our incomplete phone
capture. Kinesis is a community Mac application descended from this POC, not an
official Meta SDK; the shared source lineage above matters when judging evidence.

After the existing L2CAP/AirShield, owner-trust, and input-service setup:

1. Use service `0xce56`, request type `0x02000314`, response `0x02000315` on
   channel `0x8001`. RPC field 1 carries the request ID; arm 14 carries settings.
   Its nested arm 1 queries count, arm 2 describes candidates, and arm 3 reads or
   writes a setting. Discover `data-collection` and `data-collection-model` by
   name. Candidate IDs from references are search hints only, never write targets
   until the returned names match.
2. Read and save **both** originals before writing anything. Our IDs were 7/8
   and values 0/4. A protobuf zero may be omitted: read operation, success status,
   and scalar value require the appropriate default-zero handling. The typed
   value submessage must still exist. This fixed the initial failed preparation.
3. On channel `0x8005`, enable input stream fields 4, 22, and 23 and check their
   acknowledgement. Write collection=1 and model=5; read both back separately.
   The individual meanings of 22 and 23 remain unverified.
4. Require at least five valid pipeline-3 samples before reporting Ready and
   starting the user capture timer. Do not treat a successful write alone as
   proof that handwriting is streaming.
5. On stop, restore the saved model and collection values (4 and 0 here), read
   back both, then disable fields 4/22/23 and check the acknowledgement. Never
   substitute reference firmware's model=2 for the saved original. Cleanup has
   a bounded deadline; failed confirmation is an error, not a successful stop.

Inference message `0x0200020c` contains protobuf field 1 (sequence), field 2
(timestamp in microseconds), field 3 (packed little-endian float32 bytes), and
field 10 (pipeline). Pipeline 3 supplies 100 log-probabilities about every
156.25 ms (~6.4 Hz). We require finite nonpositive scores whose exponentials sum
to approximately one, retain the distributions locally, and greedily select the
largest score. The app displays recognized characters rather than claiming that
the band sends complete UTF-8 sentences.

| Class | Mapping used by our decoder |
| --- | --- |
| 0–25 | a–z |
| 26–51 | A–Z |
| 52–61 | 0–9 |
| 62–93 | ASCII punctuation in Python `string.punctuation` order, with the exceptions below |
| 87 | Boundary/control; no character emitted (consumer meaning not fully established) |
| 88 | Explicit space, overriding the underscore slot |
| 94 | Backspace |
| 95 | Newline |
| 96 | Explicit space |
| 97 | Shift for the next emitted character |
| 98 | Pause/boundary; no character emitted |
| 99 | CTC blank |

Greedy CTC collapses consecutive identical predictions and removes blanks. For
example, top classes `7, 7, 99, 8, 99, 96, 99, 26` produce `hi A`: 7 is h,
8 is i, 96 is an explicit space, and 26 is A. A blank between two identical
letters permits both letters; its duration never creates a space. Special-class
handling follows research/community mappings and is not a claim that all 100
classes have been individually elicited on this consumer firmware.
# Standby investigation (2026-10-19)

Initially prepared from public evidence; the physical trial below now verifies
the core behavior on our band. The public starting points were
[Kinesis issue 11](https://github.com/callbacked/kinesis/issues/11#issuecomment-6151575420)
and Lumen's subsequent implementation. Kinesis's author identified a device-state
request in Meta's client: RPC field 5 contains configuration field 6, with value
1 for standby and 2 for active. Kinesis's current source at
`5c78485f48c0758e2ce46ee11d3aaa070d827b75` has no standby controller.

[Lumen's implementation](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core/src/session.rs#L747)
sends that request on the input service. Its comments and beta.25 changelog report
that ordinary gestures and their vibrations stop; middle-finger double tap wakes
the band but is consumed locally. The next gesture reaches the host. Its reply
handler logs status and configuration rather than independently verifying the
power state.

[Lumen's screen handling](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/app/src/main/java/dev/lumen/glasses/BandRuntime.kt#L267)
also disables motion separately and keeps the gesture subscription enabled in
normal standby. Its stronger power-saving option disables gestures too. These
are distinct operations; neither silence nor a successful RPC measures battery
savings. Whether EMG acquisition, inference or radio duty cycle changes remains
unknown. A search of
[Air Gestures](https://gitlab.com/896kb/air-gestures/-/tree/7de74f049f636f059f98f35772598ea5121593c2)
found no additional standby implementation.

## Interface and initial experiment

Use the existing authenticated L2CAP/AirShield input-service connection: service
`0xce56`, request type `0x02000314`, reply `0x02000315`. Our configuration channel
is `0x8007`; its number is a local routing choice. Example plaintext RPC payloads:

```text
08 06 2a 02 30 01    request 6: standby
08 07 2a 02 30 02    request 7: active
```

Reply field 1 correlates the request, field 2 is status (observed success 1),
field 6 contains configuration, with nested field 6 potentially echoing state.
An echo is not an independent measurement of standby.

The separate named settings include `stream_in_standby`,
`auto-standby-timeout-secs`, `standby-gesture`, `wake-gesture`,
`middle-wake-enabled`, and `keep-alive`. Their numeric IDs change across firmware;
resolve by name before any future experiments. Their effects and enum values
are not established here. The first test leaves them unchanged.

```sh
python instrumentation/mac_band_probe.py BAND_UUID \
  --identity-key LOCAL_OWNER_PEM --query-device-info \
  --stream-control dial --seconds 90 --standby-after 15 \
  --output captures/standby-trial-UNIQUE.jsonl
```

The timer starts when motion arrives. After a baseline with confirmed hand and
stream subscriptions, it requests standby at 15 seconds, then active eight
seconds before the end, then disables streams. Ctrl-C also schedules active
recovery if standby was sent. Recovery is best effort: a broken transport or
process failure can prevent it. Failed/missing standby or recovery acknowledgements
produce an unsuccessful exit. The test does not change the band's hand.

During baseline, try index taps and swipes. After the standby reply, repeat those
without a middle double tap and note vibrations. Then perform one middle double
tap, pause, and try index taps again. Compare gesture and motion counts across
these intervals in the JSONL capture. Keeping motion subscriptions unchanged
isolates the effect of the device-state request. A later separate trial can
disable motion as Lumen does. Battery savings require a longer controlled test.

Close other band clients before connecting, including clients in other worktrees
(the existing connection lock is local to each checkout). Runtime imports and
saved local connection material were checked; no hardware connection was made
during preparation. Synthetic protocol tests verify request bytes, response
correlation, rejection, timeout, and active recovery; they do not verify device
behavior.

## Physical standby trial (2026-10-19)

Two local captures used the already enrolled identity and AirShield parameter 27
in both directions on PSM 129. Both accepted standby (`status=1`, echoed state 1),
accepted active recovery (`status=1`, echoed state 2), acknowledged all stream
disables, and disconnected cleanly. No named wake/timeout/stream-in-standby
settings were changed. Firmware identity was not independently decoded during
this trial; do not assume an older firmware identifier from previous sessions.

The repeat capture `captures/standby-trial-20261019T164549Z.jsonl` established:

| Phase (UTC) | Band/host observation | Wearer observation |
| --- | --- | --- |
| Baseline, 16:46:14–16 | Exactly three index `singleTap` events | All three taps vibrated |
| Standby acknowledged, 16:46:37.735 | State 1 echoed; no gesture events before wake | Three attempted index taps did not vibrate |
| Wake, then index taps at 16:47:20–21 | Exactly three more index `singleTap` events; no middle `doubleTap` event | One middle double tap, then three index taps; vibration returned |
| Recovery, 16:47:37.060 | Active state 2 acknowledged | No further action requested |
| Shutdown, 16:47:42–45 | Gesture/gyro/orientation disables acknowledged; clean disconnect | — |

This supports a device-side standby gate and a locally consumed wake gesture,
not merely host-side filtering. The first capture,
`captures/standby-trial-20261019T164334Z.jsonl`, is supplementary: the wearer
reported two middle double taps followed by single taps, while only one middle
double-tap event reached the host. Its pre-standby gesture baseline was missing,
so use the repeat for the primary behavioral conclusion.

Gyro streaming was **not stopped by standby** with the existing subscription
enabled: 2,560 gyro samples over 20 baseline seconds (128 Hz), 4,095 over 32
seconds after standby and before wake (~128 Hz), and 1,920 over 15 seconds after
wake (128 Hz). Orientation was silent during that standby window and returned
briefly around later gestures, but it also became silent before the explicit
standby request in the repeat. Its behavior cannot be attributed solely to the
standby command; inactivity or another gate remains possible.

For host integration, retain the gesture subscription for wake detection and
separately disable unneeded motion streams if reducing traffic is the goal.
The first delivered gesture after a local wake may need to activate the host UI;
do not depend on receiving the waking middle double tap itself. Battery/current,
raw EMG, automatic standby timeout, and other firmware remain untested.

The repeat's early stop also exercised graceful signal handling: active recovery
was sent and acknowledged before stream shutdown. Capture files contain session
material and remain ignored/local.
