import json
from pathlib import Path
import tempfile
import unittest

from learning.labels import visual_pinch_label, StableLabel, label_frame
from learning.relabel import relabel_session
from learning.dataset import build_session
from learning.tests.test_pipeline import make_session


def hand(tip=None):
    image = [[.25, .6, 0.] for _ in range(21)]
    world = [[0., 0., 0.] for _ in range(21)]
    image[5], image[17] = [.2, .4, 0.], [.6, .4, 0.]
    world[5], world[17] = [0., 1., 0.], [1., 1., 0.]
    for i in (8, 12, 16, 20):
        image[i], world[i] = [.85, .6, 0.], [1.5, 0., 0.]
    if tip:
        image[tip], world[tip] = [.35, .6, 0.], [.5, 0., 0.]
    return {'landmarks': image, 'world_landmarks': world, 'hand': 'right', 'hand_score': .99}


class GeometryTests(unittest.TestCase):
    def test_all_classes_and_looser_world_guard(self):
        self.assertEqual(visual_pinch_label(hand(), 1920, 1080)[0], 'neutral')
        for tip, name in zip((8, 12, 16, 20), ('index', 'middle', 'ring', 'pinky')):
            self.assertEqual(visual_pinch_label(hand(tip), 1920, 1080)[0], name)

    def test_aspect_ratio_is_accounted_for(self):
        h = hand(8)
        h['landmarks'][8] = [.25, .8, 0.]
        label, details = visual_pinch_label(h, 1920, 1080)
        self.assertAlmostEqual(details['image_distances'][0], .28125)
        self.assertEqual(label, 'index')
        self.assertEqual(visual_pinch_label(h, 1080, 1920)[0], 'unknown')

    def test_depth_overlap_multiple_candidates_and_tracking_failures(self):
        h = hand(8)
        h['world_landmarks'][8] = [.9, 0., 0.]
        self.assertEqual(visual_pinch_label(h, 1920, 1080)[0], 'unknown')
        h = hand(8)
        h['landmarks'][12], h['world_landmarks'][12] = h['landmarks'][8], h['world_landmarks'][8]
        self.assertEqual(visual_pinch_label(h, 1920, 1080)[0], 'unknown')
        self.assertEqual(visual_pinch_label(hand(8), 20, 20)[0], 'unknown')
        h['landmarks'][0][0] = float('nan')
        self.assertEqual(visual_pinch_label(h, 1920, 1080)[0], 'unknown')
        self.assertEqual(visual_pinch_label({}, 1920, 1080)[0], 'unknown')

    def test_dwell_resets_on_loss_gap_and_class_change(self):
        stable = StableLabel()
        for t in (0, 50, 100):
            self.assertEqual(stable.update('index', t * 1_000_000), 'unknown')
        self.assertEqual(stable.update('index', 150_000_000), 'index')
        self.assertEqual(stable.update('unknown', 180_000_000), 'unknown')
        self.assertEqual(stable.update('index', 200_000_000), 'unknown')
        self.assertEqual(stable.update('index', 400_000_000), 'unknown')
        self.assertEqual(stable.update('middle', 430_000_000), 'unknown')

    def test_prompt_never_invents_label_or_overrides_ambiguity(self):
        stable = StableLabel()
        for t in (0, 50, 100, 150, 200):
            result = label_frame([hand(12)], 'right', 1920, 1080, t * 1_000_000,
                                 'pinky', 2., 2., stable)
        self.assertEqual(result['visual_label'], 'middle')
        self.assertEqual(result['stable_label'], 'middle')
        self.assertEqual(result['label'], 'unknown')
        result = label_frame([hand(12), hand(12)], 'right', 1920, 1080, 250_000_000,
                             'middle', 2., 2., stable)
        self.assertEqual(result['label'], 'unknown')


class RelabelTests(unittest.TestCase):
    def fixture(self, path):
        make_session(path)
        (path / 'session.json').write_text(json.dumps({'status': 'complete', 'hand': 'right',
            'image_width': 1920, 'image_height': 1080, 'trials': [{'label': 'neutral', 'seconds': 12}]}))
        rows = [{'frame': i, 'host_monotonic_ns': 10_000_000_000 + i * 33_333_333,
                 'hands': [hand()], 'trial': 0, 'cue': 'neutral', 'visual_label': 'neutral',
                 'label': 'neutral'} for i in range(300)]
        (path / 'camera.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def test_original_preserved_and_modified_sidecar_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.fixture(path)
            before = (path / 'camera.jsonl').read_bytes()
            report = relabel_session(path)
            self.assertEqual(before, (path / 'camera.jsonl').read_bytes())
            self.assertGreater(report['after']['neutral'], 0)
            x, _, _, quality = build_session(path, 'camera.labels-v2.jsonl')
            self.assertGreater(len(x), 0)
            self.assertEqual(quality['labels_file'], 'camera.labels-v2.jsonl')
            with self.assertRaises(FileExistsError):
                relabel_session(path)
            with (path / 'camera.labels-v2.jsonl').open('a') as handle:
                handle.write('\n')
            with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
                build_session(path, 'camera.labels-v2.jsonl')

    def test_bad_schedule_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.fixture(path)
            camera = path / 'camera.jsonl'
            camera.write_text(camera.read_text().replace('"cue": "neutral"', '"cue": "index"'))
            with self.assertRaisesRegex(ValueError, 'schedule'):
                relabel_session(path)
            self.assertFalse((path / 'camera.labels-v2.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
