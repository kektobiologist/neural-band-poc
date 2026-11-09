# Mac owner enrollment

The enrollment command obtains a new owner identity directly from the Mac.
It uses Meta sign-in and signed ownership receipts instead of extracting a key
from Android. Based on [Kinesis](https://github.com/callbacked/kinesis), pinned
source snapshot `5c78485f48c0758e2ce46ee11d3aaa070d827b75`; adapted code is MIT
licensed, with attribution in `instrumentation/licenses/kinesis-MIT.txt`.

## Default connection method

**Reuse the existing Mac-enrolled Keychain identity for normal connections.** Enrollment is
setup/recovery, not a step to repeat at each connection. Android/ADB/root/Frida
key extraction in older research notes is no longer the operational workflow.
Do not unpair or factory-reset a working band as routine setup.

## Current local identity — verified November 9, 2026

| Item | Saved value |
| --- | --- |
| Band | Meta Band 00Z9 |
| Mac CoreBluetooth UUID | `ABCBABE4-D7A6-4B05-BB42-E675678CFABA` |
| Owner key | macOS Keychain service `local.neural-band-poc.identity` |
| Active reference registry | `~/Library/Application Support/NeuralBand/identities.json` |
| Keychain session | service `local.neural-band-poc.meta`, account `session` |
| Enrollment status log | `captures/enrollment-20261109T155544Z-6799d160.jsonl` |
| Successful sensor capture | `captures/enrollment-stream-check-20261109T1556.jsonl` |

The registry and compiled identity helper live outside Git worktrees. Other
worktrees on this Mac automatically use the same active identity. The registry
contains only a `keychain:BAND_UUID:PUBLIC_KEY_SHA256` reference, not a secret.
On another Mac, its Keychain and CoreBluetooth UUID differ; these references
alone do not transfer the private key.

The account used in the successful login was accepted by both Meta's ownership
service and the band; do not infer that the earlier stalled login requires
Android or a VPN. The stall was the unhandled `oculus` callback scheme.

## Run

Use the project's Python environment and install `requirements.txt`. Xcode
command-line tools are needed to compile a small Swift/AppKit/WebKit login
helper on first use. No additional Python dependency is required.

```sh
python instrumentation/enroll_band.py --prepare
python instrumentation/enroll_band.py --login-only
python instrumentation/enroll_band.py
# Or choose an exact CoreBluetooth UUID:
python instrumentation/enroll_band.py BAND_UUID
```

Sign in with the Meta account that owns the band. Put the band in pairing mode
after login; accept any macOS Bluetooth pairing prompt. Without a UUID, the
command requires exactly one nearby band. Stop the dashboard's active stream
before enrolling.

Enrollment changes the band's owner app key and may invalidate the key used
by the phone or another client. The command does not factory-reset or unpair
the band. If Meta reports the wrong account, use `--login` to sign in with
the owner account. A factory reset is a separate manual action, not an
automatic recovery step.

## Storage and success

- Meta session: macOS Keychain service `local.neural-band-poc.meta`. Sign-in
  occurs in a native WebKit window; its title shows the page's current host.
  Tokens are passed privately to the Python process and excluded from logs.
  The private `captures/meta-login-status.log` records navigation hosts and
  stages for debugging a stalled login; callback query strings are not logged.
- Owner key: a separate immutable Keychain item for each candidate, stored and
  read back **before** any ownership request. The item stores the P-256 scalar
  as a generic password, accessible while unlocked on this Mac. This is
  encrypted Keychain storage, not a Secure Enclave or non-exportable key.
  The Python client reads it through a private pipe into memory for signing;
  key bytes never appear in command arguments or logs.
- Recovery metadata: ignored JSON under `captures/identities/` records the
  reference, UUID, ceremony state and optional band public key. The client
  checks that the band accepted our owner key; it does not verify the band's
  signature.
- After fresh owner authentication succeeds, the durable registry is activated
  and the checkout dashboard mapping is updated with the reference.
  `--no-dashboard` leaves both mappings untouched. Failed candidates remain
  available in Keychain without replacing the active identity.
- Keychain access errors stop the connection. Unlock or grant access to the
  identity helper if macOS asks; do not re-enroll to fix a storage error.

Normal probes, haptics, recording and the dashboard resolve the active identity
automatically. An explicit `--identity-key` accepts a Keychain reference or a
legacy PEM for migration. Firmware provisioning also accepts the reference,
but necessarily writes a private ignored header for the embedded device.

```sh
python instrumentation/mac_band_probe.py BAND_UUID \
  --query-device-info --seconds 35 --output captures/owner-check.jsonl
```

## Recovery

If the connection drops after ownership changes, keep the printed recovery
Keychain reference. First try it without another ownership change:

```sh
python instrumentation/enroll_band.py BAND_UUID \
  --verify-key keychain:BAND_UUID:PUBLIC_KEY_SHA256
```

This reconnects and updates the dashboard only if the key is accepted.
An expired Meta session is removed from Keychain; rerun with `--login`.
The ownership ceremony always restarts from a fresh nonce, never halfway
through an expired receipt. An unsuccessful attempt retains its candidate key
and leaves the dashboard mapping unchanged.

## Validation

Offline coverage includes encrypted startup, response ordering, wrong-account
rejection, nonce validation, exact signed receipt preservation, HTTP session
expiry, cancellation/timeouts, checkpoint failure before the final request,
private persistence and Keychain fingerprint validation, and verification before dashboard activation.
The native login helper compiles on the development Mac. On November 9, 2026,
Meta sign-in, the complete ownership ceremony, and a fresh connection using the
new PEM succeeded on Meta Band 00Z9 (PSM 129). The band explicitly accepted the
new owner identity and completed peer link setup. No Android device or factory
reset was used. The dashboard mapping was activated only after that check.
An additional raw-EMG connection using the new PEM negotiated parameter 27,
received 898 EMG messages / 14,368 sample frames with zero missing batches,
and confirmed stream shutdown before disconnecting. The band reported eight
channels at 2,048 Hz.
At hardware validation, the instrumentation suite passed 108 tests and the
dashboard suite passed 7. After removal of superseded diagnostics and their
tests, all 96 remaining instrumentation tests and 7 dashboard tests passed.

The live sign-in page returned `oculus://frl_login`, while the reference
implementation expected `fb-viewapp://frl_login`. The helper accepts both exact
callback endpoints and checks the request-bound token before exchanging the
blob. A regression check can be run with the compiled helper's `--self-test`.

Meta's endpoints are undocumented and can change. Kinesis's reference
transport supports parameter 3; this implementation reuses this repository's
tested transport negotiation for parameters 3, 26 and 27.

On November 9, 2026, the existing owner key was migrated to Keychain and
matched by its public-key fingerprint. A fresh live connection accepted the
Keychain-backed identity before activation and removal of the original
plaintext PEM. No re-enrollment was performed. The migration regression suite
passes 99 instrumentation tests and 7 dashboard tests.
