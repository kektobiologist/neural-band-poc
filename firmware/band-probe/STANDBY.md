# Neural Band standby for the AC controller

Status: planned for the `band-ac` demo; **not implemented in ESP32 firmware**.
The device-state RPC and physical wake behavior were verified using the Mac
probe on 2026-10-19. See [the live trial](../../docs/protocol.md#physical-standby-trial-2026-10-19).

The goal is to let the band wait for a wake gesture between brief AC-control
sessions, instead of keeping normal gesture interaction active continuously.
Battery savings have not been measured. This is band standby over an existing
Bluetooth connection, not ESP32 deep sleep or an AC power command.

## Verified behavior and limits

- An authenticated configuration request with device state `1` enters standby;
  state `2` requests active mode. Both returned success and echoed the state.
- In the controlled trial, three index taps vibrated and reached the host before
  standby. Three attempted taps after standby did neither.
- One middle-finger double tap woke the band. The band consumed that gesture:
  no middle double-tap event reached the host. The next three index taps arrived
  and vibrated normally.
- With gyro subscribed, it continued at approximately 128 Hz during standby.
  Standby does not by itself stop all sensor traffic. Orientation behavior was
  inconclusive; raw EMG and internal power consumption were not tested.

The ESP32's `start_input()` already enables **only gesture stream field 3**;
it does not subscribe to gyro, orientation or raw EMG. Keep that configuration.
There is no existing motion subscription to remove in this demo. Keep the
gesture subscription and authenticated connection alive during standby so
events after a local wake can still arrive.

## Proposed interaction

Use a configurable inactivity timer (30 seconds is an initial test proposal,
not a validated optimum). After owner authentication and gesture subscription,
establish active mode, then request standby when the interaction window expires.
Refresh the timer on genuine user gestures, not BLE traffic or synthetic cleanup
events. Do not interrupt an in-progress IR shutdown sequence.

While idle, the wearer first performs a middle double tap to wake the band, then
uses the existing AC gestures:

| Gesture after wake | Existing action |
| --- | --- |
| Index double tap | AC ON |
| Middle double tap | AC OFF/ON/OFF cleaning-cancel sequence |
| Thumb swipe right/left | Temperature +1/-1 °C |

The wake gesture alone must not send IR. In particular, **from standby, turning
the AC off takes a wake middle double tap followed by another middle double
tap**. While active, one middle double tap retains its existing OFF action.
Do not remap or synthesize the consumed wake gesture as an OFF command.

There is no verified host-visible wake notification. Treat the first genuine
post-standby gesture as evidence of resumed interaction, request active mode to
establish the intended session state, and restart the inactivity timer. Preserve
the existing raw/derived filtering and deduplication so the user's subsequent
AC command executes once. Do not blindly discard the first received event: it
may be part of the intended command, not the consumed wake double tap.

Keep `gestures off` as the existing host-side AC-action disarm. A band waking
must never re-arm it. Manual serial AC commands remain available. Standby,
wake, connection and reconnection must not themselves transmit IR.

## Protocol implementation notes

Use the existing encrypted L2CAP/AirShield transport and input service `0xce56`.
Request type is `0x02000314`; response type is `0x02000315`.

| Field | Meaning |
| --- | --- |
| RPC request field 1 | Fresh request ID |
| RPC request field 5 | Nested configuration request |
| Configuration request field 6 | `1` standby, `2` active |
| RPC response fields 1 / 2 | Matching request ID / status (`1` observed success) |
| RPC response field 6 | Nested configuration response; field 6 can echo state |

Example plaintext payloads, before DataX framing and encryption:

```text
08 06 2a 02 30 01    request 6: standby
08 07 2a 02 30 02    request 7: active
```

Reserve a configuration channel distinct from stream channel `0x8005` (the Mac
uses `0x8007`). Open it with `[0x8100ce56, 0x02000314]`; subsequent requests reuse
the channel and retained type. Match reply channel and request ID, parse status
and any state echo, and distinguish requested state from acknowledged state.
An acknowledgement is not a battery measurement.

Schedule timer-driven requests on the BLE/protocol execution context; do not
write concurrently from the IR worker or block BLE callbacks waiting for a
reply. Use a bounded reply deadline (the Mac uses five seconds), log failures,
and avoid a rapid retry loop. On rejection or timeout, report unknown state
rather than claiming standby or savings. Clear pending requests and timers on
disconnect; rebuild state after reconnect. Retain an explicit active recovery
path for diagnostics and interrupted trials.

Do not write `stream_in_standby`, `auto-standby-timeout-secs`, `standby-gesture`,
`wake-gesture`, `middle-wake-enabled` or `keep-alive` for this first implementation.
Their full semantics are unverified and their setting IDs vary across firmware.
The host inactivity timer avoids guessing those settings.

## Acceptance checks when implemented

1. Verify correlated state replies, timeout/rejection handling, reconnect reset,
   and that stream subscriptions remain gesture-only.
2. On the physical ESP32/band setup, confirm normal gestures, idle standby with
   no ordinary gesture vibration/events, consumed middle-double-tap wake, and
   subsequent AC commands without duplicate or unsolicited IR.
3. Check wake while disarmed, manual serial commands during standby, and standby
   expiry during the OFF/ON/OFF sequence; the final OFF must still complete.
4. Compare band battery drain over equal-duration active and standby sessions
   with the same connection, wear and gesture pattern. Measure ESP32 power
   separately if needed. Report actual savings rather than assuming them from
   fewer gesture events.

Public sources: [Kinesis discussion](https://github.com/callbacked/kinesis/issues/11#issuecomment-6151575420)
and [Lumen's device-state implementation](https://github.com/beyondlevi/rokid-lumen/blob/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core/src/session.rs#L747).
