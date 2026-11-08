import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from learning.labels import CLASSES, cue_at, pinch_label, trial_plan
from learning.dataset import build_session


def make_session(path, gap=False, unknown=False):
    path.mkdir(exist_ok=True)
    (path / 'session.json').write_text(json.dumps({'status': 'complete'}))
    rows = [{'event': 'emg_config_received', 'channels': 8, 'sample_rate': 2048}]
    rng = np.random.default_rng(42)
    for i in range(1280):
        label = min(4, i // 256)
        rows.append({'event': 'emg_batch', 'sequence': i + int(gap and i >= 64),
                     'timestamp_us': round(i * 7812.5), 'host_monotonic_ns': round((10 + i / 128) * 1e9),
                     'missing_before': int(gap and i == 64),
                     'samples': (32768 + rng.normal(size=(16, 8)) * (10 + label * 30)).tolist()})
    (path / 'band.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    frames = [{'host_monotonic_ns': round((9.9 + i / 30) * 1e9), 'trial': min(4, max(0, int((i / 30 - .1) // 2))),
               'label': 'unknown' if unknown else CLASSES[min(4, max(0, int((i / 30 - .1) // 2)))]} for i in range(306)]
    (path / 'camera.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in frames))


class LabelTests(unittest.TestCase):
    def hand(self):
        points = [[0., 0., 0.] for _ in range(21)]
        points[5], points[17] = [0., 1., 0.], [1., 1., 0.]
        for tip in (8, 12, 16, 20):
            points[tip] = [1., 0., 0.]
        return points

    def test_all_pinches_and_ambiguous_geometry(self):
        self.assertEqual(pinch_label(self.hand())[0], 'neutral')
        for name, tip in zip(CLASSES[1:], (8, 12, 16, 20)):
            points = self.hand()
            points[tip] = [.1, 0., 0.]
            self.assertEqual(pinch_label(points)[0], name)
        points[8] = [.1, 0., 0.]
        self.assertEqual(pinch_label(points)[0], 'unknown')
        self.assertEqual(pinch_label([])[0], 'unknown')
        points[8] = [float('nan'), 0, 0]
        self.assertEqual(pinch_label(points)[0], 'unknown')

    def test_schedule(self):
        trials = trial_plan(2)
        self.assertEqual(len(trials), 16)
        self.assertEqual(cue_at(trials, 0)[1], 'neutral')
        self.assertEqual(cue_at(trials, 48)[1], 'done')
        self.assertEqual(trials, trial_plan(2))


class DatasetTests(unittest.TestCase):
    def test_windows_gaps_and_unknown_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            make_session(path)
            x, y, ends, report = build_session(path)
            self.assertEqual(x.shape[1:], (512, 8))
            self.assertEqual(set(y), set(range(5)))
            self.assertTrue(np.all(np.diff(ends) > 0))
            count = len(y)
            make_session(path, gap=True)
            _, y, _, report = build_session(path)
            self.assertLess(len(y), count)
            self.assertGreater(report['rejected']['sensor_gap'], 0)
            make_session(path, unknown=True)
            x, y, _, _ = build_session(path)
            self.assertEqual(x.shape, (0, 512, 8))
            self.assertEqual(len(y), 0)

    def test_incomplete_session_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'session.json').write_text('{"status":"failed"}')
            with self.assertRaisesRegex(ValueError, 'not complete'):
                build_session(path)


if __name__ == '__main__':
    unittest.main()
