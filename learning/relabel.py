"""Recompute labels from saved landmarks, preserving the original camera log."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .labels import LABEL_CONFIG, LABEL_VERSION, StableLabel, cue_at, label_frame


def relabel_session(session, output_name='camera.labels-v2.jsonl'):
    session = Path(session)
    if Path(output_name).name != output_name or output_name == 'camera.jsonl':
        raise ValueError('Use a new filename within the session directory')
    source = session / 'camera.jsonl'
    output = session / output_name
    report_path = output.with_suffix('.report.json')
    if output.exists() or report_path.exists():
        raise FileExistsError('Relabel outputs already exist; choose another --output-name')
    metadata = json.loads((session / 'session.json').read_text())
    if metadata['status'] != 'complete':
        raise ValueError('Only complete sessions can be relabeled')
    raw = source.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line]
    starts = [r['host_monotonic_ns'] for r in rows if r['trial'] == 0]
    if not starts:
        raise ValueError('No first-trial frame to anchor the cue schedule')
    width, height = metadata.get('image_width'), metadata.get('image_height')
    if width is None or height is None:
        # Old recordings did not save frame dimensions. Read them from video.
        import cv2
        cap = cv2.VideoCapture(str(session / 'camera.mp4'))
        try:
            width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        finally:
            cap.release()
        if width <= 0 or height <= 0:
            raise ValueError('Cannot establish original image dimensions')
    stability, updated, previous = StableLabel(), [], None
    for row in rows:
        at = row['host_monotonic_ns']
        if previous is not None and at <= previous:
            raise ValueError('Camera timestamps must strictly increase')
        previous = at
        elapsed = (at - starts[0]) / 1e9
        trial, cue, age, remaining = cue_at(metadata['trials'], elapsed)
        if elapsed < 0:
            cue = 'waiting for band'
        if row['trial'] != trial or row['cue'] != cue:
            raise ValueError('Stored cue disagrees with reconstructed schedule; cannot relabel safely')
        labels = label_frame(row['hands'], metadata['hand'], width, height, at, cue, age, remaining, stability)
        updated.append({**row, 'original_label': row['label'], 'original_visual_label': row['visual_label'],
                        'cue_age_seconds': age, 'cue_remaining_seconds': remaining, **labels})
    report = {'label_version': LABEL_VERSION, 'config': LABEL_CONFIG, 'source': source.name,
              'source_sha256': hashlib.sha256(raw).hexdigest(),
              'session_sha256': hashlib.sha256((session / 'session.json').read_bytes()).hexdigest(),
              'image_width': width, 'image_height': height, 'frames': len(rows),
              'before': dict(Counter(r['label'] for r in rows)),
              'after': dict(Counter(r['label'] for r in updated)),
              'visual_by_cue': {cue: dict(Counter(r['visual_label'] for r in updated if r['cue'] == cue))
                                for cue in sorted({r['cue'] for r in rows})},
              'note': 'Pilot-calibrated pseudo-labels. Not verified contact ground truth or held-out accuracy.'}
    payload = ''.join(json.dumps(r) + '\n' for r in updated)
    report['labels_sha256'] = hashlib.sha256(payload.encode()).hexdigest()
    with output.open('x') as handle:
        handle.write(payload)
    with report_path.open('x') as handle:
        handle.write(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--output-name', default='camera.labels-v2.jsonl')
    args = parser.parse_args()
    print(json.dumps(relabel_session(args.session, args.output_name), indent=2))


if __name__ == '__main__':
    main()
