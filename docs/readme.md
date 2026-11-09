# notes

setup and everyday use are in the [main readme](../readme.md). commands in these notes run from the repo root. capture filenames refer to the local, ignored `captures/` folder.

- [Mac connection and enrollment](mac-enrollment.md): current identity, setup, and recovery.
- [findings](findings.md): hardware results, verified derivations, stream captures, and known failures.
- [home-control handoff](home-control-handoff.md): appliance-control goals, solid-state hardware decisions, shopping candidates, and remaining feasibility work (2026-10-01).
- [protocol](protocol.md): public schemas, pinned source code, and framing references.
- [gestures](gestures.md): the supplied video references and how the hand illustrates them.
- [haptics](haptics.md): client-triggered buzzes, quick sequences, console/CLI use, and verified limits.
- [handedness](handedness.md): the native hand setting, read-back checks, and dial direction.
- [capture tools](capture-tools.md): current Mac capture commands and offline analysis.
- [public integrations](public-integrations.md): a dated look at meta's glasses and research APIs.
- [gesture models](gesture-models.md): the on-band model's score stream, its nine output labels, and what the app reveals about it.
- [pinch learning experiments](pinch-learning.md): webcam labeling, personal EMG CNN, motion fusion, Meta checkpoint transfer, failed live tests, weight audit, and reproduction commands.

## code and checks

`dashboard/` holds the server, static frontend, and console tests. `instrumentation/` holds the Mac enrollment/connection clients, protocol code, and offline decoders.
`learning/` holds personal pinch recording, labels, datasets, training, and live
comparison. Install `learning/requirements.txt` for those optional ML dependencies.

```sh
python3 -m unittest discover -s instrumentation -p 'test_*.py'
python3 -m unittest discover -s dashboard/tests -p 'test_*.py'
python3 -m unittest discover -s learning/tests -v
node dashboard/tests/test_gesture_animation.mjs
node dashboard/tests/test_hand_model.mjs
ruff check instrumentation dashboard
```

## open work

- verify ADC channel order, electrode mapping, and voltage scaling.
- validate gesture directions and relative wrist axes with labeled trials.
- reduce dropped data and shutdown failures. combined semg/gesture framing is still unresolved; the console uses separate modes.
- establish haptic duration units and native pattern support; client-triggered buzzes now work.
- improve the experimental personal pinch classifiers: reject artifacts, use robust normalization, and evaluate across independently recorded band placements. Current ring/pinky results are not a reliable live controller.
- activate the `thumb_tap` output live and find the app code that reads the native label table. see [gesture models](gesture-models.md).

the superseded clients and early text exports are in [git history](https://github.com/callbacked/neural-band-poc/tree/36b99eaf37ffd7a6116e563744457bfdd52e1af6).
