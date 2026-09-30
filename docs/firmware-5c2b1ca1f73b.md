# Firmware 5c2b1ca1f73b+ investigation

Status on 2026-09-30: **direct Mac owner authentication, device info, wrist
motion, recognized gestures, and raw EMG streaming work on firmware `5c2b1ca1f73b+`**, using an
already enrolled owner identity recovered from the user's rooted Android.
Index/middle presses, releases, and holds were subsequently observed. Context:
[issue #6](https://github.com/callbacked/neural-band-poc/issues/6).
The sections below preserve the investigation chronology; final hardware
results appear under “Direct Mac validation completed.”

## Enrollment challenge control, 2026-09-30 06:35 UTC

The user reports that the band was unpaired from Meta AI. The local dashboard
stores only its name and CoreBluetooth identifier, not an enrolled owner key.
A bounded challenge request to service 0x24, message `0x02002000`, on a fresh
channel returned **`0x02002001` with protobuf field 1 containing a 16-byte
nonce**. The session authenticated three RX records and remained open to its
deadline. No ownership-change request or account request was sent.

This confirms the first device-side enrollment step remains available on the
parameter-26 band. It does not establish whether an existing owner remains,
whether Meta will authorize a new enrollment, or whether completed legacy
trust will unlock sensor access. The next test requires implementing the
account-backed receipt exchange and having the user sign in, then explicitly
reviewing any operation that replaces an existing owner identity.

Local capture: `captures/android-research/enrollment-challenge-20260930.jsonl`.
The nonce is transient and must be obtained again for an actual enrollment.

## Registration and legacy trust follow-up, 2026-09-30

Further Android static analysis narrows the missing state:

- `ManifestCapabilities` (classes4.dex) defines field 1 as the enum
  `canSendManifest`, not a bool. Our band's nested `08 02` therefore means raw
  enum value 2. Its symbolic value names were not recovered; calling this
  true/false would be an unsupported interpretation. The diagnostic now emits
  `can_send_manifest_raw` and preserves unknown values. All 68 tests pass.
- The SDK registrar generates a fresh app signing key when none is stored,
  persists it, and passes its public key in `AppRegisterRequest` to Meta AI.
  This does not require extraction of Meta AI's private key in the observed
  SDK path. It is not yet a demonstrated registration route for this Mac.
- `ACDCServiceBinder.A01` resolves the caller's package through `LX/1By.A06`.
  That searches built-in and configured app records, including `dat_apps`
  preferences. Thus calling Binder alone does not establish eligibility.
- `ManifestManagerImpl` (`LX/FeR`) adds an app's public key to its manifest,
  increments the version, builds and stores the updated manifest, and sends
  it to connected devices. SDK registration returns manifest bytes through
  a `ParcelFileDescriptor` pipe. This locates the authority for provisioning
  in the companion app, rather than in a generic BLE-pairing operation.
- The generated `ManifestFileComplete` schema (classes6.dex) has field 1
  `authorityPubKey`. Its use in the band's observed empty type-4 response has
  not been established. Do not reinterpret every completion payload as this
  protobuf: the inspected SDK type-4 handler appends raw transfer bytes.

A bounded offline test tried the two certificates returned by legacy identity
read (fields 1 and 5) against the Constellation proof using the documented
receive transcript digest. Neither verified; neither public-key SHA256 prefix
matched the offered eight-byte key tag. This is a negative result for those
specific keys/digest, not proof that the signing algorithm differs.

### Legacy identity control on hardware

A new, intentionally unregistered P-256 identity signed the documented host
transcript digest. The probe sent `[0x81000024, 0x02001000]` on channel `0x8004`,
with identifier `SHA256(raw identity public key)` and a raw 64-byte signature.
The band returned **`0x03001043`** on channel 4, with empty payload. This matches
the documented *invalid app identity* result. The session stayed open until its
deadline and received three authenticated packets.

This demonstrates that the legacy trust entry point is present and rejects
an unregistered identity. It does not verify a successful trust exchange or
prove that legacy enrollment will unlock input services on this firmware.
No ownership-change requests were sent, no account login was attempted, and
no private identity was imported. The control remains an ignored research
script because it cannot establish trust and should not be an app default.

Evidence: `captures/android-research/legacy-trust-control-20260930.jsonl`,
`legacy_trust_probe.py`, `check_constellation_certificate.py`,
`registration-trace.txt`, `registration-trace-rest.txt`,
`app-registration-checks.txt`, and `manifest-manager.txt`.

The public Kinesis reference was inspected at commit
[`d900b7311398cd6609582038a85fea4b45a5eb45`](https://github.com/callbacked/kinesis/tree/d900b7311398cd6609582038a85fea4b45a5eb45).
Its AirShield implementation still supports parameter 3 only; it is a source
for legacy enrollment, not a ready fix for this band's parameter-26 transport.
Meta's official [Android](https://github.com/facebook/meta-wearables-dat-android)
and [iOS](https://github.com/facebook/meta-wearables-dat-ios) DAT SDKs offer
mobile app registration, but their existence does not establish a supported
standalone-band/raw-EMG or transferable-to-Mac credential path.

The next decision depends on existing pairing: use an authorized app identity
or investigate supported developer registration while preserving the current
pairing, versus an explicit ownership/enrollment change. A physical Android is
not proved necessary. We need the user's pairing state before choosing any
path that could replace their existing owner identity.

## Constellation authentication identified, 2026-09-30

Service `0x4f` is `ConstellationAuthentication`, established directly by the
Android constructor's `Service(79)` call. `com.meta.constellationauth.EnableTrust`
and its generated schema map the observed payload:

| Field | Meaning | Observed |
| --- | --- | --- |
| 1 | key_tag | 8 bytes |
| 2 | signature | 64 bytes |
| 3 | manifest_version | 8 |
| 4 | key_hint | absent |
| 5 | client_version | absent |
| 6 | subscope_type | absent |
| 7 | manifest_capabilities | nested bytes `08 02`; meaning not decoded |

The app's `handleEnableTrustReceived` compares manifest versions. When the
peer has a newer manifest, it sends `NEED_MANIFEST`, custom result 3. When
versions match and are nonzero, it finds the peer public key by key tag in the
manifest and verifies the signature against the receive challenge hash.
The send path signs the transmit challenge hash using a stored app private key.
It explicitly fails when that key is unavailable. These keys are distinct in
role from the fresh ephemeral ECDH keys used to encrypt transport.

The registration delegate `LX/FeG;` uses Android Binder action
`com.meta.wearable.acdc.service.ACDCService.BIND`, targeting `com.facebook.stella`
or its debug variant, and calls `registerLinkableApp`. This identifies an
app registration route, not a verified Mac enrollment implementation. The
SDK manifest loader also requires a stored public verification key and an app
private key when loading device records. No such identity material has been
obtained for this Mac client.

Recovered service message IDs (`LX/Ffd;`): EnableTrust=1, transfer-data=2,
transfer-done=3, transfer-complete=4. Custom results (`LX/Ffe;`): failure=1,
invalid-manifest=2, need-manifest=3, invalid-peer=4, manifest-out-of-date=5.

### Fresh hardware checks

1. Adding a second random UUID as EndLinkSetup field 3 still caused stream
   closure after two authenticated records. The published
   [ATC schema](https://github.com/zhuowei/SimStella/blob/5c603b2957c8d51ba134dd51b580ee7a06d76c83/app/src/main/proto/com/oculus/atc/atc.proto)
   and current native parser establish that field's existence, but this control
   shows that simply supplying it does not solve setup. No production UUID
   behavior was changed based on this negative result.
2. Replying on the band's opened channel (clear its high bit) with
   `0x03000003` elicited `0x02000004` (transfer-complete) with **zero payload
   bytes**, followed by another EnableTrust offer with manifest version 8.
   No transfer-data records preceded completion. This was reproduced in two
   fresh sessions, including the integrated diagnostic. Both connections stayed
   open to their deadlines and received four authenticated records.

Empty completion is not a usable manifest, does not verify identity, and does
not establish why the band withheld data. Possible protocol/version or missing
registration requirements remain hypotheses. No trust-accepted reply was sent,
no owner state was changed, and no sensor data was obtained.

`mac_band_probe.py --query-manifest` now performs this bounded diagnostic:
it requests once, summarizes the offer without printing keys/signatures,
limits manifest accumulation to 1 MiB, and distinguishes empty, incomplete,
and completed transfers from verified identity. It deliberately does not
implement trust acceptance or registration. All **66 instrumentation tests
pass**, and the integrated option reproduced the live result.

Local evidence: `captures/android-research/link-uuid-20260930.jsonl`,
`manifest-request-20260930.jsonl`, and `manifest-diagnostic-20260930.jsonl`.
The same ignored directory contains `constellation-dex.txt`,
`auth-dependencies.txt`, and `setup-xrefs.txt`. Native parsing checks are at
ELF VAs `0xe6a270` (UUID) and `0xe6a298` (link UUID); these addresses apply only
to the exact library hash recorded below.

Next: trace the companion app's registration provider and the manifest
capability variant. A successful official-app capture can establish the
missing sequence and key provisioning, but a plain packet capture may not
expose the stored signing keys. Android is helpful, not established as a hard
requirement; further static work can still proceed on the Mac. Do not promise
sensor access merely from implementing these diagnostic messages.

## Working Mac transport, 2026-09-30

Fresh controls identified the difference from the earlier failed experiments:

| Host offer | Request field 7 | Host enable | Band RX result |
| --- | --- | --- | --- |
| 3 | 16 | 3 | No candidate authenticated the first packet |
| 31 | 17 | 26 | Parameter-26 candidate authenticated |
| 31 | 16 | 26 | Same candidate authenticated |
| 27 | 16 | 26 | Same candidate authenticated |

Earlier saved host-offer-3/enable-26 experiments also failed to authenticate
band RX. The evidence supports using offer 27 and enable 26, without changing
request field 7. It does not completely explain the band's negotiation logic.

For raw 32-byte P-256 ECDH secret `S`, receiver challenge `C`, and sender seed
`R`, the verified parameter-26 transport is:

```text
K = HKDF-SHA256(IKM=S, salt=SHA256(C || R), info="AirShield", length=32)
Kenc = Kmac = K
MAC = HMAC-SHA256(K, 02020000 || LE32(counter) || block_count_minus_1 || ciphertext)[:8]
```

AES-256-CBC uses the sender's enable IV, then the preceding record's last
ciphertext block. Counter advances once per authenticated record. This matches
the native-app-derived candidate described below and authenticates independent
fresh band replies. It is transport authentication, not owner/device identity
verification; no companion-app key trace was obtained for this build.

Active controls after setup:

- Identity query only: two authenticated RX records, including an identity
  response containing certificates. Connection remained open until the probe
  deadline.
- Identity plus device-info query, without EndLinkSetup: three authenticated
  RX records. The device-info channel returns result word `0x0300c001` with an
  empty payload, not device information. Connection remains open to deadline.
- Identity, legacy EndLinkSetup, and device-info query: two authenticated RX
  records, then the band ends the stream. No device-info response or samples.

The unsolicited first packet opens service `0x4f` on observed channel `0x9d03`,
with message `0x02000001`. Its payload has byte fields 1 (8 bytes), 2 (64 bytes),
7 (2 bytes), and integer field 3 equal to 8. The subsequent Constellation analysis above identifies this offer and a
manifest-request reply. This and the changed link setup are the next investigation
points; do not treat certificate retrieval as completed trust establishment.

The active probe now advertises 27, selects TX 26 when offered, falls back to
3, and accepts only RX 3/26. The offline decoder also supports 26. Existing
PSM discovery is preserved. Synthetic tests cover both handshake modes,
parameter-26 key reuse, MAC-prefix enforcement, split/coalesced records,
chained IVs, counter wrap, corrupted tags/ciphertext, and unsupported selection.
All **60 instrumentation tests pass**.

Local captures are under ignored `captures/android-research/`:
`fresh-reply-native-offer-20260930.jsonl`,
`fresh-reply-control16-20260930.jsonl`,
`fresh-reply-offer27-20260930.jsonl`,
`active26-identity-only-20260930.jsonl`,
`active26-info-only-20260930.jsonl`, and `active26-info-20260930.jsonl`.
These contain session secrets/certificates and are not publication artifacts.

The sections below preserve earlier negative results and static-analysis
provenance; their former blockers are superseded by these fresh controls.

## Evidence collected locally

- The existing local PSM change works: the band advertises 129 and CoreBluetooth
  opens that channel successfully.
- Four saved sessions contain RequestEncryption with supported parameters 27,
  EnableEncryption with parameters 26, and a subsequent 106-byte RX chunk.
  Under the existing framing interpretation, that chunk is marker `0x40`, an
  eight-byte tag, metadata `5`, and six 16-byte blocks. This shape alone does
  not establish the cipher, tag construction, or plaintext.
- The old active probe advertises 31 despite implementing only 3. A fresh
  hardware experiment advertised 3 and sent EnableEncryption with 3. The band
  still sent EnableEncryption with 26. Merely narrowing the offer does not
  restore compatibility. This also leaves the exact negotiation semantics
  unresolved; do not infer them solely from bitwise intersection.
- That experiment stopped before encrypted queries and is saved locally as
  `captures/parameter3-negotiation-20260929.jsonl` (14:19:51–14:19:54 UTC).
- An additional offline check of five direct-SHA256 key candidates, with both
  existing MAC prefixes, matched none of the four saved RX tags. This is a
  bounded negative result, not proof that a new KDF or cipher is required.
  The issue author's larger candidate search was not independently reproduced.

At that stage, the probe advertised only its implemented mode. It allowed a capability
superset containing 3 to reach the enable exchange, but continued to reject
an actual selection other than 3 before deriving keys or sending queries.
Regression tests cover those boundaries and the existing authenticated flow.
The PSM fix predated this investigation and is preserved.

## Earlier proposed evidence collection

Capture a **successful** official companion-app connection to this firmware.
Record phone platform, Meta AI version/build, and band firmware. Preserve raw
bidirectional stream chunks, all setup fields, and chunk ordering. Prefer two
fresh connections so a candidate formula can be checked independently.

With instrumentation available, correlate the app's ECDH result, directional
challenge/seed/IV/base, selected parameters, derived encryption/MAC keys, and
crypto call sites with that exact connection. This distinguishes changes to
key derivation from changes to record authentication or negotiation. Failed
Mac transcripts alone do not uniquely determine the algorithm.

The existing iOS key observer requires Meta AI 269.1.0 / 948093709 and validates
native instruction/string anchors. Do not remove its checks or assume its
offsets apply to another build. Android requires a separate observer. See
[capture tools](capture-tools.md) for the existing iOS workflow.

The original plan was to validate parameter 26 against official-app keys and
captured traffic. Fresh direct-band MAC checks above now independently verify
the static-analysis candidate without those app keys. Verify both directions,
multiple consecutive records, split/coalesced chunks, and rejection of changed
tags before trying the normal identity and input-service startup. Keep session
material in ignored local captures; commit only synthetic/public test vectors
and derived findings.

## Mac-only static analysis, 2026-09-30

Obtained the Android Meta AI **292.0.0.19.164**, version code **969202220**,
ARM64 package from [this APKMirror listing](https://www.apkmirror.com/apk/facebook-2/facebook-view/meta-ai-292-0-0-19-164-release/meta-ai-292-0-0-19-164-3-android-apk-download/).
The package was unpacked and inspected, not installed or launched. All package
files and raw disassembly remain in ignored `captures/android-research/`.

Provenance:

| Artifact | SHA256 |
| --- | --- |
| APKM bundle | `088f805dc7435bc4f2632f66a7635ff97fc937222e10d4b528bc185cd00b6314` |
| base.apk | `02e8e80061bbb5f0e23080e9e208a04f7bf5786ac815d28c755681237fbb3899` |
| ARM64 split | `228aee42e58c7ff1b1ce1f38305ef51a0fb8bc956c850e969b386a77c90758d0` |
| libstartup.so | `b2d525e66d66af71997e9a514a3c733b3009304072b7eab4c0aa87cbc3ee9a60` |

Both APKs contain a v2 signer certificate with SHA256
`81b04887e8eb8a209f2e5e4042adcf696bf751e99abdbda132b66167fdca9431`,
matching the previously published Stella certificate fingerprint. Certificate
extraction is **not** full APK signature/content-digest verification. The parsed
base manifest identifies `com.facebook.stella` and the version above.

### Native locations and inferred branches

These are ELF virtual addresses in this exact library, not portable Frida offsets.
The stripped library has no named AirShield dynamic symbols, but retains JNI
class names and the `hmac_derive` string. ARM64 ADRP/ADD references lead from
that string to an outlined helper and then the derivation routine.

| Address | Observation |
| --- | --- |
| `0xfe7e5` | `hmac_derive` string |
| `0xf79970` | Outlined helper loads its pointer and length 11 |
| `0xe5f2e8` | Cipher-builder derivation routine; receives cached ECDH material |
| `0xe69dd0` | Peer enable parsing writes counter and option fields |
| `0xe72c9c` | HKDF-shaped extract/expand routine, default `AirShield` context |
| `0xe73400` | Shared-secret computation and 32-byte integer serialization |

The enable parser maps bit 0 to internal byte 4, bit 2 to byte 5, and bit 4
to byte 6 of the parameter structure (counter occupies bytes 0–3). Bit 3
sets framing fields; a nonzero separate protobuf quirks value populates byte 9.
The derivation routine reads those fields independently:

- Byte 6 controls raw versus hashed shared-secret input and whether the
  shared-secret hash is included in the encryption salt.
- Byte 5 controls the separate `hmac_derive` branch versus key reuse.
- Byte 4 or byte 6 enables the HKDF branch.
- Byte 9 equal to one selects a 136-byte alternate context at `0x2b53ce`:
  `b"AirShield" + bytes(119) + bytes.fromhex("2000000000010000")`.
  Otherwise the HKDF helper uses the ordinary nine-byte context. This is an
  observed app branch, not evidence that the band enables that option.

This suggests a parameter-26 candidate of the known parameter-31 encryption
derivation with that encryption key reused as the MAC key. It is an inference
from the Android app, **at that point not a verified firmware-26 formula**. Other configuration
paths and firmware/app differences remain possible.

### Offline results

`instrumentation/check_airshield_candidates.py` reconstructs each direction's
setup from concatenated chunks, checks captured byte counts and local material
against the wire, then evaluates six named key candidates with each of the two
existing MAC prefixes. It never enables a new live mode or emits candidate
plaintext/session keys. It reports packet authentication separately from stream
completeness; an empty stream is not positive evidence.

The four captures ending `133531108792`, `133604548027`, `133614341170`, and
`133745154189` yielded:

- Host TX: respectively 6, 6, 4, and 4 authenticated packets using the
  shared-modern-key candidate and prefix `02020000`.
- Band RX: zero authenticated packets for every tested candidate, including
  the alternate 136-byte contexts.
- The captured host offers are already 3, and both enable selections are 26
  in these earlier experimental sessions. Their successful TX MAC checks only
  confirm the host experiment's implementation; they do not prove band support
  or independently verify that its ECDH result agrees with the host's.

The complete local report is `captures/android-research/candidate-results.json`.
Example command (supply the other three paths to reproduce the full report):

```sh
.venv/bin/python instrumentation/check_airshield_candidates.py \
  captures/mac-band-probe-dashboard-20260929T133745154189.jsonl \
  --output captures/candidate-check-new.json
```

Four new tests verify the public parameter-31 MAC vector uniquely identifies
its candidate/prefix, corrupted tags and partial frames fail, empty input is
not a match, and setup truncation/order errors are rejected. All 59
instrumentation tests pass. The project's pinned cryptography 46.0.3 was
restored after installing local research dependencies.

A 12-second fresh Mac connection attempt at 04:53 UTC did not connect and
received no setup bytes. Its capture is
`captures/android-research/fresh-handshake-20260930.jsonl`; it cannot test a
crypto hypothesis. No encrypted commands were sent by that research probe.

The fresh-band controls at the top now resolve the transport candidate. Next:
identify the service-0x4f exchange and the required link/identity setup, then
verify input-service access. An official-app connection capture would still
help with that sequence; it is no longer required to establish the transport KDF.

## Rooted Android native capture (2026-09-30)

Meta AI Android 290.1.0.42.163 on the owner's NE2211/Android 15 now provides
an observable official connection. Frida Java method replacement crashed in
ART; native-only `Interceptor` hooks with matched Frida 17.15.5 recorded traffic.
The observed `libstartup.so` SHA-256 is
`657b37d5ee16c0abdb31399a212c2af1cb9bea21495d668f8f4150d60e46f38f`.
`capture_android_native.js` is specific to that library and checks JNI table
pointers. It observes direct-buffer JNI inputs, native-to-Java buffers, and a
bounded number of ephemeral ECDH cache outputs. It does not change app traffic.
Raw captures and the user's enrolled identity remain in ignored local storage.

Two band connections in `native-reconnect-complete.log` establish:

- App TX selects 27; band TX selects 26. The observed parameter-27 packets use
  the same HKDF and MAC prefix as 26. All 76 captured band TX packets passed MAC
  verification and decrypted; 348 glasses TX packets also verified with 31.
- The app opens service `0x24`, type `0x02001000`: field 1 is SHA-256 of its
  enrolled P-256 public key (64-byte X||Y), field 2 is a 64-byte r||s signature,
  and field 3 is role 2.
- The signed digest is
  `SHA256(SHA256(peer_challenge || peer_public) || SHA256(local_seed || local_public))`.
  Both observed signatures verified independently with the identity's public key.
- The band accepts the app's proof with `0x03001000` on the corresponding
  response channel. The app also acknowledges the band's service-0x24 offer.
- The app answers the service-0x4f Constellation offer with `0x0300c001` and still
  successfully queries device information. A Constellation manifest is therefore
  not required for this observed paired-phone path.
- The app waits for trust acceptance and the peer's EndLinkSetup before sending
  its own EndLinkSetup, with field 1 = 1 and two 16-byte fields (2 and 3).
  The two UUIDs' semantics remain unverified. The prototype generates fresh UUIDs.

Capture limits: the RX analysis verified 41 band and 1127 glasses packets, but
357 later RX packets did not match the tracked MAC states. They were excluded;
this is not a complete decrypted capture. One band DataX session ends with an
incomplete frame. Authentication claims above use complete MAC-verified frames
from the beginning of both sessions, not partial or unauthenticated data.

`mac_band_probe.py --identity-key /absolute/path/to/local.pem` is an opt-in
prototype for an already enrolled identity. It uses role 2, waits for both trust
acknowledgement and peer setup before sending requests, and fails on rejection.
It never enrolls, unpairs, or resets a device. Acceptance of our identity does
not verify the peer's identity. The first Mac attempt could not connect and a
fresh scan found no band; subsequent successful validation is recorded below.

### Direct Mac validation completed

After the glasses were powered off, an unnamed FD5F advertisement exposed the
same firmware `5c2b1ca1f73b+`, battery 69%, PSM 129, and resolved to Meta Band
00Z9 when connected. Its CoreBluetooth identifier had changed after pairing.

The Mac's enrolled-owner proof was accepted immediately. Initial input queries
were silent while the OnePlus remained BLE_ON with a GATT link open. Stopping
Meta AI and disabling background Bluetooth scanning brought Android to OFF.
The next Mac session returned a successful device-info response.

EndLinkSetup state field 1 may be omitted (protobuf default 0) or contain 1;
accept both. Do not treat the omitted field as malformed. Its precise enum
semantics are not yet documented.

Hardware results in ignored `captures/oneplus/paired-session/`:

- `mac-owned-info-v5.jsonl`: owner trust accepted; device info succeeded.
- `mac-owned-dial.jsonl`: 323 authenticated packets, 2818 motion messages,
  right-hand setting confirmed, stream-disable acknowledgement received.
  No gesture events were observed during that interval.
- `mac-owned-emg-v2.jsonl`: 196 authenticated packets, 890 EMG batches /
  14240 sample frames; 14 missing batches reported; disable acknowledged.

Raw EMG exposed a full-block padding case: sixteen 0xd0 bytes, including at a
fragment boundary. DataXStream now strips padding lengths 1 through 16.
The failed earlier recording replays as 76 batches / 1216 sample frames with
no gaps after this fix. Synthetic tests cover both complete and fragmented
DataX frames followed by a full padding block.


## Gesture confirmation and handoff, 2026-09-30

The user confirmed gestures became visible in the dashboard. The session
`captures/mac-band-probe-dashboard-20260930T163329747567.jsonl` contains
index/middle press and release events and derived hold events. Its final
interaction state reports 962 gesture messages and 2499 dial steps. Gesture
messages include raw and derived events, so this is not a count of distinct
physical gestures. The session ended normally; press Start to reconnect.

The local dashboard maps each selected band UUID to its own private owner PEM
through ignored `captures/dashboard-identities.json`. Keep the glasses and
phone Bluetooth off for the verified direct-Mac setup. Keys and raw captures
remain local and ignored; they must not be added to Git.

### What is still unknown

We have not established that the newer firmware inherently requires an owner
key for sensor access. Earlier no-key failures and later owner-key successes
also differed in competing phone/glasses connections and pairing state. A
controlled no-key versus owner-key comparison under identical radio conditions
has been proposed but not performed. Do not present enrollment as the only
possible route or infer behavior for all devices from this band.

Root-free enrollment is deferred at the user's request. The repository's
[enrollment flow](enrollment-flow.md) and the maintainer's
[Kinesis app](https://github.com/callbacked/kinesis) provide a reference for
Mac-generated P-256 identity, Meta sign-in, and signed ownership receipts.
The challenge request works on this firmware; the complete server/band
ceremony has not been validated here. A future ownership-changing hardware
test may require unpairing/resetting the band and should be distinguished from
building and testing the implementation without changing the current pairing.

### Git and upstream PR

[PR #7](https://github.com/callbacked/neural-band-poc/pull/7) targets upstream
main and references [issue #6](https://github.com/callbacked/neural-band-poc/issues/6).
It contains transport, optional owner trust, unnamed-band discovery, DataX
padding, tests, and concise usage documentation. It excludes dashboard changes
and research instrumentation. Its isolated suite passed 65 tests, including a
simulated authenticated startup; hardware results came from the full local
working copy. The PR currently uses a closing reference to issue #6, but the
broader root-free connection problem remains unresolved as described above.

The full local working copy remains on `main` at
`/Users/arpitsaxena/random/neural-band-poc`. Its dashboard, protocol, tests,
and research changes are included in the local main checkpoint containing
this note. They have not been pushed to upstream main. The PR is committed separately as `437db32` on
`codex/firmware-26-owner-trust` in the sibling worktree
`/Users/arpitsaxena/random/neural-band-firmware-pr`, and pushed to the user's
fork. Do not reset the original working copy to the minimal PR branch: that
would discard the broader local work. Before the PR isolation, the full local
suite passed 77 instrumentation tests and 4 dashboard tests.
