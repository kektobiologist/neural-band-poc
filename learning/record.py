"""Guided local recording: python -m learning.record --help."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import signal
import subprocess
import sys
import time
from collections import deque

from .labels import cue_at, trial_plan, label_frame, StableLabel, LABEL_VERSION, LABEL_CONFIG

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('band', help='CoreBluetooth UUID used by mac_band_probe')
    parser.add_argument('--model', type=Path, required=True, help='MediaPipe hand_landmarker.task')
    parser.add_argument('--output', type=Path, required=True, help='New session directory, preferably under captures/')
    parser.add_argument('--hand', choices=('left', 'right'), required=True, help='Hand in unmirrored camera input; does not change band settings')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--hold-seconds', type=float, default=3.)
    parser.add_argument('--rest-seconds', type=float, default=3.)
    parser.add_argument('--motion', action='store_true', help='Experimental simultaneous EMG + gyro + quaternion')
    parser.add_argument('--identity-key')
    parser.add_argument('--predictor', type=Path, help='Live sensor prediction checkpoint directory')
    parser.add_argument('--meta-checkpoint', type=Path, help='Frozen adapted Meta checkpoint (.pt)')
    parser.add_argument('--meta-source', type=Path, default=ROOT / 'captures/meta-gni-source')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('repeats must be 1–10 (capture limit: 300 seconds)')
    if not args.model.is_file():
        parser.error('download the MediaPipe model first; see docs/pinch-learning.md')
    import cv2
    import mediapipe as mp

    if not 2 <= args.hold_seconds <= 15 or not 2 <= args.rest_seconds <= 15:
        parser.error('hold and rest must each be 2–15 seconds')
    decoder = None
    if args.predictor and args.meta_checkpoint:
        parser.error('Select only one live predictor')
    if args.meta_checkpoint:
        from .predict_meta import MetaPredictor
        from .live import LiveDecoder, camera_reference
        decoder = LiveDecoder(MetaPredictor(args.meta_checkpoint, args.meta_source))
    if args.predictor:
        from .predict_features import FeaturePredictor
        from .live import LiveDecoder, camera_reference
        decoder = LiveDecoder(FeaturePredictor(args.predictor))
        args.motion = True
    trials = trial_plan(args.repeats, args.seed, rest=args.rest_seconds, hold=args.hold_seconds)
    duration = sum(t['seconds'] for t in trials)
    if duration + 8 > 300:
        parser.error('trial duration plus cleanup must fit within 300 seconds; reduce repeats')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'hand': args.hand, 'camera': args.camera, 'seed': args.seed, 'trials': trials,
                'clock': 'host monotonic_ns; camera timestamp after read; sensor timestamp at decoded receipt',
                'alignment': 'approximate; camera exposure and Bluetooth transport latency uncalibrated',
                'motion_requested': args.motion, 'status': 'starting', 'label_version': LABEL_VERSION, 'label_config': LABEL_CONFIG,
                'model_path': str(args.model.resolve()),
                'model_sha256': hashlib.sha256(args.model.read_bytes()).hexdigest(), 'mediapipe_version': mp.__version__,
                'opencv_version': cv2.__version__, 'predictor': str(args.predictor.resolve()) if args.predictor else None}
    if args.meta_checkpoint:
        manifest.update(predictor=str(args.meta_checkpoint.resolve()), predictor_type='Meta adapted EMG',
                        predictor_sha256=hashlib.sha256(args.meta_checkpoint.read_bytes()).hexdigest(),
                        predictor_context_samples=2048, meta_source=str(args.meta_source.resolve()))
    manifest_path = args.output / 'session.json'
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    save()
    camera = cv2.VideoCapture(args.camera)
    process = writer = None
    frames = log = sensor = tracker = predictions = None
    last_prediction = None
    reference_history = deque(maxlen=120)
    agreements = comparisons = 0
    started = None
    frame_id = 0
    stability = StableLabel()
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open webcam. Check macOS camera permission.')
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=.7, min_hand_presence_confidence=.7,
            min_tracking_confidence=.7)
        tracker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        # Readiness happens before starting the bounded band stream.
        while True:
            ok, preview = camera.read()
            if not ok:
                raise RuntimeError('Webcam stopped returning frames')
            preview = cv2.resize(preview, (960, 540))
            cv2.rectangle(preview, (0, 0), (960, 130), (20, 20, 20), -1)
            cv2.putText(preview, f'{args.hand.upper()} HAND: press SPACE when ready', (15, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, .9, (255, 255, 255), 2)
            cv2.putText(preview, 'Keep fingertips visible. Touch thumb to the named finger.', (15, 78),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1)
            cv2.putText(preview, 'Click this preview first. Q cancels.', (15, 112),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1)
            cv2.imshow('Pinch dataset (unmirrored)', preview)
            key = cv2.waitKey(20) & 0xff
            if key == ord('q'):
                manifest['status'] = 'aborted'
                return
            if key == ord(' '):
                break
        frames = (args.output / 'camera.jsonl').open('x')
        log = (args.output / 'probe.log').open('x')
        if decoder:
            predictions = (args.output / 'predictions.jsonl').open('x')
        command = [sys.executable, str(ROOT / 'instrumentation/mac_band_probe.py'), args.band,
                   '--stream-control', 'raw-emg-motion' if args.motion else 'raw-emg',
                   '--seconds', str(min(300, duration + 8)), '--output', str(args.output / 'band.jsonl')]
        if args.identity_key:
            command += ['--identity-key', str(args.identity_key)]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 100
        partial = ''
        last_ms = -1
        manifest['status'] = 'recording'
        save()
        while True:
            ok, frame = camera.read()
            at = time.monotonic_ns()
            if not ok:
                raise RuntimeError('Webcam stopped returning frames')
            if sensor is None and (args.output / 'band.jsonl').exists():
                sensor = (args.output / 'band.jsonl').open()
            if sensor:
                partial += sensor.read()
                lines = partial.split('\n')
                partial = lines.pop()
                for line in lines:
                    row = json.loads(line)
                    if decoder:
                        decoder.feed(row)
                    if row['event'] == 'emg_batch' and started is None:
                        started = at
            if started is None and time.monotonic() > deadline:
                raise RuntimeError('No decoded EMG within 100 seconds; inspect probe.log')
            elapsed = (at - started) / 1e9 if started else -1
            trial, cue, age, remaining = cue_at(trials, elapsed)
            if elapsed < 0:
                cue = 'waiting for band'
            if cue == 'done':
                manifest['status'] = 'complete'
                break
            if process.poll() is not None:
                raise RuntimeError('Band process ended before trials completed; inspect probe.log')
            # Preserve unmirrored camera pixels and acquisition times for relabeling.
            if writer is None:
                height, width = frame.shape[:2]
                manifest['image_width'], manifest['image_height'] = width, height
                save()
                writer = cv2.VideoWriter(str(args.output / 'camera.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 30, (width, height))
                if not writer.isOpened():
                    raise RuntimeError('Cannot create camera.mp4')
            writer.write(frame)
            ms = max(last_ms + 1, at // 1_000_000)
            last_ms = ms
            result = tracker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                       data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), ms)
            hands = []
            for landmarks, world, handedness in zip(result.hand_landmarks, result.hand_world_landmarks, result.handedness):
                hands.append({'hand': handedness[0].category_name.lower(), 'hand_score': handedness[0].score,
                              'landmarks': [[p.x, p.y, p.z] for p in landmarks],
                              'world_landmarks': [[p.x, p.y, p.z] for p in world]})
            matching = [h for h in hands if h['hand'] == args.hand and h['hand_score'] >= .8]
            labels = label_frame(hands, args.hand, width, height, at, cue, age, remaining, stability)
            label, accepted = labels['visual_label'], labels['label']
            if decoder:
                reference_history.append((at, labels['stable_label']))
                prediction, state = decoder.predict(time.monotonic_ns())
                if prediction is not None:
                    reference = camera_reference(reference_history, prediction['window_end_ns'])
                    prediction['camera_reference'] = reference
                    if reference != 'unknown' and prediction['label'] != 'unknown':
                        comparisons += 1
                        agreements += reference == prediction['label']
                    predictions.write(json.dumps(prediction) + '\n')
                    predictions.flush()
                    last_prediction = prediction
                elif state != 'unchanged':
                    last_prediction = None
            frames.write(json.dumps({'frame': frame_id, 'host_monotonic_ns': at, 'hands': hands,
                                     'trial': trial, 'cue': cue, 'cue_age_seconds': age,
                                     'cue_remaining_seconds': remaining, **labels}) + '\n')
            frames.flush()
            frame_id += 1
            preview = cv2.resize(frame, (960, 540))
            for hand in matching:
                for point in hand['landmarks']:
                    cv2.circle(preview, (int(point[0] * 960), int(point[1] * 540)), 3, (0, 255, 255), -1)
            cv2.rectangle(preview, (0, 0), (960, 125), (20, 20, 20), -1)
            instruction = 'RELAX / OPEN HAND' if cue == 'neutral' else (
                f'THUMB + {cue.upper()}: TOUCH AND HOLD' if trial >= 0 else 'CONNECTING TO BAND...')
            cv2.putText(preview, instruction, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, .9, (255, 255, 255), 2)
            cv2.putText(preview, f'{max(0, remaining):.1f}s remaining | Camera sees: {label} | Q: stop',
                        (15, 78), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 0) if accepted != 'unknown' else (0, 200, 255), 2)
            next_cue = trials[trial + 1]['label'] if 0 <= trial < len(trials) - 1 else 'finish'
            cv2.putText(preview, f'Next: {next_cue}', (15, 110), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1)
            if decoder:
                cv2.rectangle(preview, (0, 390), (960, 540), (20, 20, 20), -1)
                predicted = last_prediction['label'] if last_prediction else 'waiting for fresh data'
                mode = last_prediction['mode'] if last_prediction else state
                color = (0, 230, 0) if labels['stable_label'] == predicted else (0, 180, 255)
                cv2.putText(preview, f'BAND MODEL: {predicted.upper()}', (15, 430), cv2.FONT_HERSHEY_SIMPLEX, 1., color, 2)
                cv2.putText(preview, f'Camera reference: {labels["stable_label"]} | {mode}', (15, 466), cv2.FONT_HERSHEY_SIMPLEX, .7, (255,255,255), 2)
                agreement = f'{100*agreements/comparisons:.1f}%' if comparisons else '--'
                cv2.putText(preview, f'Camera agreement: {agreement} ({comparisons} stable windows) | Q: stop', (15, 505), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,255,255), 1)
            cv2.imshow('Pinch dataset (unmirrored)', preview)
            if cv2.waitKey(1) & 0xff == ord('q'):
                manifest['status'] = 'aborted'
                break
    except BaseException as error:
        manifest.update(status='failed', error=str(error))
        raise
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        if manifest['status'] == 'complete' and process is not None and process.returncode != 0:
            manifest.update(status='failed', error='Band cleanup failed; inspect probe.log')
        if decoder:
            manifest['live_comparison'] = {'agreements': agreements, 'comparisons': comparisons,
                                           'meaning': 'Approximate camera agreement on stable windows; not human ground truth.'}
        manifest.update(frames=frame_id, probe_returncode=process.returncode if process else None)
        save()
        camera.release()
        if writer:
            writer.release()
        if tracker:
            tracker.close()
        for handle in (frames, log, sensor, predictions):
            if handle:
                handle.close()
        cv2.destroyAllWindows()
    print(f'Saved {frame_id} frames to {args.output}; status={manifest["status"]}')


if __name__ == '__main__':
    main()
