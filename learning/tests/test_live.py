import unittest
import numpy as np
from learning.live import LiveDecoder, camera_reference


class Predictor:
    def predict(self, x, motion, valid):
        assert x.shape == (1,512,8)
        return np.array([1]), np.array([True])


class LiveTests(unittest.TestCase):
    def test_meta_context_requires_full_second_without_motion(self):
        class MetaStub:
            window_batches = 128
            requires_motion = False
            mode = 'Meta adapted EMG'
            def predict(self, x, motion, valid):
                assert x.shape == (1,2048,8)
                assert motion is None and valid is None
                return np.array([4]), np.array([False])
        decoder = LiveDecoder(MetaStub())
        decoder.feed({'event':'emg_config_received','sample_rate':2048,'channels':8})
        for i in range(128):
            if i == 127:
                self.assertEqual(decoder.predict(11_000_000_000),(None,'warming up'))
            decoder.feed({'event':'emg_batch','sequence':i,'timestamp_us':round(i*7812.5),
                          'host_monotonic_ns':10_000_000_000+i*7_812_500,'samples':[[32768]*8]*16})
        result, state = decoder.predict(11_000_000_000)
        self.assertEqual(result['label'],'pinky')
        self.assertEqual(result['mode'],'Meta adapted EMG')
        decoder.emg[10]['missing_before'] = 1
        self.assertEqual(decoder.predict(11_000_000_000),(None,'sensor gap'))

    def decoder(self):
        decoder=LiveDecoder(Predictor())
        decoder.feed({'event':'emg_config_received','sample_rate':2048,'channels':8})
        for i in range(32):
            decoder.feed({'event':'emg_batch','sequence':i,'timestamp_us':round(i*7812.5),
                          'host_monotonic_ns':10_000_000_000+i*7_812_500,'samples':[[32768]*8]*16,'missing_before':0})
        return decoder

    def test_fresh_prediction_not_recounted_and_stale_clears(self):
        decoder=self.decoder()
        prediction,state=decoder.predict(10_250_000_000)
        self.assertEqual(prediction['label'],'index')
        self.assertEqual(prediction['mode'],'EMG fallback')
        self.assertEqual(decoder.predict(10_260_000_000),(None,'unchanged'))
        self.assertEqual(decoder.predict(11_000_000_000),(None,'sensor stream stale'))

    def test_gaps_and_disconnects_do_not_predict(self):
        decoder=self.decoder();decoder.emg[15]['missing_before']=1
        self.assertEqual(decoder.predict(10_250_000_000),(None,'sensor gap'))
        decoder.feed({'event':'disconnected'})
        self.assertIsNone(decoder.predict(10_250_000_000)[0])

    def test_reference_requires_full_stable_interval(self):
        points=[(i*50_000_000,'index') for i in range(9)]
        self.assertEqual(camera_reference(points,300_000_000),'index')
        points[3]=(150_000_000,'unknown')
        self.assertEqual(camera_reference(points,300_000_000),'unknown')
        self.assertEqual(camera_reference(points,500_000_000),'unknown')
        self.assertEqual(camera_reference([(0,'index'),(300_000_000,'index')],300_000_000),'unknown')
