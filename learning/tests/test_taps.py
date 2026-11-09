import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from learning.tap_record import Pacer, schedule
from learning.taps import channel_envelopes, evaluate, live_level, main, session_features

GESTURES = ['index', 'ring', 'pinky']


def make_session(path, seed=0, drop=200):
    """Synthetic band: class-specific EMG bursts 0.35 s after each cue, scores to match."""
    rng = np.random.default_rng(seed)
    path.mkdir()
    (path / 'session.json').write_text(json.dumps({'status': 'complete'}))
    cues, end = schedule(GESTURES, 8, seed, 3., 2., .5)
    batches = int((end + 1) * 128)
    x = rng.normal(size=(batches * 16, 8)) * 20
    host0 = 100.
    for cue in cues:
        cue['host_monotonic_ns'] = round((host0 + cue['offset_seconds']) * 1e9)
        if cue['label'] != 'rest':
            k = GESTURES.index(cue['label'])
            start = int((cue['offset_seconds'] + .35) * 2048)
            x[start:start + 250, [k, k + 3]] += rng.normal(size=(250, 2)) * 300
    rows = [{'event': 'emg_config_received', 'channels': 8, 'sample_rate': 2048}]
    for i in range(batches):
        if i == drop:
            continue
        rows.append({'event': 'emg_batch', 'sequence': 7 + i, 'timestamp_us': 5_000_000 + round(i * 7812.5),
                     'host_monotonic_ns': round((host0 + (i + 1) / 128 + rng.uniform(.01, .04)) * 1e9),
                     'samples': (32768 + x[i * 16:(i + 1) * 16]).round().tolist()})
    for j in range(int(end * 60)):
        t = j / 60
        scores = np.full(9, -6.) + rng.normal(size=9) * .2
        for cue in cues:
            if cue['label'] != 'rest' and 0 < t - cue['offset_seconds'] - .35 < .2:
                scores[GESTURES.index(cue['label']) * 2] = 2.
        rows.append({'event': 'inference_sample', 'timestamp_us': 9_000_000 + round(t * 1e6),
                     'host_monotonic_ns': round((host0 + t + rng.uniform(.01, .03)) * 1e9), 'scores': scores.tolist()})
    (path / 'band.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (path / 'cues.jsonl').write_text(''.join(json.dumps({'label': c['label'], 'host_monotonic_ns': c['host_monotonic_ns']}) + '\n' for c in cues))
    return cues


class TapTests(unittest.TestCase):
    def test_schedule_is_balanced_and_jittered(self):
        cues, end = schedule(['a', 'b'], 5, 1, 4., 2., .5)
        self.assertEqual(sorted(c['label'] for c in cues), ['a'] * 5 + ['b'] * 5 + ['rest'] * 5)
        gaps = np.diff([c['offset_seconds'] for c in cues])
        self.assertTrue(np.all(gaps >= 2.) and np.all(gaps <= 2.5) and gaps.std() > 0)
        self.assertEqual(cues[0]['offset_seconds'], 4.)

    def test_pacer_waits_for_settle_and_reports_misses(self):
        pacer = Pacer()
        self.assertIsNone(pacer.update(.05, 50.))  # learning.taps ignores the first 0.1 s too
        self.assertIsNone(pacer.update(.8, 9.))
        self.assertIsNone(pacer.update(1., 1.5))
        self.assertIsNone(pacer.update(1.2, 3.))  # back above lo restarts settling
        self.assertIsNone(pacer.update(1.3, 1.))
        self.assertEqual(pacer.update(1.6, 1.), 'tap')
        missed = Pacer()
        self.assertIsNone(missed.update(1., 3.9))
        self.assertEqual(missed.update(1.6, 1.), 'missed')
        restless = Pacer()
        restless.update(.5, 9.)
        self.assertEqual(restless.update(3., 3.), 'tap')

    def test_live_level_matches_offline_envelope(self):
        x = np.random.default_rng(1).normal(size=(4096, 8)) * 20
        x[3000:3200, 2] *= 10
        scale = np.nanmedian(channel_envelopes(x), axis=0)
        # Offline windows are centred; the live window ends at the newest sample.
        self.assertAlmostEqual(live_level(x[:3126], scale), (channel_envelopes(x)[3100] / scale).max())

    def test_onsets_features_and_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / 's'
            make_session(session)
            events, kept, emg, meta = session_features(session)
            self.assertTrue((session / 'taps.json').exists())
            taps = [e for e in events if e['label'] != 'rest']
            delays = [e['delay'] for e in taps if e['status'] == 'ok']
            self.assertGreaterEqual(len(delays), len(taps) - 1)  # one cue may hit the dropped batch
            self.assertLess(abs(np.median(delays) - .35), .03)
            self.assertTrue(all(e['status'] == 'ok' for e in events if e['label'] == 'rest'))
            self.assertEqual(emg.shape, (len(kept), 72))
            self.assertFalse(np.isnan(meta).any())
            y = np.array([e['label'] for e in kept])
            for X in (emg, meta):
                self.assertGreater(evaluate(X, y, np.zeros(len(y)))['balanced'], .9)

    def test_missed_tap_and_cli_report(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = [Path(directory) / name for name in ('a', 'b')]
            for seed, session in enumerate(sessions):
                make_session(session, seed)
            cues = [json.loads(line) for line in (sessions[0] / 'cues.jsonl').read_text().splitlines()]
            cues.append({'label': 'ring', 'host_monotonic_ns': cues[-1]['host_monotonic_ns'] + int(1.5e9)})
            (sessions[0] / 'cues.jsonl').write_text(''.join(json.dumps(c) + '\n' for c in cues))
            output = io.StringIO()
            argv, sys.argv = sys.argv, ['taps', *map(str, sessions)]
            try:
                with contextlib.redirect_stdout(output):
                    main()
            finally:
                sys.argv = argv
            report = output.getvalue()
            self.assertIn("'missed': 1", report)
            self.assertIn('leave-one-session-out', report)
            self.assertIn('index_press', report)


if __name__ == '__main__':
    unittest.main()
