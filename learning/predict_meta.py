"""Frozen Meta transfer inference using exactly the offline preprocessing."""
import numpy as np
import torch

from .labels import CLASSES
from .meta_transfer import AdaptedGesture, preprocess, upstream_classes


class MetaPredictor:
    window_batches = 128
    requires_motion = False
    mode = 'Meta adapted EMG'

    def __init__(self, checkpoint, source):
        torch.set_num_threads(2)
        saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
        if (saved['architecture'] != 'MetaGNI-adapter8to16-pinch5'
                or saved['context_samples'] != 2048
                or saved['classes'] != list(CLASSES)
                or saved['preprocessing'] != 'context_median_hp40_resample125over128_training_std_times32'):
            raise ValueError('Unsupported transfer checkpoint')
        architecture, _ = upstream_classes(source)
        self.model = AdaptedGesture(architecture)
        self.model.load_state_dict(saved['state_dict'], strict=True)
        self.model.eval()
        self.scale = np.asarray(saved['scale'], dtype=np.float32)
        if self.scale.shape != (8,) or not np.isfinite(self.scale).all() or (self.scale <= 0).any():
            raise ValueError('Invalid training scale')

    def predict(self, windows, motion=None, valid=None):
        if windows.shape[1:] != (2048, 8) or not np.isfinite(windows).all():
            raise ValueError('Expected finite one-second eight-channel EMG')
        x = (preprocess(windows) / self.scale * 32).transpose(0, 2, 1).copy()
        with torch.inference_mode():
            predicted = self.model(torch.from_numpy(x)).argmax(1).numpy()
        return predicted, np.zeros(len(windows), dtype=bool)
