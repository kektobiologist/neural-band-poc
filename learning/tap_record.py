"""Cue-only tap recording, no webcam: python -m learning.tap_record --help.

Each cue asks for one quick thumb tap; `learning.taps` later finds the actual
tap from the EMG burst after the cue. By default the band also streams its own
model scores alongside raw EMG (step 0 probe).
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def schedule(gestures, repeats, seed, baseline, gap, jitter):
    """Shuffled tap cues plus as many relaxed 'rest' cues as each gesture gets."""
    rng = random.Random(seed)
    labels = [g for g in (*gestures, 'rest') for _ in range(repeats)]
    rng.shuffle(labels)
    cues, at = [], baseline
    for label in labels:
        cues.append({'label': label, 'offset_seconds': round(at, 3)})
        # Jitter stops the wearer from tapping to a rhythm instead of the cue.
        at += gap + rng.uniform(0, jitter)
    return cues, at + gap


def show(label, index, total):
    text = '. . .  stay relaxed  . . .' if label == 'rest' else f'TAP   thumb + {label.upper()}'
    sys.stdout.write(f'\033[2J\033[H\n\n\n        {text}\n\n\n        cue {index + 1}/{total}   (Ctrl-C stops)\n')
    if label != 'rest':
        sys.stdout.write('\a')
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('band', help='CoreBluetooth UUID used by mac_band_probe')
    parser.add_argument('--output', type=Path, required=True, help='New session directory, preferably under captures/')
    parser.add_argument('--gestures', nargs='+', default=['index', 'middle', 'ring', 'pinky'],
                        help='Names shown in cues; any custom gesture name works')
    parser.add_argument('--repeats', type=int, default=12, help='Cues per gesture (and rest cues)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--baseline', type=float, default=5., help='Relaxed seconds before the first cue')
    parser.add_argument('--gap', type=float, default=2., help='Minimum seconds between cues')
    parser.add_argument('--jitter', type=float, default=.5, help='Extra random seconds between cues')
    parser.add_argument('--stream', choices=('raw-emg-inference', 'raw-emg'), default='raw-emg-inference',
                        help='raw-emg-inference adds the band model scores')
    parser.add_argument('--identity-key', help='Keychain reference or PEM override; defaults to the saved band identity')
    args = parser.parse_args()
    if 'rest' in args.gestures or len(set(args.gestures)) != len(args.gestures):
        parser.error('gesture names must be unique and not "rest"')
    if args.gap < 1.5 or args.jitter < 0:
        parser.error('gap must be at least 1.5 seconds so taps do not overlap the analysis window')
    cues, duration = schedule(args.gestures, args.repeats, args.seed, args.baseline, args.gap, args.jitter)
    if duration + 8 > 300:
        parser.error(f'session would take {duration:.0f}s; capture limit is ~290s, reduce --repeats')

    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {'schema_version': 1, 'kind': 'tap-cues', 'created_utc': datetime.now(timezone.utc).isoformat(),
                'gestures': args.gestures, 'repeats': args.repeats, 'seed': args.seed, 'stream': args.stream,
                'baseline': args.baseline, 'gap': args.gap, 'jitter': args.jitter, 'status': 'starting',
                'clock': 'host monotonic_ns for cues and sensor receipt; no camera'}
    manifest_path = args.output / 'session.json'
    save = lambda: manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    save()
    print(f'{len(cues)} cues, about {duration:.0f}s. Tap once per cue, quickly, then relax.')
    print('Close the dashboard and other band clients first.')
    process = log = sensor = cue_log = None
    try:
        input('Band on, hand relaxed. Press Enter to connect... ')
        log = (args.output / 'probe.log').open('x')
        cue_log = (args.output / 'cues.jsonl').open('x')
        command = [sys.executable, str(ROOT / 'instrumentation/mac_band_probe.py'), args.band,
                   '--stream-control', args.stream, '--seconds', str(min(300, duration + 8)),
                   '--output', str(args.output / 'band.jsonl')]
        if args.identity_key:
            command += ['--identity-key', str(args.identity_key)]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        manifest['status'] = 'connecting'
        save()
        deadline, started, partial = time.monotonic() + 100, None, ''
        while started is None:
            if process.poll() is not None:
                raise RuntimeError('Band process ended before EMG arrived; inspect probe.log')
            if time.monotonic() > deadline:
                raise RuntimeError('No decoded EMG within 100 seconds; inspect probe.log')
            if sensor is None and (args.output / 'band.jsonl').exists():
                sensor = (args.output / 'band.jsonl').open()
            if sensor:
                partial += sensor.read()
                if '"event": "emg_batch"' in partial:
                    started = time.monotonic_ns()
                partial = partial[partial.rfind('\n') + 1:]
            time.sleep(.02)
        manifest['status'] = 'recording'
        save()
        sys.stdout.write('\033[2J\033[H\n\n\n        relax...\n')
        sys.stdout.flush()
        for index, cue in enumerate(cues):
            target = started + int(cue['offset_seconds'] * 1e9)
            while time.monotonic_ns() < target:
                if process.poll() is not None:
                    raise RuntimeError('Band process ended before cues completed; inspect probe.log')
                time.sleep(.002)
            show(cue['label'], index, len(cues))
            cue_log.write(json.dumps({'index': index, 'label': cue['label'], 'host_monotonic_ns': time.monotonic_ns()}) + '\n')
            cue_log.flush()
        time.sleep(args.gap)
        manifest['status'] = 'complete'
    except KeyboardInterrupt:
        manifest['status'] = 'aborted'
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
        manifest['probe_returncode'] = process.returncode if process else None
        save()
        for handle in (log, sensor, cue_log):
            if handle:
                handle.close()
    print(f'\nSaved {args.output}; status={manifest["status"]}')


if __name__ == '__main__':
    main()
