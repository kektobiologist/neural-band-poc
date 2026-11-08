import unittest
import numpy as np
import torch
from learning.train import PinchTCN, center, metrics


class ModelTests(unittest.TestCase):
    def test_forward_backward_and_checkpoint(self):
        import io
        torch.set_num_threads(2)
        model = PinchTCN()
        data = torch.randn(3, 8, 512)
        logits = model(data)
        self.assertEqual(tuple(logits.shape), (3, 5))
        loss = torch.nn.functional.cross_entropy(logits, torch.tensor([0, 1, 4]))
        loss.backward()
        self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))
        buffer = io.BytesIO()
        torch.save(model.state_dict(), buffer)
        buffer.seek(0)
        copy = PinchTCN()
        copy.load_state_dict(torch.load(buffer, weights_only=True))
        torch.testing.assert_close(copy(data), logits)

    def test_dc_removal_and_missing_class_metrics(self):
        x = np.arange(512 * 8).reshape(1, 512, 8).astype(np.float32)
        np.testing.assert_allclose(center(x + 30000), center(x))
        report = metrics(np.array([0, 0, 1]), np.array([0, 1, 1]))
        self.assertEqual(report['support']['pinky'], 0)
        self.assertTrue(np.isfinite(report['macro_f1']))


if __name__ == '__main__':
    unittest.main()
