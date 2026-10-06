# Home-control prototype handoff — updated 2026-10-06

## Start here: procurement and next task

Read [the BOM and perfboard-design handoff](home-control-bom.md) first. The user confirmed a Robu order on 2026-10-03 after the agent prepared a cart of 25 paid product lines (₹5,091.78 including GST). This is a cart record, not an independently checked final invoice; reconcile delivered parts before layout. The user now wants to continue with another agent to design the prototype perfboards and test them. No hardware tests or perfboard design were completed in this conversation.

The selected architecture is **two ESP32-S3 N16R8 boards**, using ESP-NOW between the fan/light and AC nodes. The RF-only receiver proposal was abandoned. The selected fan module is Robu's single-channel 8 A AC dimmer; the A03B SSR is a provisional LED-tube test component. USB-C power adapters were explicitly excluded from the order. Missing items and detailed interface caveats are in the BOM.

## Goal and user preferences

Use the neural band's recognized gestures to control the user's room appliances with minimal delay after recognition:

- Tubelight: on/off. User confirmed LED, approximately 20–40 W; exact driver remains unknown.
- Conventional 230 V AC ceiling fan in India, currently using a wall regulator: on/off and speed.
- Samsung AC with an IR remote: on/off and temperature. Exact AC/remote model remains unknown.

The user reports recognition feels very fast. Thumb swipes work, although initially entering the swipe interaction sometimes takes a little time. Prioritize a fast switching prototype over Home Assistant integration. Avoid cloud dependencies and unnecessary wireless hops. The final prototype should not depend on the Mac. Prefer off-the-shelf parts, searching Amazon India first and Robu second. No parts have been purchased by the agent.

The latest requirement is **no mechanical relay clicking**. The user has also experienced MCU interference with optocoupled mechanical relay boards. Revise the hardware plan toward solid-state outputs; do not continue recommending the earlier mechanical relay board.

## Proposed architecture, not yet implemented

The user intends to use two ESP32 devices because the AC and fan/light controls cannot be colocated:

1. ESP32 #1: receive band events, run the gesture/control state machine, and drive local fan/light control interfaces.
2. ESP32 #2: sit near the AC and transmit Samsung-compatible IR, receiving commands from #1 over ESP-NOW.

ESP32-S3 N16R8 development boards were selected for both nodes. The band-receiving node assignment above is provisional. **Direct band connectivity on ESP32 is not established.** BLE L2CAP CoC support in a platform SDK is only a prerequisite; the existing band transport, owner authentication, encryption, and streaming protocol still need porting and hardware validation. Appliance-node prototyping can proceed with synthetic commands or the existing Mac bridge. A dedicated Linux SBC remains a fallback connector if the ESP32 port proves unsuitable; the final Mac-independent band path is not settled.

No measured end-to-end latency budget exists yet. Do not promise zero radio latency. Measure recognition-event receipt, command dispatch, output activation, and acknowledgement separately. IR transmission and an appliance's internal response are distinct from MCU dispatch time; fan mechanical speed changes and AC compressor delays are not switching latency.

## Latest output-stage decision

| Appliance | Proposed output | Remaining verification |
| --- | --- | --- |
| LED tubelight | A03B 5 V single-channel AC SSR module, provisional test part | Conflicting seller trigger descriptions; actual isolation, input interface, driver inrush, minimum load, leakage, thermal behaviour and protection |
| Conventional fan | Selected Robu single-channel 8 A dimmer with zero-cross sensing and MCU-timed triggering | Actual board revision/pinout, output logic levels, isolation, ESP32-S3 firmware support, fan compatibility, startup/minimum speed, hum and thermal behaviour |
| Samsung AC | IR transmitter driven by the second ESP32 | Model/protocol variant, full-state frame format, emitter coverage and library support |

Optocouplers themselves are not the mechanical/noisy component; optical isolation remains desirable. Removing the relay coil and contacts removes coil flyback and contact arcing from that relay, but does not eliminate all load-related EMI. The user's interference has not been diagnosed: supply dips, shared ground/power paths, contact transients and radiated coupling are possibilities. Do not assert that airborne coil coupling is the cause without measurements.

A zero-cross SSR waits for the next voltage zero crossing: approximately 0–10 ms at 50 Hz. This is a small, bounded switching contribution, not a measured total system latency. A normal on/off zero-cross SSR is **not** a fan speed regulator; do not apply ordinary ESP32 PWM or heater-style burst control to it for this purpose. Phase-angle fan control removes relay clicks but may produce motor hum. SSRs dissipate heat, leak some current while off, and are not a physical mains disconnect. Use an enclosed, appropriately protected assembly and retain a physical disconnect; mains installation needs a qualified electrician.

## Historical shopping research (superseded by the BOM)

These are historical listing observations from this conversation, not purchase approvals, certifications, or guaranteed current prices/stock. Recheck before ordering.

| Item | Link and observation | Status |
| --- | --- | --- |
| Robocraze 2-channel 5 V optocoupler mechanical relay board | [Amazon B073B6M5JB](https://www.amazon.in/dp/B073B6M5JB); observed ₹209, in stock; advertised 3.3–5 V low-level control | **Superseded** by the user's solid-state requirement; bare board and general contact rating were not proof of lamp-inrush suitability |
| Xenbrix AC Dimmer V2 | [Amazon B0HBKKW7BT](https://www.amazon.in/dp/B0HBKKW7BT); observed ₹349, in stock; seller advertised 110–230 VAC, 3 A/600 W, 2.8–5.5 V control and induction-fan support | Candidate only; seller claims do not establish isolation, motor rating, or exact ESP32 interface. Obtain schematic/pinout/library and verify before selecting |
| Four-channel AC dimmer module | [Robu listing](https://robu.in/product/ac-light-lamp-dimming-led-lamp-and-motor-dimmer-module-4-channel/); SKU 890179; observed ₹1,789, out of stock; BTA16-600B and RBDdimmer mentioned | Candidate only; listing had inconsistent channel/voltage descriptions. Not a verified ready-to-install fan regulator |
| G3MB-202P SSR modules | [Datasheet hosted by Robu](https://robu.in/wp-content/uploads/2017/04/g3mb-ssr-datasheet-1.pdf) | Investigated as an SSR family, **not selected**. Do not treat a generic “2 A” module as verified for LED inrush or ceiling-fan control |

A selected-parts/cart BOM now exists in [home-control-bom.md](home-control-bom.md), and the user confirmed ordering. The historical candidates above are not the current shopping list. The selected dimmer and SSR still require hardware/load validation; procurement does not establish electrical suitability or successful operation.

Useful primary technical references:

- [Omron SSR application and load guidance](https://www.ia.omron.com/support/guide/18/further_information.html)
- [Omron SSR terminology, including zero-cross operation](https://www.ia.omron.com/support/guide/18/explanation_of_terms.html)
- [Omron mechanical relay precautions, including contact-arcing interference](https://www.ia.omron.com/product/cautions/36/safety_precautions.html)
- [ST induction ceiling-fan TRIAC controller reference](https://www.st.com/ja/evaluation-tools/steval-ihm037v1.html)

## Gesture vocabulary discussed, not implemented

### Original scheme: light and fan

Use finger identity to select the device directly, without a separate device-selection step: index for the light, middle for the fan. Double-taps provide discrete power commands; a held pinch plus wrist roll provides the fan dial interaction.

| Gesture | Action |
| --- | --- |
| Index double-tap | Toggle tubelight on/off |
| Middle double-tap | Toggle fan on/off |
| Middle pinch/hold plus wrist roll | Adjust fan speed |

The user wanted rapid operation and clear device disambiguation. They also requested haptic feedback to indicate fan dial position; tactile speed detents remain an idea contingent on decoding the haptics command, not an available feature.

### Extended scheme: add the AC

Preserve the light/fan shortcuts in normal mode and introduce a temporary AC context. The combined proposed mapping was:

| Gesture/context | Action |
| --- | --- |
| Index double-tap in normal mode | Toggle light |
| Middle double-tap in normal mode | Toggle fan |
| Middle pinch/hold plus wrist roll in normal mode | Adjust fan speed |
| Right thumb swipe in normal mode | Enter temporary AC mode |
| Left thumb swipe or five seconds idle | Exit AC mode |
| Index double-tap in AC mode | Toggle AC power |
| Index pinch/hold plus wrist roll in AC mode | Adjust temperature |

Suspend normal-mode bindings while AC mode is active. This is a design proposal, not a final tested user preference or deployed appliance controller. Validate disambiguation, accidental activation, gesture deduplication and mode feedback before use. Decide startup state, stale command behavior, explicit on/off versus toggles, and retry/acknowledgement semantics when implementing; no such policy has been implemented here.

### Interaction details still to settle

- Wrist-roll direction, gain, deadband and detent spacing; do not infer these from the animation alone.
- Fan speed steps and whether adjusting speed while off also powers the fan on.
- Temperature step size, permitted range and behavior while the AC is off.
- Reliable feedback for entering/exiting AC mode, including a fallback if band haptics remain unavailable.
- Exact hold/release and idle-timeout behavior during an active adjustment.

These are open design decisions, not previously agreed bindings. The user's swipe observation supports trying the AC-mode gesture, but their reported initial swipe-acquisition delay should be evaluated in actual use. No up/down swipe appliance actions were assigned in the recorded scheme.

Band-recognized gestures arrive from the band; the host does not run the recognition model for these events. Host logic still interprets/deduplicates events and converts wrist motion into a dial. Synthetic cleanup/release events must not trigger appliance actions. Raw and derived representations of the same gesture must not cause duplicate commands.

Custom haptics would be useful for fan speed detents. A `hapticsReq` RPC name/field 17 was recovered in earlier investigation, but its nested parameters have not been decoded and custom haptic playback is **not working/verified**. Do not promise tactile ticks yet.

## Existing Mac/dashboard state and PEM strategy

The existing dashboard is at `http://localhost:8765/`. Its process was running earlier in this conversation; **current liveness was not rechecked for this handoff**. Typical launch command from the repo root is `.venv/bin/python dashboard/server.py`.

The PEM owner identity was provisioned in earlier work. Current `dashboard/server.py` reads `captures/dashboard-identities.json` and passes the selected identity path as `--identity-key` to the band client. Continue using that strategy rather than re-enrolling or replacing the owner identity unnecessarily.

Local ignored artifacts relevant to resuming:

- `captures/dashboard-selected-band.json`: selected band (previously Meta Band 00Z9).
- `captures/dashboard-identities.json`: mapping of band identifier to owner identity path.
- `captures/oneplus/paired-session/band-owner-identity.pem`: previously used owner identity. **Private key: never print its contents, commit it, or copy it into documentation.**
- `captures/mac-band-probe-dashboard-20260930T171050089594.jsonl`: trace examined earlier. Reported 119 non-synthetic raw swipes (26 left, 37 right, 38 down, 18 up), each with a derived equivalent, plus four thumb click events. These are prior trace observations, not a new verification during this documentation update.

The user's real-world observation that swipes work is stronger evidence than merely seeing their enum values. Enum support does not prove every gesture is physically available. Consult `instrumentation/input_service.py`, [gesture notes](gestures.md), [gesture model notes](gesture-models.md), [trust handshake](trust-handshake.md), and [findings](findings.md) for protocol details. This session did not establish table-writing/handwriting recognition as an accessible band feature.

`captures/` is ignored. A fresh clone will not contain the owner PEM or captured traces; the next agent must distinguish local artifacts from tracked project data.

## Suggested continuation

1. Reconcile the BOM against the actual invoice/delivered parts and identify the missing components. Confirm fan, LED driver and Samsung AC/remote models.
2. Follow the BOM's design handoff: verify actual board interfaces, draw the two low-voltage schematics and GPIO maps, then create dimensioned perfboard layouts. Resolve power distribution and boot/output states before wiring.
3. Execute the staged low-voltage, communications, IR and protected load tests in the BOM. Record evidence and failures. Household-output firmware and mains hardware were not built in this conversation.
4. Separately prove band connectivity/authentication on ESP32 and implement the gesture state machine. Preserve the existing owner identity strategy; do not equate selecting an ESP32 board with a working band port.

This file records discussion, procurement context and intended work. This documentation update does not change the server, band firmware, authentication implementation, or appliance control behaviour.
