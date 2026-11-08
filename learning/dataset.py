"""Build conservative 250 ms windows, without crossing missing sensor batches."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path

import numpy as np
from .labels import CLASSES

BATCHES = 32
SAMPLES = 512
RATE = 2048


def read_rows(path):
    with Path(path).open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_session(session, labels_name="camera.jsonl"):
    session = Path(session)
    metadata = json.loads((session / 'session.json').read_text())
    if metadata['status'] != 'complete':
        raise ValueError(f'{session}: session is not complete')
    rows = read_rows(session / 'band.jsonl')
    configs = [r for r in rows if r['event'] == 'emg_config_received']
    if not configs or any(r.get('sample_rate') != RATE or r.get('channels') != 8 for r in configs):
        raise ValueError('Expected eight channels at 2048 Hz')
    batches = [r for r in rows if r['event'] == 'emg_batch']
    if Path(labels_name).name != labels_name:
        raise ValueError('labels_name must be a filename within the session directory')
    labels_path = session / labels_name
    if labels_name != 'camera.jsonl':
        provenance = json.loads(labels_path.with_suffix('.report.json').read_text())
        for name, expected in [('camera.jsonl', provenance['source_sha256']),
                               ('session.json', provenance['session_sha256']),
                               (labels_name, provenance['labels_sha256'])]:
            if hashlib.sha256((session / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Label provenance mismatch: {name}')
    frames = read_rows(labels_path)
    times = np.asarray([r['host_monotonic_ns'] / 1e9 for r in frames])
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError('Camera timestamps must increase')
    x, y, ends = [], [], []
    rejected = Counter()
    for end in range(BATCHES, len(batches) + 1, 8):
        window = batches[end - BATCHES:end]
        if any(b['sequence'] != a['sequence'] + 1 or b.get('missing_before', 0)
               for a, b in zip(window, window[1:])):
            rejected['sensor_gap'] += 1
            continue
        device = np.asarray([r['timestamp_us'] for r in window]) / 1e6
        # Timestamp resets, reordering, and unexpected device cadence are rejected.
        if np.any(np.abs(np.diff(device) - 16 / RATE) > .002):
            rejected['device_timing'] += 1
            continue
        host = np.asarray([r['host_monotonic_ns'] / 1e9 for r in window])
        if np.any(np.diff(host) < 0) or abs((host[-1] - host[0]) - (device[-1] - device[0])) > .08:
            rejected['receipt_jitter'] += 1
            continue
        finish = host[-1]
        start = finish - SAMPLES / RATE
        # Include frames bracketing the entire input window, not just its endpoint.
        left = np.searchsorted(times, start, side='right') - 1
        right = np.searchsorted(times, finish, side='left')
        if left < 0 or right >= len(times) or np.max(np.diff(times[left:right + 1])) > .15:
            rejected['camera_gap'] += 1
            continue
        labels = {r['label'] for r in frames[left:right + 1]}
        trials = {r['trial'] for r in frames[left:right + 1]}
        if len(labels) != 1 or 'unknown' in labels or len(trials) != 1:
            rejected['uncertain_or_transition'] += 1
            continue
        values = np.asarray([r['samples'] for r in window], dtype=np.float32)
        if values.shape != (BATCHES, 16, 8) or not np.isfinite(values).all():
            raise ValueError('Invalid EMG sample shape or values')
        x.append(values.reshape(SAMPLES, 8))
        y.append(CLASSES.index(next(iter(labels))))
        ends.append(finish)
    report = {'session': str(session.resolve()), 'windows': len(y), 'rejected': dict(rejected),
              'labels_file': labels_name, 'labels_sha256': hashlib.sha256(labels_path.read_bytes()).hexdigest(),
              'class_counts': dict(Counter(CLASSES[v] for v in y)),
              'emg_batches': len(batches), 'missing_batches': sum(r.get('missing_before', 0) for r in batches),
              'camera_frames': len(frames), 'accepted_camera_frames': sum(r['label'] != 'unknown' for r in frames),
              'gyro_samples': sum(r['event'] == 'gyro_sample' for r in rows),
              'orientation_samples': sum(r['event'] == 'orientation_sample' for r in rows),
              'alignment': 'approximate host receipt; uncalibrated sensor/camera latency'}
    return np.asarray(x, dtype=np.float32).reshape(-1, SAMPLES, 8), np.asarray(y, dtype=np.int64), np.asarray(ends), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--labels-name', default='camera.jsonl')
    args = parser.parse_args()
    x, y, ends, report = build_session(args.session, args.labels_name)
    suffix = '' if args.labels_name == 'camera.jsonl' else '.' + Path(args.labels_name).stem
    np.savez_compressed(args.session / f'windows{suffix}.npz', x=x, y=y, ends=ends)
    (args.session / f'quality{suffix}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not len(y):
        raise SystemExit('No usable windows. Inspect video, hand selection, labels, and sensor timing.')


if __name__ == '__main__':
    main()
