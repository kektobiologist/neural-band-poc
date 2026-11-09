# Cue-only tap learning

Second attempt at personal gestures (ring, pinky and any other custom tap), after
the [webcam pinch experiments](pinch-learning.md) failed live. Three changes:

- **Taps, not holds.** A tap's onset is a sharp EMG burst; a held pinch is weak
  and depends on how hard you press. Meta's own model is event-based too.
- **No webcam.** The cue gives the class, the first EMG burst after it gives the
  time. No occlusion, no camera/band clock alignment.
- **Many short sessions across rewears**, scored leave-one-session-out, with a
  per-session rest calibration. The Nov 7 failure was cross-session drift.

Nothing here has been run on the band yet; tests use synthetic sessions only.

## Step 0: do the band's own model scores already separate ring/pinky?

The band streams nine scores from its on-device model (see
[gesture models](gesture-models.md)). `--stream-control raw-emg-inference`
requests raw EMG (field 2) and those scores (field 4) on one subscription. It
leaves out gesture events (field 3), because an earlier combined run broke when a
gesture record arrived mid-frame ([findings](findings.md)). **Whether EMG and
scores stream together reliably is itself untested**: check `probe.log` for missing
batches and `probe_result.inference_messages > 0`. If scores never arrive, try
`(2, 3, 4)` in `STREAM_FIELDS`, or record with `--stream raw-emg` and skip step 0.

## Record

```sh
python -m learning.tap_record BAND_UUID --output captures/taps-20261110-01
```

Defaults: index, middle, ring, pinky and rest, 12 cues each, one cue every
2–2.5 s (jittered so you react instead of keeping rhythm), about 2.5 minutes.
The terminal shows `TAP thumb + RING` with a bell; tap once quickly and relax.
On `stay relaxed`, do nothing. Ctrl-C aborts (aborted sessions are rejected).
Custom gestures: `--gestures ring pinky fist` (names are only labels and cues).

Take the band off and put it back on between sessions. Aim for 8–10 sessions
over 2–3 days. Vary arm position a little between sessions, not within one.

Files in the session directory: `band.jsonl` (probe capture, contains session
key material, keep local), `cues.jsonl` (cue label and host monotonic time),
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

- `--hi` (default 3): a tap's envelope peak must exceed this multiple of the
  session's median EMG envelope. Raise it if rest cues show `rest_active`; lower
  it if gentle taps are `missed`.
- `--lo` (default 1.5): onset is where the envelope last rose through this
  multiple before the peak.
- Taps are searched 0.1–1.2 s after the cue; 0.3 s before the cue must be quiet.

Timing uses the least-delayed receipt to anchor device clocks to host time:
biased late by at least one 8 ms batch and ignoring clock drift. Fine for a 250 ms
window; fit a line if sessions get much longer.

## Next

If step 0 separates the classes, a classifier on the nine scores is the cheapest
path, because Meta already made them robust across sessions. Otherwise, once
leave-one-session-out accuracy is decent, add live two-stage inference (burst
detector, then classifier, with confidence rejection) and measure false triggers
per minute during typing, walking and holding objects.

```sh
python -m unittest learning.tests.test_taps -v
```
