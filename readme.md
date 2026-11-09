# neural band poc

https://github.com/user-attachments/assets/4fc157bc-b579-480d-971b-bae8bdbb86fa

live sEMG readings from a meta neural band connected directly to a mac. no glasses or phone needed for the streams tested here.

Need a fresh owner identity without Android? The new [Mac enrollment command](docs/mac-enrollment.md)
opens Meta sign-in, enrolls a locally generated Keychain identity, and checks it on a fresh
connection before updating the dashboard. Enrollment and fresh-connection owner
trust were validated on Meta Band 00Z9 on November 9, 2026.

there's a local console with eight channels, a 3d gesture hand, and a pinch and roll dial. you can find and connect the band from there too.

## run it

macos + python 3.11. allow bluetooth access for the terminal when asked.
reuse the enrolled owner key from the shared macOS Keychain registry; ordinary
connections do not need unpairing, a reset, Android, or another Meta login.
for a missing/rejected identity, follow the [Mac connection and recovery guide](docs/mac-enrollment.md).

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m dashboard.server
```

open [localhost:8765](http://localhost:8765). put the band in pairing mode, hit find band, choose it, then start. it remembers the band after that.

pick hand + dial for gestures, or semg for raw readings. hand sessions run for up to five minutes; semg runs for a minute. stop ends the session. captures stay local.

the **Try a buzz** panel sends client-controlled haptic feedback, including quick double buzzes and a four-intensity comparison. [haptics controls, protocol, and test results](docs/haptics.md).

left wrist works too. choose your band hand before starting, or leave it on use band setting. it checks the setting on the band and adjusts the dial direction. [wire details and cli](docs/handedness.md).

## train personal pinch gestures

A webcam-supervised recording, training and live-test workflow lives in `learning/`, starting with neutral and thumb-to-index/middle/ring/pinky pinches. We tested an EMG CNN, EMG/motion feature fusion, and adaptation of Meta's public checkpoint. Offline gains did not carry over reliably to fresh live sessions; this is experimental, not a dependable gesture controller. [Experiment log, results, setup and commands](docs/pinch-learning.md). Recordings and trained weights stay local under ignored `captures/`. A follow-up records cued taps without a webcam and checks whether the band's own model scores separate ring/pinky taps: [tap learning](docs/tap-learning.md).

## what would be cool

training a model for more hand gestures and even better hand tracking (as in, you can see your fingers articulate freely)

[doing that thing meta did where you can write on a surface and it turns your gestures to text](https://www.meta.com/help/ai-glasses/866944989643926/)



## still figuring out

raw readings are experimental adc values. voltage scaling and electrode mapping aren't verified, and some data gets dropped. semg and gestures run separately for now since running both made things lag.

the hand shows recognized taps, holds and swipes. it isn't tracking every finger joint, and ring/pinky gestures aren't supported (same behavior when used natively with the glasses so it's probably not trained on those gestures) the dial only changes the number in the console.

[findings](docs/findings.md) · [gesture references](docs/gestures.md) · [protocol notes](docs/protocol.md) · [capture tools](docs/capture-tools.md) · [gesture models](docs/gesture-models.md)

shoutout astra for reviving this project lol, this definitely contains a bunch of unreadable slop though, I would advise combing through this repo with an agent.
