"""Bounded live sensor window buffer, independent of the camera and trial cues."""
from collections import deque
import numpy as np
from .features import causal_motion
from .labels import CLASSES


class LiveDecoder:
    def __init__(self, predictor):
        self.predictor = predictor
        self.window_batches = getattr(predictor, 'window_batches', 32)
        self.emg = deque(maxlen=self.window_batches)
        self.motion = deque(maxlen=512)
        self.previous_prediction_sequence = None
        self.configured = False

    def feed(self, row):
        event = row['event']
        if event == 'emg_config_received':
            self.configured = row.get('sample_rate') == 2048 and row.get('channels') == 8
        if event == 'emg_batch':
            self.emg.append(row)
        elif event in ('gyro_sample', 'orientation_sample'):
            self.motion.append(row)
        elif event in ('disconnected', 'probe_error'):
            self.emg.clear()
            self.motion.clear()
            self.previous_prediction_sequence = None
            self.configured = False

    def predict(self, now_ns):
        if not self.configured or len(self.emg) < self.window_batches:
            return None, 'warming up'
        rows = list(self.emg)
        finish = rows[-1]['host_monotonic_ns'] / 1e9
        if not 0 <= now_ns/1e9 - finish <= .35:
            return None, 'sensor stream stale'
        if any(b['sequence'] != a['sequence']+1 or b.get('missing_before', 0)
               for a,b in zip(rows,rows[1:])):
            return None, 'sensor gap'
        device = np.asarray([r['timestamp_us'] for r in rows])/1e6
        host = np.asarray([r['host_monotonic_ns'] for r in rows])/1e9
        if np.any(np.abs(np.diff(device)-16/2048) > .002) or np.any(np.diff(host)<0) or abs(host[-1]-host[0]-(device[-1]-device[0])) > .08:
            return None, 'sensor timing gap'
        sequence = rows[-1]['sequence']
        if self.previous_prediction_sequence is not None and sequence-self.previous_prediction_sequence < 8:
            return None, 'unchanged'
        x = np.asarray([r['samples'] for r in rows], dtype=np.float32).reshape(1,self.window_batches*16,8)
        if getattr(self.predictor, 'requires_motion', True):
            motion, valid = causal_motion(list(self.motion), [finish])
        else:
            motion, valid = None, None
        prediction, fallback = self.predictor.predict(x, motion, valid)
        self.previous_prediction_sequence = sequence
        label = CLASSES[int(prediction[0])] if prediction[0] >= 0 else 'unknown'
        return {'label': label, 'sequence': sequence, 'window_end_ns': rows[-1]['host_monotonic_ns'],
                'mode': 'EMG fallback' if fallback[0] else getattr(self.predictor, 'mode', 'EMG + motion'),
                'computed_at_ns': now_ns}, 'ok'


def camera_reference(history, end_ns):
    """Compare only full, stable camera intervals; unknown is never counted wrong."""
    points = list(history)
    start = end_ns - 250_000_000
    before = [i for i, (at, _) in enumerate(points) if at <= start]
    after = [i for i, (at, _) in enumerate(points) if at >= end_ns]
    if not before or not after:
        return 'unknown'
    selected = points[before[-1]:after[0]+1]
    if len(selected)<2 or any(b[0]-a[0] > 150_000_000 for a,b in zip(selected,selected[1:])):
        return 'unknown'
    labels = {label for _,label in selected}
    return next(iter(labels)) if len(labels)==1 and 'unknown' not in labels else 'unknown'
