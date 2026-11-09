"""Cue-only tap recording, no webcam: python -m learning.tap_record --help.

Each cue asks for one quick thumb tap; `learning.taps` later finds the actual
tap from the EMG burst after the cue. By default the band also streams its own
model scores alongside raw EMG (step 0 probe).

Pacing is live: the same burst detector moves to the next cue once a tap has
settled, and a cue with no tap is repeated once at the end.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

import numpy as np

from .taps import channel_envelopes, live_level

ROOT = Path(__file__).resolve().parents[1]
PROBE_SECONDS = 290


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


class Pacer:
    """Ends a tap cue once a burst above hi has stayed below lo for `settle` seconds.

    Thresholds match learning.taps defaults: multiples of each channel's resting level.
    """
    def __init__(self, hi=4., lo=2., settle=.3, ignore=.1, timeout=1.6, give_up=3.):
        self.hi, self.lo, self.settle, self.ignore, self.timeout, self.give_up = hi, lo, settle, ignore, timeout, give_up
        self.seen, self.quiet_since = False, None

    def update(self, t, level):
        """t: seconds since the cue. Returns None, 'tap' or 'missed'."""
        if t < self.ignore:
            return None  # learning.taps also ignores the first 0.1 s
        if level >= self.hi:
            self.seen, self.quiet_since = True, None
        elif self.seen and level < self.lo:
            self.quiet_since = t if self.quiet_since is None else self.quiet_since
            if t - self.quiet_since >= self.settle:
                return 'tap'
        else:
            self.quiet_since = None
        if not self.seen and t >= self.timeout:
            return 'missed'
        if t >= self.give_up:
            return 'tap' if self.seen else 'missed'
        return None


def show(label, done, total, note=''):
    text = '. . .  stay relaxed  . . .' if label == 'rest' else f'TAP   thumb + {label.upper()}'
    sys.stdout.write(f'\033[2J\033[H\n\n\n        {text}\n\n\n        cue {done + 1}/{total}   {note}\n'
                     '        (Ctrl-C stops)\n')
    if label != 'rest':
        sys.stdout.write('\a')
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('band', help='CoreBluetooth UUID used by mac_band_probe')
    parser.add_argument('--output', type=Path, required=True, help='New session directory, preferably under captures/')
    parser.add_argument('--gestures', nargs='+', default=['index', 'middle', 'ring', 'pinky'],
                        help='Names shown in cues; any custom gesture name works')
    parser.add_argument('--repeats', type=int, default=12, help='Cues per gesture (and rest cues)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--baseline', type=float, default=5., help='Relaxed seconds before the first cue')
    parser.add_argument('--gap', type=float, default=2., help='Seconds a rest cue lasts')
    parser.add_argument('--jitter', type=float, default=.5, help='Extra random seconds before each next cue')
    parser.add_argument('--hi', type=float, default=4., help='Live tap threshold; see learning.taps --hi')
    parser.add_argument('--lo', type=float, default=2., help='Live settle threshold; see learning.taps --lo')
    parser.add_argument('--stream', choices=('raw-emg-inference', 'raw-emg'), default='raw-emg-inference',
                        help='raw-emg-inference adds the band model scores')
    parser.add_argument('--identity-key', help='Keychain reference or PEM override; defaults to the saved band identity')
    args = parser.parse_args()
    if 'rest' in args.gestures or len(set(args.gestures)) != len(args.gestures):
        parser.error('gesture names must be unique and not "rest"')
    if args.gap < 1.9 or args.jitter < 0:
        parser.error('gap must be at least 1.9 seconds: learning.taps checks rest cues for 1.6 s')
    cues, duration = schedule(args.gestures, args.repeats, args.seed, args.baseline, args.gap, args.jitter)
    if duration + 8 > PROBE_SECONDS:
        parser.error(f'session could take {duration:.0f}s; capture limit is ~{PROBE_SECONDS - 10}s, reduce --repeats')
    rng = random.Random(args.seed + 1)

    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {'schema_version': 2, 'kind': 'tap-cues', 'created_utc': datetime.now(timezone.utc).isoformat(),
                'gestures': args.gestures, 'repeats': args.repeats, 'seed': args.seed, 'stream': args.stream,
                'baseline': args.baseline, 'gap': args.gap, 'jitter': args.jitter, 'status': 'starting',
                'pacing': {'mode': 'live', 'hi': args.hi, 'lo': args.lo, 'settle': .3, 'min_gap': 1.5, 'retries': 1},
                'clock': 'host monotonic_ns for cues and sensor receipt; no camera'}
    manifest_path = args.output / 'session.json'
    save = lambda: manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    save()
    print(f'{len(cues)} cues, at most about {duration:.0f}s plus repeats. Tap once per cue, quickly, then relax.')
    print('Close the dashboard and other band clients first.')
    process = log = sensor = cue_log = None
    recent, baseline, partial = deque(maxlen=128), [], ''

    def pump():
        """Read new EMG from the growing capture; fail fast if the probe died."""
        nonlocal partial, sensor
        if process.poll() is not None:
            raise RuntimeError('Band process ended early; inspect probe.log')
        if sensor is None:
            if not (args.output / 'band.jsonl').exists():
                return 0
            sensor = (args.output / 'band.jsonl').open()
        partial += sensor.read()
        lines = partial.split('\n')
        partial = lines.pop()
        count = 0
        for line in lines:
            if '"event": "emg_batch"' in line:
                samples = json.loads(line)['samples']
                recent.extend(samples)
                if baseline is not None:
                    baseline.extend(samples)
                count += 1
        return count

    try:
        input('Band on, hand relaxed. Press Enter to connect... ')
        log = (args.output / 'probe.log').open('x')
        cue_log = (args.output / 'cues.jsonl').open('x')
        command = [sys.executable, str(ROOT / 'instrumentation/mac_band_probe.py'), args.band,
                   '--stream-control', args.stream, '--seconds', str(PROBE_SECONDS),
                   '--output', str(args.output / 'band.jsonl')]
        if args.identity_key:
            command += ['--identity-key', str(args.identity_key)]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        manifest['status'] = 'connecting'
        save()
        deadline = time.monotonic() + 100
        while not pump():
            if time.monotonic() > deadline:
                raise RuntimeError('No decoded EMG within 100 seconds; inspect probe.log')
            time.sleep(.02)
        started = time.monotonic()
        manifest['status'] = 'recording'
        save()
        sys.stdout.write('\033[2J\033[H\n\n\n        relax...\n')
        sys.stdout.flush()
        baseline.clear()
        while time.monotonic() < started + args.baseline:
            pump()
            time.sleep(.01)
        # ponytail: resting levels come from the baseline only; a session-long median would
        # track band drift, but the 2× gap between the live thresholds and taps absorbs it.
        scale = np.maximum(np.nanmedian(channel_envelopes(np.array(baseline, dtype=np.float64)), axis=0), 1e-9)
        baseline = None
        manifest['live_scale'] = [round(float(v), 3) for v in scale]
        save()
        end = started + PROBE_SECONDS - 14  # leave time for the trailing window and stream shutdown
        queue = [(cue['label'], 0) for cue in cues]
        done = retries = 0
        note = ''
        while queue:
            if time.monotonic() > end:
                manifest['skipped_for_time'] = len(queue)
                break
            label, attempt = queue.pop(0)
            show(label, done, done + 1 + len(queue), note)
            cued_ns = time.monotonic_ns()
            cued = cued_ns / 1e9
            if label == 'rest':
                result, earliest = 'rest', cued + args.gap
                while time.monotonic() < earliest:
                    pump()
                    time.sleep(.005)
            else:
                pacer = Pacer(args.hi, args.lo)
                result = None
                while result is None:
                    if pump() and len(recent) > 52:
                        result = pacer.update(time.monotonic() - cued, live_level(list(recent), scale))
                    time.sleep(.002)
                earliest = max(cued + 1.5, time.monotonic())
                if result == 'missed' and attempt == 0:
                    queue.append((label, 1))
                    retries += 1
            note = {'tap': 'got it', 'missed': 'no tap seen' + (', will repeat' if attempt == 0 else ''), 'rest': ''}[result]
            cue_log.write(json.dumps({'index': done, 'label': label, 'host_monotonic_ns': cued_ns,
                                      'attempt': attempt, 'live': result}) + '\n')
            cue_log.flush()
            done += 1
            earliest += rng.uniform(0, args.jitter)
            while time.monotonic() < earliest:
                pump()
                time.sleep(.005)
        manifest['retries'] = retries
        end_at = time.monotonic() + 2.
        while time.monotonic() < end_at:  # trailing data for the last cue's analysis window
            pump()
            time.sleep(.01)
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
