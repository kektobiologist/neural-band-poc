"""Conservative test limits, not a claim about the band's supported range or units."""
DEFAULT_HAPTICS = {'amplitude': 128, 'duration': 150, 'count': 1, 'gap_ms': 100}
LIMITS = {'amplitude': (1, 1023), 'duration': (50, 1000), 'count': (1, 4), 'gap_ms': (50, 1000)}


def validate_haptics(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULT_HAPTICS):
        raise ValueError('Provide amplitude, duration, count, and gap_ms')
    for key, (low, high) in LIMITS.items():
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}')
    if settings['count'] not in (1, 2, 4):
        raise ValueError('Choose one pulse, two pulses, or the four-intensity comparison')
    return dict(settings)

# count=4 is the comparison mode; count=1/2 repeats the selected amplitude.
COMPARISON_AMPLITUDES = (128, 255, 256, 384)
