import unittest

import numpy as np

from learning.meta_transfer import context_window, preprocess


def batches(count=130):
    return [{'sequence': i, 'timestamp_us': i*7812.5,
             'host_monotonic_ns': int(i*7812500),
             'samples': np.full((16,8),i).tolist()} for i in range(count)]


class TransferContextTests(unittest.TestCase):
    def test_context_excludes_future_and_keeps_endpoint(self):
        rows = batches()
        x, reason = context_window(rows,128)
        self.assertIsNone(reason)
        self.assertEqual(x.shape,(2048,8))
        self.assertEqual(x[-1,0],127)
        rows[128]['samples'] = [[float('nan')]*8]*16
        np.testing.assert_array_equal(x,context_window(rows,128)[0])

    def test_gap_before_label_window_is_rejected(self):
        rows = batches()
        rows[10]['sequence'] += 1
        self.assertEqual(context_window(rows,128)[1],'sensor_gap')

    def test_context_warmup_and_timing_reset(self):
        self.assertEqual(context_window(batches(),127)[1],'warmup')
        rows = batches()
        rows[10]['timestamp_us'] = 0
        self.assertEqual(context_window(rows,128)[1],'device_timing')

    def test_preprocessing_rate_and_dc_rejection(self):
        x = np.full((2,2048,8),12345,dtype=np.float32)
        transformed = preprocess(x)
        self.assertEqual(transformed.shape,(2,2000,8))
        np.testing.assert_array_equal(transformed,0)


if __name__ == '__main__':
    unittest.main()
