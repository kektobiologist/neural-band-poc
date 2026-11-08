"""Cached feature-model inference with an optional EMG fallback."""
from pathlib import Path
import joblib
import numpy as np
from .features import emg_features


class FeaturePredictor:
    """Load trusted local checkpoints once; never consumes camera labels or cues."""
    def __init__(self, directory):
        directory = Path(directory)
        self.checkpoint = joblib.load(directory / 'model.joblib')
        self.fallback = None
        path = directory / 'fallback.pt'
        if path.exists():
            import torch
            from .train import PinchTCN
            torch.set_num_threads(2)
            saved = torch.load(path, weights_only=True)
            self.fallback = PinchTCN()
            self.fallback.load_state_dict(saved['state_dict'])
            self.fallback.eval()
            self.scale = np.asarray(saved['scale'])

    def predict(self, windows, motion, valid):
        modality = self.checkpoint['modality']
        valid = np.asarray(valid, dtype=bool)
        if motion.shape != (len(windows), 39) or valid.shape != (len(windows),):
            raise ValueError('Motion dimensions do not match EMG windows')
        emg = emg_features(windows)
        features = emg if modality == 'emg' else motion if modality == 'motion' else np.concatenate((emg, motion), axis=1)
        usable = np.ones(len(windows), dtype=bool) if modality == 'emg' else valid
        predicted = np.full(len(windows), -1, dtype=np.int64)
        if usable.any():
            predicted[usable] = self.checkpoint['pipeline'].predict(features[usable])
        fallback_used = ~usable & (self.fallback is not None)
        if fallback_used.any():
            import torch
            from .train import center
            x = torch.tensor((center(windows[fallback_used]) / self.scale).transpose(0,2,1), dtype=torch.float32)
            with torch.no_grad():
                predicted[fallback_used] = torch.cat([self.fallback(chunk).argmax(1) for chunk in x.split(128)]).numpy()
        return predicted, fallback_used


def predict_windows(model_directory, windows, motion, valid):
    """Batch wrapper. -1 denotes unavailable prediction; load only trusted models."""
    return FeaturePredictor(model_directory).predict(windows, motion, valid)
