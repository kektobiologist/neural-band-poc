"""Window-local EMG features and causal host-receipt-aligned motion features."""
import numpy as np


def emg_features(windows):
    x = np.asarray(windows, dtype=np.float64)
    if x.ndim != 3 or x.shape[1:] != (512, 8) or not np.isfinite(x).all():
        raise ValueError('Expected finite [windows, 512, 8] EMG')
    x = x - np.median(x, axis=1, keepdims=True)
    # Limit isolated ADC transients without learning statistics from validation.
    lo, hi = np.percentile(x, [1, 99], axis=1, keepdims=True)
    x = np.clip(x, lo, hi)
    rms = np.sqrt(np.mean(x*x, axis=1))
    log_rms = np.log1p(rms)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(512)[None, :, None], axis=1)) ** 2 / 512**2
    frequencies = np.fft.rfftfreq(512, 1/2048)
    bands = [np.log1p(spectrum[:, (frequencies >= lo) & (frequencies < hi)].mean(axis=1))
             for lo, hi in [(20, 60), (60, 150), (150, 300), (300, 500), (500, 900)]]
    return np.concatenate([log_rms, log_rms - log_rms.mean(axis=1, keepdims=True),
                           np.log1p(np.mean(np.abs(x), axis=1)),
                           np.log1p(np.mean(np.abs(np.diff(x, axis=1)), axis=1)), *bands], axis=1)


def causal_motion(rows, ends, max_age=.1):
    """32 sample-and-hold points over each trailing 250 ms; no future receipt used.

    Uses shared host monotonic time, not unverified cross-stream device epochs.
    Quaternion outer products avoid both component-order assumptions and q/-q flips.
    Reject missing/stale motion rather than silently imputing a sensor modality.
    """
    ends = np.asarray(ends)
    grids = ends[:, None] - np.arange(31, -1, -1)[None, :] / 128
    valid = np.ones(len(ends), dtype=bool)
    streams = []
    for event, size in [('gyro_sample', 3), ('orientation_sample', 4)]:
        selected = [r for r in rows if r['event'] == event]
        if not selected:
            return np.zeros((len(ends), 39)), np.zeros(len(ends), dtype=bool)
        times = np.asarray([r['host_monotonic_ns'] / 1e9 for r in selected])
        values = np.asarray([r['values'] for r in selected], dtype=np.float64)
        device = np.asarray([r['timestamp_us'] for r in selected], dtype=np.float64)
        sequence = np.asarray([r['sequence'] for r in selected], dtype=np.int64)
        if np.any(np.diff(times) < 0) or values.shape != (len(times), size):
            raise ValueError('Malformed or reordered motion stream')
        indices = np.searchsorted(times, grids, side='right') - 1
        safe = indices.clip(0, len(times)-1)
        valid &= np.all((indices >= 0) & (grids - times[safe] <= max_age), axis=1)
        bad = np.r_[0, (np.diff(sequence) != 1) | (np.diff(device) <= 0) | (np.diff(device) > max_age*1e6)]
        cumulative = np.cumsum(bad)
        valid &= cumulative[safe[:, -1]] == cumulative[safe[:, 0]]
        data = values[safe]
        valid &= np.isfinite(data).all(axis=(1, 2))
        if size == 4:
            norms = np.linalg.norm(data, axis=2, keepdims=True)
            valid &= np.all((norms[:, :, 0] > .9) & (norms[:, :, 0] < 1.1), axis=1)
            data = data / np.maximum(norms, 1e-9)
            outer = data[:, :, :, None] * data[:, :, None, :]
            a, b = np.triu_indices(4)
            data = outer[:, :, a, b]
        streams.extend([data.mean(axis=1), data.std(axis=1), data[:, -1] - data[:, 0]])
    features = np.concatenate(streams, axis=1)
    features[~valid] = 0
    return features, valid
