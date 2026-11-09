"""Label cued taps from the EMG burst and test what separates them.

python -m learning.taps SESSION [SESSION ...]

The cue gives the class; the first EMG burst after it gives the time. Writes
taps.json into each session and prints, per class, the band model's peak scores
(step 0), then cross-validated accuracy for Meta scores, EMG
features and both. One session uses stratified folds (optimistic); several use
leave-one-session-out, which is the number that predicts live use.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

from .dataset import read_rows
from .features import emg_features

RATE = 2048
# Output order from the Meta AI app's label table (docs/gesture-models.md).
NATIVE_LABELS = ('index_press', 'index_release', 'middle_press', 'middle_release',
                 'thumb_tap', 'thumb_up', 'thumb_down', 'thumb_in', 'thumb_out')


def emg_grid(rows):
    """EMG on a sequence-number grid (NaN for dropped batches) and the host time of sample 0."""
    configs = [r for r in rows if r['event'] == 'emg_config_received']
    if not configs or any(r.get('sample_rate') != RATE or r.get('channels') != 8 for r in configs):
        raise ValueError('Expected eight EMG channels at 2048 Hz')
    batches = [r for r in rows if r['event'] == 'emg_batch']
    if not batches:
        raise ValueError('No EMG batches')
    sequence = np.array([b['sequence'] for b in batches])
    if np.any(np.diff(sequence) <= 0):
        raise ValueError('EMG sequence numbers must increase')
    x = np.full(((sequence[-1] - sequence[0] + 1) * 16, 8), np.nan)
    for batch, s in zip(batches, sequence):
        x[(s - sequence[0]) * 16:][:16] = batch['samples']
    start = (sequence - sequence[0]) * 16 / RATE
    host = np.array([b['host_monotonic_ns'] for b in batches]) / 1e9
    # ponytail: least-delayed receipt anchors the grid; biased late by >= one batch (8 ms)
    # and ignores band/Mac clock drift (tens of ppm). Fit a line if longer sessions need it.
    return x, np.min(host - start)


def device_times(rows):
    """Host-time estimate for a device-timestamped stream, same least-delay anchor."""
    device = np.array([r['timestamp_us'] for r in rows]) / 1e6
    host = np.array([r['host_monotonic_ns'] for r in rows]) / 1e9
    return device + np.min(host - device)


def replay_scores(rows):
    """Re-decode saved packets when the live decoder left scores uninterpreted (older captures)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'instrumentation'))
    from input_service import InputService
    samples, at = [], None
    keep = lambda event, **values: samples.append({**values, 'host_monotonic_ns': at}) if event == 'inference_sample' else None
    reader = InputService(keep, requested_fields=(2, 4))
    for row in rows:
        if row['event'] == 'authenticated_packet':
            at = row['host_monotonic_ns']
            reader.feed(bytes.fromhex(row['plaintext']))
    return samples


def envelope(x, smooth=51):
    """Strongest channel's 25 ms RMS of the first difference (a cheap high-pass),
    in multiples of that channel's session median. Summing channels diluted ring taps."""
    d = np.diff(x, axis=0, prepend=np.full((1, 8), np.nan))
    kernel = np.ones(smooth) / smooth
    channels = np.sqrt(np.stack([np.convolve(d[:, c] ** 2, kernel, 'same') for c in range(8)], axis=1))
    channels /= np.nanmedian(channels, axis=0)
    out = np.full(len(x), np.nan)
    valid = ~np.isnan(channels).any(axis=1)
    out[valid] = channels[valid].max(axis=1)
    return out


def label_taps(x, t0, cues, hi=4., lo=2., search=(.1, 1.6), quiet=.3):
    """One event per cue. Thresholds are multiples of each channel's resting level."""
    env = envelope(x)
    index = lambda t: int(round((t - t0) * RATE))
    events = []
    for cue in cues:
        at = cue['host_monotonic_ns'] / 1e9
        event = {'label': cue['label'], 'cue_time': at, 'onset_time': None}
        i0, i1, i2 = index(at - quiet), index(at + search[0]), index(at + search[1])
        if i0 < 64 or i2 + 448 > len(env) or np.isnan(env[i0:i2]).any():
            events.append({**event, 'status': 'gap'})
            continue
        window = env[i1:i2]
        peak = int(np.argmax(window))
        event['peak_ratio'] = round(float(window[peak]), 2)
        pre = env[i0:i1].max()  # wearers tense slightly in anticipation of the cue
        if cue['label'] == 'rest':
            event['status'] = 'ok' if max(pre, window[peak]) < hi else 'busy' if pre >= hi else 'rest_active'
        elif window[peak] < hi:
            event['status'] = 'missed'
        elif window[peak] < 2 * pre:
            event['status'] = 'busy'  # the tap does not clearly stand out from earlier activity
        else:
            below = np.flatnonzero(window[:peak] < lo)
            if not len(below):
                event['status'] = 'busy'
            else:
                onset = i1 + below[-1] + 1
                event.update(status='ok', onset_time=t0 + onset / RATE, delay=round(t0 + onset / RATE - at, 3))
        events.append(event)
    delays = [e['delay'] for e in events if e.get('delay') is not None]
    typical = float(np.median(delays)) if delays else .4
    for event in events:
        if event['label'] == 'rest' and event['status'] == 'ok':
            event['onset_time'] = event['cue_time'] + typical  # same timing as a typical tap
    return events


def session_features(session, hi=4., lo=2.):
    session = Path(session)
    if json.loads((session / 'session.json').read_text())['status'] != 'complete':
        raise ValueError(f'{session}: session is not complete')
    rows = read_rows(session / 'band.jsonl')
    cues = read_rows(session / 'cues.jsonl')
    x, t0 = emg_grid(rows)
    events = label_taps(x, t0, cues, hi, lo)
    scores = [r for r in rows if r['event'] == 'inference_sample']
    if not scores and any(r['event'] == 'raw_inference_payload' for r in rows):
        scores = replay_scores(rows)
    width = len(scores[0]['scores']) if scores else 0
    score_t = device_times(scores) if scores else np.zeros(0)
    score_v = np.array([r['scores'] for r in scores]).reshape(len(scores), width)
    kept, emg, meta = [], [], []
    for event in events:
        if event['status'] != 'ok':
            continue
        start = int(round((event['onset_time'] - t0) * RATE)) - 64
        window = x[start:start + 512]
        if np.isnan(window).any():
            event['status'] = 'gap'
            continue
        kept.append(event)
        emg.append(window)
        near = (score_t >= event['onset_time'] - .1) & (score_t <= event['onset_time'] + .5)
        meta.append(score_v[near].max(axis=0) if near.any() else np.full(width, np.nan))
    (session / 'taps.json').write_text(json.dumps(events, indent=1) + '\n')
    emg = emg_features(np.array(emg)) if emg else np.zeros((0, 72))
    return events, kept, emg, np.array(meta).reshape(len(kept), width)


def evaluate(X, y, groups):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix
    from sklearn.model_selection import LeaveOneGroupOut, StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if len(set(groups)) > 1:
        cv, how = LeaveOneGroupOut(), 'leave-one-session-out'
    else:
        folds = min(5, min(Counter(y).values()))
        if folds < 2:
            return None
        cv, how = StratifiedKFold(folds, shuffle=True, random_state=0), f'{folds}-fold within one session (optimistic)'
        groups = None
    model = make_pipeline(StandardScaler(), LogisticRegression(class_weight='balanced', max_iter=5000))
    predicted = cross_val_predict(model, X, y, cv=cv, groups=groups)
    classes = sorted(set(y))
    return {'how': how, 'accuracy': accuracy_score(y, predicted), 'balanced': balanced_accuracy_score(y, predicted),
            'classes': classes, 'confusion': confusion_matrix(y, predicted, labels=classes).tolist()}


def rest_normalize(X, y, groups):
    """Subtract each session's mean rest features: a per-wear calibration for band placement."""
    X = X.copy()
    for g in set(groups):
        rest = (groups == g) & (y == 'rest')
        if rest.any():
            X[groups == g] -= np.nanmean(X[rest], axis=0)
    return X


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sessions', nargs='+', type=Path)
    parser.add_argument('--hi', type=float, default=4., help="Tap peak threshold, multiple of the strongest channel's resting level")
    parser.add_argument('--lo', type=float, default=2., help='Onset threshold, same units')
    args = parser.parse_args()
    labels, groups, emg, meta = [], [], [], []
    for number, session in enumerate(args.sessions):
        events, kept, e, m = session_features(session, args.hi, args.lo)
        print(f'\n{session}')
        for label in sorted({ev['label'] for ev in events}):
            mine = [ev for ev in events if ev['label'] == label]
            ok = [ev for ev in mine if ev['status'] == 'ok']
            status = dict(Counter(ev['status'] for ev in mine if ev['status'] != 'ok'))
            delay = np.median([ev['delay'] for ev in ok]) if label != 'rest' and ok else float('nan')
            peak = np.median([ev['peak_ratio'] for ev in mine if 'peak_ratio' in ev] or [np.nan])
            print(f'  {label:>8}: {len(ok)}/{len(mine)} kept  delay {delay:.2f}s  peak {peak:.1f}x  {status or ""}')
        labels += [ev['label'] for ev in kept]
        groups += [number] * len(kept)
        emg.append(e)
        meta.append(m)
    y, groups = np.array(labels), np.array(groups)
    emg = np.concatenate(emg)
    classes = sorted(set(y))
    if len({m.shape[1] for m in meta}) > 1:
        raise ValueError('Sessions report different band model output counts; analyze them separately')
    meta = np.concatenate(meta)
    has_meta = meta.size and not np.isnan(meta).all()
    if has_meta:
        names = NATIVE_LABELS if meta.shape[1] == len(NATIVE_LABELS) else [f'score {i}' for i in range(meta.shape[1])]
        print(f'\nBand model peak score per class (mean over taps; {meta.shape[1]} outputs)')
        print(' ' * 10 + ''.join(f'{n[:11]:>12}' for n in names))
        for label in classes:
            print(f'{label:>10}' + ''.join(f'{v:12.2f}' for v in np.nanmean(meta[y == label], axis=0)))
    else:
        print('\nNo band model scores in these sessions (recorded with --stream raw-emg?)')
    candidates = {'emg features': emg}
    use = np.ones(len(y), bool)
    if has_meta:
        use = ~np.isnan(meta).any(axis=1)  # same taps for every candidate
        candidates = {'band model scores': meta, 'emg features': emg, 'both': np.hstack([emg, meta])}
    print('\nCross-validated logistic regression, rest-normalized per session')
    for name, X in candidates.items():
        result = evaluate(rest_normalize(X[use], y[use], groups[use]), y[use], groups[use])
        if result is None:
            print(f'  {name}: need at least 2 kept taps per class')
            continue
        print(f"  {name:>18}: accuracy {result['accuracy']:.1%}, balanced {result['balanced']:.1%}  [{result['how']}]")
        print('      confusion (rows true, cols predicted): ' + ' '.join(result['classes']))
        for label, row in zip(result['classes'], result['confusion']):
            print(f'      {label:>8} ' + ' '.join(f'{v:3d}' for v in row))


if __name__ == '__main__':
    main()
