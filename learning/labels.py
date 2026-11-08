"""Conservative geometry labels; these are pseudo-labels, not contact sensors."""
import math
import random

CLASSES = ('neutral', 'index', 'middle', 'ring', 'pinky')
TIPS = (8, 12, 16, 20)


def pinch_label(landmarks, close=.25, opened=.45):
    """Use palm-normalized 3D distances. Ambiguity is never neutral."""
    if len(landmarks) != 21 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in landmarks):
        return 'unknown', []
    scale = math.dist(landmarks[5], landmarks[17])
    if scale < 1e-6:
        return 'unknown', []
    distances = [math.dist(landmarks[4], landmarks[i]) / scale for i in TIPS]
    candidates = [i for i, d in enumerate(distances) if d < close]
    if len(candidates) == 1 and all(d > opened for i, d in enumerate(distances) if i != candidates[0]):
        return CLASSES[candidates[0] + 1], distances
    if all(d > opened for d in distances):
        return 'neutral', distances
    return 'unknown', distances


def trial_plan(repeats=6, seed=42, rest=3., hold=3.):
    """Randomize each block, keeping a rest before every pinch."""
    rng, trials = random.Random(seed), []
    for block in range(repeats):
        gestures = list(CLASSES[1:])
        rng.shuffle(gestures)
        for gesture in gestures:
            trials.extend([{'label': 'neutral', 'seconds': rest, 'block': block},
                           {'label': gesture, 'seconds': hold, 'block': block}])
    return trials


def cue_at(trials, elapsed):
    start = 0.
    for index, trial in enumerate(trials):
        end = start + trial['seconds']
        if start <= elapsed < end:
            return index, trial['label'], elapsed - start, end - elapsed
        start = end
    return -1, 'done', 0., 0.


LABEL_VERSION = 'image-world-v2'
LABEL_CONFIG = {
    'image_close': .35, 'image_open': .55, 'world_close': .65,
    'world_open': .45, 'min_palm_pixels': 20., 'stable_seconds': .15,
    'max_frame_gap_seconds': .15,
}


def visual_pinch_label(hand, width, height):
    """Image contact proxy with a loose depth guard; never proves physical contact.

    Image x/y must be converted to pixels before comparing distances on a
    non-square frame. Thresholds are pilot-calibrated, not population-validated.
    """
    image = hand.get('landmarks', [])
    world = hand.get('world_landmarks', [])
    details = {'image_distances': [], 'world_distances': []}
    if (not math.isfinite(width) or not math.isfinite(height) or min(width, height) <= 0
            or any(len(points) != 21 or any(len(p) != 3 or not all(math.isfinite(v) for v in p)
                                           for p in points) for points in (image, world))):
        return 'unknown', details
    xy = [[p[0] * width, p[1] * height] for p in image]
    image_scale = math.dist(xy[5], xy[17])
    world_scale = math.dist(world[5], world[17])
    if image_scale < LABEL_CONFIG['min_palm_pixels'] or world_scale < 1e-6:
        return 'unknown', details
    image_d = [math.dist(xy[4], xy[i]) / image_scale for i in TIPS]
    world_d = [math.dist(world[4], world[i]) / world_scale for i in TIPS]
    details.update(image_distances=image_d, world_distances=world_d)
    candidates = [i for i in range(4) if image_d[i] < LABEL_CONFIG['image_close']
                  and world_d[i] < LABEL_CONFIG['world_close']]
    if len(candidates) == 1:
        candidate = candidates[0]
        if all(image_d[i] > LABEL_CONFIG['image_open'] and world_d[i] > LABEL_CONFIG['world_open']
               for i in range(4) if i != candidate):
            return CLASSES[candidate + 1], details
    # A fingertip that is close in either view is ambiguous, not neutral.
    if all(d > LABEL_CONFIG['image_open'] for d in image_d) and all(
            d > LABEL_CONFIG['world_close'] for d in world_d):
        return 'neutral', details
    return 'unknown', details


class StableLabel:
    """Causal dwell filter; unknown, tracking loss or a frame gap resets it."""
    def __init__(self):
        self.label = 'unknown'
        self.since = self.last = None

    def update(self, label, at_ns):
        gap = self.last is not None and (at_ns <= self.last or
              (at_ns - self.last) / 1e9 > LABEL_CONFIG['max_frame_gap_seconds'])
        if gap or label != self.label or label == 'unknown':
            self.since = at_ns
        self.label, self.last = label, at_ns
        if self.since is None:
            self.since = at_ns
        return label if label != 'unknown' and (at_ns - self.since) / 1e9 >= LABEL_CONFIG['stable_seconds'] else 'unknown'


def label_frame(hands, hand_name, width, height, at_ns, cue, age, remaining, stability):
    matches = [h for h in hands if h['hand'] == hand_name and h['hand_score'] >= .8]
    visual, details = visual_pinch_label(matches[0], width, height) if len(matches) == 1 else (
        'unknown', {'image_distances': [], 'world_distances': []})
    stable = stability.update(visual, at_ns)
    accepted = stable if stable == cue and age >= .65 and remaining >= .35 else 'unknown'
    return {'visual_label': visual, 'stable_label': stable, 'label': accepted,
            'label_version': LABEL_VERSION, **details}
