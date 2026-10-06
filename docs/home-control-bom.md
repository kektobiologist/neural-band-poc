# Home-control prototype BOM and board-design handoff

Updated: 2026-10-06. Related context: [home-control handoff](home-control-handoff.md).

## Status and evidence

The user confirmed the Robu order was placed on 2026-10-03. The table below records the **last agent-verified cart before checkout**, not an invoice: the user intended to filter items before buying, so reconcile quantities against the delivered parts/invoice before laying out boards. Delivery and physical inspection have not been confirmed. No hardware assembly or tests were performed in this conversation.

Last verified cart: **25 paid product lines, ₹5,091.78 including GST**, before any checkout changes or shipping. Prices are historical, not current quotes. No order token, address, payment details, or private browser URL is stored here.

## Selected architecture

- Two ESP32-S3 N16R8 development boards, one near the fan/light and one near the Samsung AC; ESP-NOW between them.
- Fan: conventional 230 V AC ceiling fan, controlled with the selected single-channel Robu dimmer. Exact fan label remains unknown.
- Light: user confirmed an **LED tube, approximately 20–40 W**. Exact driver/inrush characteristics remain unknown. The A03B SSR is a provisional test component, not a validated installed light switch.
- AC: IR control; do not switch its mains supply. Exact Samsung AC/remote model and protocol variant remain unknown.
- The RF-transmitter/receiver architecture with no ESP at the fan was abandoned. RDL 16-step boards, manual dimmers, digital-pot modifications and SWYAM boards were explored but not ordered in this cart.
- No mechanical relay clicking; fan hum is a separate consideration. Local operation, low latency and eventual independence from the Mac remain priorities.
- Which node receives band events is still a software decision. **Direct band transport/authentication on ESP32 is unproven.** Existing Mac software can provide test commands while the port is investigated; buying these boards does not prove that port feasible.

## Last verified Robu cart

Quantities are purchase units. Rows explicitly marked as packs contain multiple physical parts. Old product URL slugs sometimes say “pack of 50/100” even though the current listing/cart sold individual components; use the quantities and descriptions below, then reconcile with delivery.

| Qty | Part / purchase unit | Line total | Intended use |
| ---: | --- | ---: | --- |
| 2 | [ESP32-S3 DevKit, WROOM-1 N16R8, 16 MB flash + 8 MB PSRAM](https://robu.in/product/esp32-s3-devkit-esp32-s3-wroom-1-n16r8/) | ₹1,678.00 | Both controller nodes; USB-C; Robu SKU R263505 |
| 1 | [AC Light lamp dimming LED lamp and motor Dimmer Module, 1 Channel - 8A](https://robu.in/product/ac-light-lamp-dimming-led-lamp-and-motor-dimmer-module-1-channel-8a/) | ₹1,099.00 | Fan; SKU 1020730; includes heatsink and zero-cross sensing |
| 5 | [PN2222ATA onsemi NPN, TO-92](https://robu.in/product/pn2222ata-onsemi-40v-625mw-35150ma10v-1a-npn-to-92-3-bipolar-bjt-rohs/) | ₹60.00 | IR drivers, possible SSR interface, spares |
| 1 | [A03B 5 V single-channel AC SSR module with fuse](https://robu.in/product/a03b-1-road-5v-low-level-solid-state-relay-module-with-fuse-ssr-250v-2a-fuse/) | ₹109.00 | Provisional LED-tube switch; SKU 618464 |
| 1 | [MB102 830-point breadboard](https://robu.in/product/mb102-830-points-solderless-prototype-pcb-breadboard-high-quality/) | ₹69.00 | Low-voltage bench testing only |
| 1 pack | [Male–female jumper wires, 40 × 20 cm](https://robu.in/product/male-to-female-jumper-wires-40pcs-20cm/) | ₹49.00 | Low-voltage signals |
| 4 | [100 µF 25 V electrolytic capacitor](https://robu.in/product/100uf-25v-electrolytic-capacitor-pack-of-10/) | ₹18.56 | Local supply buffering |
| 1 pack | [VS1838B IR receiver, 5 pieces](https://robu.in/product/ir-receiving-head-vs1838b-remote-control-receiver/) | ₹99.00 | Substitute for unavailable TSOP38238; capture/test remote frames |
| 21 | [68 Ω 0.5 W metal-film resistor](https://robu.in/product/68-ohm-0-5w-metal-film-resistor-pack-of-50/) | ₹11.34 | Proposed IR LED current limiting; includes spares |
| 12 | [470 Ω 0.5 W metal-film resistor](https://robu.in/product/470-ohm-0-5w-metal-film-resistor-pack-of-50/) | ₹10.68 | Transistor base resistors; substitute for 0.25 W |
| 2 | [5 × 7 cm single-sided paper/copper prototype PCB](https://robu.in/product/single-side-prototype-paper-copper-pcb-universal-experiment-matrix-circuit-board-5x7cm-brand/) | ₹78.00 | Low-voltage interface perfboards; verify usable dimensions and hole layout |
| 2 packs | [M3 × 10 mm male–female nylon spacers, 10 per pack](https://robu.in/product/m310mm-male-to-female-nylon-hex-spacer-10pcs-copy/) | ₹164.00 | 20 spacers total |
| 6 | [PG7 polyamide cable gland](https://robu.in/product/polyamide-cable-gland-pg-7/) | ₹60.00 | Verify fit against actual cable outside diameters |
| 1 pack | [Female–female jumper wires, 40 × 10 cm](https://robu.in/product/10cm-female-female-breadboard-jumper-dupont-2-54mm-1p-1p-cable-40-pcs/) | ₹49.00 | Low-voltage signals |
| 2 | [BF-013A fuse holder](https://robu.in/product/fuse-holder-bf-013a/) | ₹28.00 | Listed 250 VAC/6 A; fuses not selected; check mounting and terminal insulation |
| 1 kit | [140-piece black heat-shrink assortment](https://robu.in/product/140pcs-black-heat-shrink-tube-kit/) | ₹349.00 | Assembly insulation/strain management; verify ratings for intended use |
| 2 | [1 × 40, 2.54 mm male header strip](https://robu.in/product/1x40-berg-strip-male-connector/) | ₹16.00 | Interface headers |
| 3 | [1 × 40, 2.54 mm straight long female socket strip](https://robu.in/product/1-40-pin-2-54m-straight-long-female-berg-strip-connector-pack-of-5/) | ₹294.00 | Removable development boards; verify socket height and pin fit |
| 10 | [100 nF 50 V disc capacitor](https://robu.in/product/100nf-50v-disc-capacitor/) | ₹12.20 | Local low-voltage decoupling |
| 6 | [WAGO 221-413 three-conductor connector](https://robu.in/product/wago-221-413-lever-splicing-connection-terminal/) | ₹414.00 | Each connector joins all three positions electrically; not three independent poles |
| 1 pack | [M3 × 6 mm nylon screws, 50 pieces](https://robu.in/product/m36mm-nylon-screw-50-pcs/) | ₹70.00 | Mounting hardware |
| 2 | [Black USB-A → USB-C data cable, 2 A, 1 m](https://robu.in/product/Black%202A%201m%20Type%20A%20to%20Type%20C%20USB%20Cable/) | ₹138.00 | Programming and power |
| 1 pack | [M3 nylon nuts, 25 pieces](https://robu.in/product/white-nylon-nut-m3/) | ₹67.00 | Mounting hardware |
| 1 pack | [E1008 insulated ferrules, 1.0 mm², 100 pieces](https://robu.in/product/100pcspack-e1008-insulated-ferrules-10mm%C2%B2-terminal-block-cord-end-wire-connector-blue/) | ₹119.00 | Use only with matching wire and compatible terminals |
| 1 pack | [100 mm nylon cable ties, 100 pieces](https://robu.in/product/nylon-cable-zip-ties-100mm-100pcs-bag-1-bag/) | ₹30.00 | Cable management |

Resistor quantities were increased to meet Robu's ₹10 minimum per product line. The 10 kΩ resistor line was removed after it became unavailable and could not meet the minimum; it is **not** included in the total.

Robu also automatically included free parts: 3 × Murata DSS1NB32A101Q91A 100 pF feedthrough capacitors and 10 × GCM1555C1H220JA16J 22 pF 0402 capacitors. These are not required by the design and do not replace the 100 nF decoupling capacitors.

## Missing, excluded, or not yet specified

| Qty | Part | Status |
| ---: | --- | --- |
| 2 | [Vishay TSAL6200 940 nm IR LEDs](https://in.element14.com/vishay/tsal6200/infrared-emitter-940nm-t-1-3-4/dp/3152856) | Not added on Robu; one emitter plus spare/second direction. Another emitter requires checking its ratings and recalculating the driver. |
| 10 | 10 kΩ through-hole resistors, ≥0.25 W | Not in cart; both checked Robu wattage variants unavailable at final check. Intended for defined idle states. |
| 2 | Enclosed USB power adapters, 5 V-class output, ≥2 A each | **Explicitly excluded by user.** Availability of suitable existing adapters has not been confirmed. USB data cables remained included. |
| 1 | Flame-retardant electrical enclosure, roughly 200 × 150 × 80 mm with mounting provision | Not sourced; final size depends on actual layout, heat and mains/logic separation. |
| 1 | Low-voltage AC-node enclosure, roughly 100 × 70 × 40 mm | Not sourced; size is provisional; provide an IR opening/window suitable for 940 nm. |
| ~3 m each | Brown, blue and green/yellow 1.0 mm² mains-rated copper wire | Not sourced; electrician to confirm installation needs. |
| 2 + spares | Fuses matching the holders | Ratings, characteristics and breaking capacity not selected; must coordinate with actual loads/protection. |
| 1 set | Labels | Not sourced. |

Tools were not ordered: confirm access to soldering iron, solder/flux, cutters/strippers, multimeter, suitable ferrule crimper and enclosure drilling tools. Logic analyser/oscilloscope may help timing tests, but only use appropriate isolation and probes around mains.

## Instructions for the next design/testing agent

The next task is to **design the two low-voltage perfboards and a staged test plan**, using this inventory. Do not restart component shopping or resurrect the RF-only architecture. No schematic, GPIO allocation, firmware implementation or tested wiring diagram has been approved yet.

1. Reconcile actual purchased/delivered parts. Obtain board markings, dimensions, header spacing, module pin labels and underside layout before drawing perfboard hole coordinates. A 5 × 7 cm board may be suitable for an interface carrier rather than mounting everything on one board; do not assume fit.
2. Make a schematic and pin-assignment table before the physical layout. Confirm the exact N16R8 development-board revision, PSRAM/flash-reserved pins, boot strapping, USB pins and power path. Decide how USB power reaches peripherals without backfeeding a programming host or connecting two supplies together.
3. Fan interface: seller documents **Zero** and **DIM/PSM** pins, 3.3/5 V logic and MCU-timed phase control using [RBDDimmer](https://github.com/RobotDynOfficial/RBDDimmer). Check the delivered module schematic/revision, supply requirement, actual zero-cross output level and isolation; “3.3/5 V logic” alone does not establish a safe 3.3 V output. Validate ESP32-S3/library support rather than assuming a drop-in build. No extra zero-cross module is in the BOM. Seller's “8 A” title is not a validated ceiling-fan rating; its package description previously also said 5 A.
4. Light interface: A03B is labelled low-trigger but its listing also describes high-trigger behaviour. Establish trigger polarity, input voltage/current, startup state and real isolation from the delivered board. An NPN interface from the 5 V control circuit was proposed; its exact topology/pulls are not settled. Check driver inrush, minimum load, leakage/ghosting and heat with the actual LED tube before accepting this SSR for installation.
5. IR interface: starting proposal is a PN2222A low-side driver per emitter, 68 Ω/0.5 W LED resistor from a 5 V rail, 470 Ω base resistor and 10 kΩ base–emitter pull-down, with local decoupling. This is **unbuilt and untested**; confirm transistor pinout, emitter ratings, worst-case current and dissipation before finalising. Use a separate current-limiting resistor per LED. Start with one emitter aimed at the AC. Verify the VS1838B pinout and run at a documented 3.3 V supply level for ESP32-compatible output. Capture the Samsung remote's full state frames before defining commands.
6. Keep mains off the solderless breadboard and the low-voltage perfboards. Retain the purchased dimmer/SSR as separate mains assemblies with physical separation, secure terminals, protection and enclosure. Their OFF states are not a physical disconnect. Qualified mains installation and a retained disconnect are required; do not connect USB/test equipment across an unverified isolation boundary.

## Suggested test sequence and acceptance evidence

1. **Unpowered inspection:** pinouts, shorts, polarity, soldering, connector labels and physical fit. Document photos/schematic corrections.
2. **Low-voltage bring-up:** power each ESP32 separately over USB; verify 5 V/3.3 V rails and peripheral current. Keep mains disconnected. Test GPIO idle states and transistor interfaces with suitable low-voltage test loads.
3. **Communications:** test ESP-NOW using synthetic commands first. Check acknowledgements, deduplication, loss/reconnect, reboot/brownout behaviour and explicit on/off commands. Define and verify safe output defaults before appliance tests. Measure dispatch/acknowledgement latency rather than promising a zero-latency system.
4. **IR bench/appliance tests:** receive/decode original remote commands; verify carrier/frame generation and AC reception for power, temperature, mode and fan settings. Avoid accidental resets of other AC state fields. Log success/failure and emitter placement.
5. **Dimmer timing tests:** validate zero-cross interrupt and timer logic with low-voltage simulated signals before protected mains testing. Confirm clean timing while ESP-NOW/BLE tasks run. No fan output can be proven merely by USB-powering the module.
6. **Protected load tests:** once physical isolation/protection is reviewed, validate fan reliable starting/minimum speed, stalls, hum and module/motor temperature; validate LED-tube inrush and off-state ghosting. Check MCU resets, supply dips and missed commands while switching.
7. **Band integration:** separately prove band transport/authentication on ESP32. Existing Mac event bridging remains a development fallback. Only then test end-to-end gestures and the proposed state machine in the linked handoff.

Record the actual schematic, GPIO map, perfboard layout, firmware revision, test conditions and results in the repo as work progresses. This document records procurement and intended validation, not successful test results.
