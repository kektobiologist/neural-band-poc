import unittest
import numpy as np
from learning.features import emg_features, causal_motion


def motion_rows():
    rows = []
    for i in range(96):
        for event, values in [('gyro_sample', [i, 2*i, -i]), ('orientation_sample', [1., 0., 0., 0.])]:
            rows.append({'event': event, 'host_monotonic_ns': int((10+i/128)*1e9),
                         'timestamp_us': i*7812.5, 'sequence': i, 'values': values})
    return rows


class FeatureTests(unittest.TestCase):
    def test_emg_offset_invariance_and_zero_signal(self):
        x = np.random.default_rng(3).normal(size=(4,512,8)) * 50
        features = emg_features(x)
        self.assertEqual(features.shape, (4,72))
        np.testing.assert_allclose(features, emg_features(x+32768), atol=1e-10)
        self.assertTrue(np.isfinite(emg_features(np.zeros((2,512,8)))).all())
        x[0,0,0] = np.nan
        with self.assertRaises(ValueError):
            emg_features(x)

    def test_single_spike_is_limited(self):
        x = np.zeros((1,512,8)); x[:,100,:] = 20000
        np.testing.assert_allclose(emg_features(x), 0)

    def test_motion_causal_and_quaternion_sign_invariant(self):
        rows = motion_rows()
        features, valid = causal_motion(rows, [10.5])
        self.assertTrue(valid[0]);self.assertEqual(features.shape,(1,39))
        for row in rows:
            if row['host_monotonic_ns'] > 10.5e9:
                row['values'] = [999999.] * len(row['values'])
            elif row['event'] == 'orientation_sample' and row['sequence'] % 2:
                row['values'] = [-v for v in row['values']]
        updated, mask = causal_motion(rows,[10.5])
        np.testing.assert_allclose(features,updated)
        np.testing.assert_array_equal(mask,valid)

    def test_missing_stale_and_sequence_gap_rejected(self):
        _, valid = causal_motion([], [10.5]);self.assertFalse(valid[0])
        rows=motion_rows()
        _, valid=causal_motion(rows,[11.5]);self.assertFalse(valid[0])
        rows=[r for r in rows if not(r['event']=='gyro_sample' and r['sequence']==50)]
        _, valid=causal_motion(rows,[10.5]);self.assertFalse(valid[0])

    def test_quaternion_invalid_and_receipt_reorder_rejected(self):
        rows=motion_rows()
        for r in rows:
            if r['event']=='orientation_sample' and r['sequence']==50:r['values']=[0.]*4
        _, valid=causal_motion(rows,[10.5]);self.assertFalse(valid[0])
        rows=motion_rows(); rows[0]['host_monotonic_ns']=11e9
        with self.assertRaises(ValueError):causal_motion(rows,[10.5])


if __name__ == '__main__':
    unittest.main()


class CheckpointTests(unittest.TestCase):
    def test_motion_failure_uses_emg_fallback_and_saved_models_reload(self):
        from pathlib import Path
        import tempfile
        import joblib
        import torch
        from sklearn.dummy import DummyClassifier
        from learning.train import PinchTCN
        from learning.predict_features import predict_windows
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            dummy = DummyClassifier(strategy='constant', constant=4).fit(np.zeros((5,111)), np.arange(5))
            joblib.dump({'pipeline': dummy, 'modality': 'fused'}, path/'model.joblib')
            x = np.zeros((2,512,8), dtype=np.float32)
            motion = np.zeros((2,39));valid=np.array([True,False])
            predicted, fallback = predict_windows(path,x,motion,valid)
            np.testing.assert_array_equal(predicted,[4,-1])
            self.assertFalse(fallback.any())
            model=PinchTCN()
            for parameter in model.parameters():parameter.data.zero_()
            torch.save({'state_dict':model.state_dict(),'scale':[1.]*8},path/'fallback.pt')
            predicted,fallback=predict_windows(path,x,motion,valid)
            np.testing.assert_array_equal(predicted,[4,0])
            np.testing.assert_array_equal(fallback,[False,True])
