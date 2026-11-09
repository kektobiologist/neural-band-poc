# Cue-only tap learning

Second attempt at personal gestures (ring, pinky and any other custom tap), after
the [webcam pinch experiments](pinch-learning.md) failed live. Three changes:

- **Taps, not holds.** A tap's onset is a sharp EMG burst; a held pinch is weak
  and depends on how hard you press. Meta's own model is event-based too.
- **No webcam.** The cue gives the class, the first EMG burst after it gives the
  time. No occlusion, no camera/band clock alignment.
- **Many short sessions across rewears**, scored leave-one-session-out, with a
  per-session rest calibration. The Nov 7 failure was cross-session drift.

Status after two real sessions ([results](#first-session-november-9)): recording,
live pacing and labelling work. Within one session EMG features reach 90%
balanced accuracy over index, middle, ring, pinky and rest; across the two
sessions that falls to 49%. The band's own scores cannot tell ring from middle.
Collecting many more band placements is the open work ([next](#next)).

## Step 0: do the band's own model scores already separate ring/pinky?

The band streams scores from its on-device model: nine on older firmware (see
[gesture models](gesture-models.md)), three on the current one. The decoder
takes the count from the band's inference config. `--stream-control
raw-emg-inference` requests raw EMG (field 2) and those scores (field 4) on one
subscription. It leaves out gesture events (field 3), because an earlier
combined run broke when a gesture record arrived mid-frame
([findings](findings.md)). EMG and scores streamed together with zero missing
batches in both real sessions. On other firmware, check `probe.log` for missing
batches and `probe_result.inference_messages > 0`; if scores never arrive, try
`(2, 3, 4)` in `STREAM_FIELDS`, or record with `--stream raw-emg` and skip step 0.

**Answer:** no. Index, middle and pinky taps separate from rest, but ring taps
score like middle taps, so ring needs our own EMG model.

## Record

```sh
python -m learning.tap_record BAND_UUID --output captures/taps-20261110-01
```

The owner identity comes from the saved Keychain registry, as for every probe
connection ([Mac enrollment](mac-enrollment.md)); `--identity-key` overrides it.
Defaults: index, middle, ring, pinky and rest, 12 cues each.
The terminal shows `TAP thumb + RING` with a bell; tap once quickly and relax.
On `stay relaxed`, do nothing. Ctrl-C stops early; the cues before it are still analyzed.
Custom gestures: `--gestures ring pinky fist` (names are only labels and cues).

Pacing is live. The first 5 s of rest calibrate each channel's resting level;
then the same strongest-channel detector as `learning.taps` (`--hi`/`--lo`)
advances once a tap has stayed below `--lo` for 0.3 s, at least 1.5 s after its
cue, plus 0–0.5 s jitter. A tap cue with no burst within 1.6 s shows `no tap
seen` and is repeated once at the end. Rest cues last `--gap` (2 s) plus jitter.
With a ~0.85 s reaction that is about 110 s per session instead of 141 s. Live
results are only pacing hints: `cues.jsonl` records them (`live`, `attempt`),
but `learning.taps` relabels every cue offline.

Take the band off and put it back on between sessions. Aim for 8–10 sessions
over 2–3 days. Vary arm position a little between sessions, not within one.

Files in the session directory: `band.jsonl` (probe capture, contains session
key material, keep local), `cues.jsonl` (cue label, host monotonic time, live result),
`session.json`, `probe.log`.

## Analyze

```sh
python -m learning.taps captures/taps-20261110-01 [captures/taps-20261110-02 ...]
```

Per session, prints how many cues produced a usable tap, the median reaction
delay and median burst size. Statuses: `missed` (no burst), `busy` (already
moving at the cue), `rest_active` (moved on a rest cue), `gap` (dropped EMG).
Writes `taps.json` (one event per cue) into each session.

Then, if scores were recorded, the mean peak score of each native output per
class: the step 0 answer. Finally cross-validated logistic regression on band
scores, EMG features ([`features.py`](../learning/features.py), 250 ms from 30 ms
before onset) and both. One session uses stratified folds within the session,
which is optimistic. Several sessions use leave-one-session-out, the number to
trust. Features are normalized per session by subtracting that session's mean
rest features.

### Calibration knobs

The detector uses the strongest channel, each channel scaled to its own resting
level. Summing all eight channels diluted ring taps: on the first real session
ring peaks were 1.5–2.8× summed versus 3.0–9.0× per channel, with rest at 1.8×.

- `--hi` (default 4): a tap's peak must exceed this multiple. Raise it if rest
  cues show `rest_active`; lower it if gentle taps are `missed`.
- `--lo` (default 2): onset is where the envelope last rose through this
  multiple before the peak.
- Taps are searched 0.1–1.6 s after the cue (median reaction on the first
  session was ~0.85 s); 0.3 s before the cue must be quiet.

Timing uses the least-delayed receipt to anchor device clocks to host time:
biased late by at least one 8 ms batch and ignoring clock drift. Fine for a 250 ms
window; fit a line if sessions get much longer.

## First session (November 9)

`taps-20261109-05`, right wrist, Meta Band 00Z9, Keychain owner identity. All 60
cues ran; 17,777 EMG batches with zero missing; scores and EMG streamed together
on one subscription and shut down cleanly. This firmware's model reports
**pipeline 1, stride 72, three scores**, not the nine-output table in
[gesture models](gesture-models.md). The probe then exited 1 because its decoder
accepted only nine scores (since fixed; `session.json` keeps the original status).

Kept taps with the per-channel detector: index 10/12, middle 10/12, ring 8/12,
pinky 9/12, rest 8/12. Median reaction 0.82–0.93 s. Several cues showed small
activity 0.1–0.3 s before the cue (anticipation), now tolerated if the tap is at
least twice as large.

| Features | Accuracy | Balanced | Notable confusion |
| --- | ---: | ---: | --- |
| Band model scores (3) | 68.9% | 67.8% | ring predicted middle 6/8 |
| EMG features | 88.9% | 90.0% | middle predicted ring 3/10 |
| Both | 86.7% | 87.5% | middle predicted ring 3/10 |

Five-fold within one session: optimistic, and the Nov 7 pinch models lost most
of a similar within-session score on a fresh wear. **Step 0 answer:** the band's
three scores separate index, middle and pinky taps from rest, but ring taps look
like middle taps, so ring needs our own EMG model. Record more sessions with
re-wears and check leave-one-session-out before trusting the EMG number.

### Second session, first cross-session check

`taps-20261109-06` used live pacing and was stopped after 38 of 60 cues (clean
stream shutdown, zero missing EMG). Mean cue spacing was 1.96 s versus 2.25 s
fixed; 36/38 cues were kept offline (live pacing flagged 4 misses, 3 of which
the offline detector still accepted).

Leave-one-session-out over sessions 05 and 06 (balanced accuracy): band scores
67.8%, EMG features 49.2%. The within-session 90% does not survive a new
session, as with the Nov 7 pinches. With only two sessions each model trains on
one; a quick normalization comparison gave rest-mean subtraction 49.2%, none
57.8%, rest mean and std 53.0%, per-session z-score of all taps 64.5%. Too few
sessions to choose; re-run the comparison with four or more.

## Next

Data collection is the bottleneck, and the scarce thing is band placements, not
taps: ten 30-second sessions after ten rewears teach more than one long session.
Ideas for collecting more, cheapest first (none built yet):

1. **Voice prompts, self-paced blocks.** macOS `say` speaks "ring, five"; the
   wearer taps five times and the burst detector counts them. Roughly 0.5–0.7 s
   per tap instead of 2 s, and no screen, so arm position can vary. Needs the
   analyzer to label several bursts per cue. A 45-second mode could run on every
   rewear.
2. **Fingertip contact sensors.** Conductive tape on the thumb and fingertips,
   wired to ESP32-S3 touch pins, gives exact press and release labels with no
   prompts at all. Needs the ESP32's timestamps aligned with the Mac clock.
3. **Unlabelled background recording** during normal wear, for false triggers
   per minute and each placement's resting signal. Needs the probe's 300 s limit
   lifted or captures chained; about 115 MB per hour.
4. **Labels from use**, once a model is usable: each trigger is an example and
   an undo marks a wrong one.

With four or more sessions, re-run the normalization comparison. Once
leave-one-session-out accuracy is decent, add live two-stage inference (burst
detector, then classifier, with confidence rejection) and measure false triggers
per minute during typing, walking and holding objects.

```sh
python -m unittest learning.tests.test_taps -v
```
