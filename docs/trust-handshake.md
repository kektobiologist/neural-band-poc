# trust handshake

this page is the implementation guide for the band's `enabletrust` exchange.
it is written for a port author: every constant, field, and ordering rule
below comes from working code and verified hardware sessions. read
[protocol.md](protocol.md) first for the transport handshake; the trust
handshake runs on top of it. Operational setup and identity recovery are in
[mac-enrollment.md](mac-enrollment.md).

## when it runs

the handshake replaces the legacy empty identity query (`0x02003000`) on a
connection to an enrolled band. it runs once per connection, after the
airshield exchange and before end link setup. the client waits for owner acceptance and peer link setup before opening the
input service. The current Python and ESP32 clients do not verify the band
identity signature; do not describe this as mutual identity verification.

two facts matter for reconnection logic:

- enrollment persists on the band across reboots. ownership and the
  provisioned identity survive power cycles.
- the trust handshake is per-session. every new encrypted connection replays
  it. a band that reboots mid-session expects a fresh handshake on the next
  connection, not a resume.

## the transcript digest

both proofs sign one digest. for sender `S` and receiver `R`:

```text
digest = SHA256( SHA256(R.challenge16 || R.pub64) || SHA256(S.seed32 || S.pub64) )
```

- `challenge16` is the 16-byte challenge the receiver sent in its
  `RequestEncryption` message.
- `seed32` is the 32-byte seed the sender sent in its `EnableEncryption`
  message.
- `pub64` is the raw 64-byte p-256 public point (x||y, no `04` prefix).

for the host proof the band is the receiver and the host is the sender. for
the band proof the roles flip.

signatures are p-256 ecdsa over the digest, encoded as raw 64-byte `r || s`.
no der, no hash headers.

## host proof: enable trust

frame:

| part | value |
| --- | --- |
| channel | `0x8002` |
| words | `[0x81000024, 0x02001000]` |
| payload field 1 | `SHA256` of the host identity public key's raw 64-byte point (32 bytes) |
| payload field 2 | the host identity signature, 64 bytes raw `r||s`, over the digest with the band as receiver and the host as sender |
| payload field 3 | role `2` used by the current client |

`0x81000024` opens the identity service on the channel. it is only needed
before the first identity exchange on that channel; a later `enable trust` on
the same channel sends the single word `[0x02001000]`.

the host identity key is the p-256 signing key provisioned at enrollment
(see [enrollment-flow.md](enrollment-flow.md)). field 1 binds the proof to
that key without sending it.

## band result

the band answers with a result word on channel 2, in the `0x0300xxxx` family:

| word | meaning |
| --- | --- |
| `0x03001000` | host identity accepted |
| `0x03001043` | band enrolled to a different key |
| anything else | rejection |

`0x03001043` means the stored host key does not match the band's enrollment.
the full result-code map is in
[enrollment-flow.md](enrollment-flow.md#identity-service-error-map).

## band proof: enable trust ec

after (or before, or interleaved with) the result, the band sends its own
proof:

| part | value |
| --- | --- |
| type word | `0x02001001` |
| channel | a channel with the rx bit set; observed `0x8003` |
| payload field 1 | a hint, 12 bytes observed |
| payload field 2 | the band's signature, 64 bytes raw `r||s`, over the digest with the host as receiver and the band as sender |
| payload field 3 | provisioning capabilities, observed value `1` |

The current `OwnerTrust` implementation checks that field 2 is 64 bytes and
acknowledges the proof with `0x03001000` on the low channel (`0x8003` → 3).
It does not cryptographically verify the band signature. Enrollment retains an
optional band public key for future verification work; its presence does not
mean that verification is implemented.

## ordering and end link setup

The host acknowledges the band's proof when received. `OwnerTrust.ready`
requires both the host-identity acceptance result and the peer's `EndLinkSetup`
message. The peer setup includes a 16-byte field 2 and state 0/1 in field 1
(omitted state means 0). These two events may arrive in either order.

Once ready, the current host sends:

| part | value |
| --- | --- |
| channel | `0x8001` |
| words | `[0x02001000]` |
| payload field 1 | varint `1` |
| payload field 2 | 16 fresh random bytes |
| payload field 3 | another 16 fresh random bytes in enrolled-owner mode |

Startup then queries device info on `0x8003` (`0x8100ce56`, `0x02000314`)
and opens the requested input/configuration subscriptions.

## Failure handling

`0x03001043` rejects the stored host identity. Stop the connection and verify
that the selected band's mapping points to the current Keychain identity. Preserve existing
keys. If an enrollment attempt was interrupted, try its candidate with
`enroll_band.py --verify-key` first. Use the Mac enrollment recovery flow only
when needed; do not silently fall back to an unauthenticated sensor connection.
Other rejection codes fail the connection and must be diagnosed by their actual
meaning. A transport MAC failure is not an owner-key-expiry signal.
