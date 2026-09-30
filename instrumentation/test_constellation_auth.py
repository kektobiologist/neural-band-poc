import unittest

from constellation_auth import ConstellationDiagnostic
from mac_band_probe import field, typed_frame


def padded(frame):
    count = -len(frame) % 16
    return frame + bytes([0xc0 + count]) * count


def offer(channel=0x9d03):
    return typed_frame(channel, [0x8100004f, 0x02000001],
                       field(1, b't' * 8) + field(2, b's' * 64) + field(3, 8))


class ConstellationTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.diag = ConstellationDiagnostic(lambda e, **v: self.events.append((e, v)), True)

    def test_split_offer_requests_once_and_empty_completion_is_not_trust(self):
        wire = offer()
        self.assertEqual(list(self.diag.feed(wire[:16])), [])
        self.assertEqual(list(self.diag.feed(padded(wire[16:]))), [(0x1d03, 0x03000003)])
        done = typed_frame(0x9d03, [0x02000004])
        self.assertEqual(list(self.diag.feed(padded(done + offer()))), [])
        self.diag.finish()
        result = [v for e, v in self.events if e == 'constellation_manifest_complete'][0]
        self.assertTrue(result['empty'])
        self.assertFalse(result['manifest_verified'])
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(sum(e == 'constellation_manifest_requested' for e, _ in self.events), 1)

    def test_passive_diagnostic_does_not_send(self):
        self.diag.request_manifest = False
        self.assertEqual(list(self.diag.feed(padded(offer()))), [])
        self.assertFalse(self.diag.requested)

    def test_chunks_are_bounded_and_wrong_channel_is_ignored(self):
        list(self.diag.feed(padded(offer())))
        for ch, data in ((0x9001, b'ignored'), (0x9d03, b'abc')):
            list(self.diag.feed(padded(typed_frame(ch, [0x02000002], data))))
        self.assertEqual(self.diag.manifest, b'abc')
        self.diag.max_manifest_bytes = 3
        with self.assertRaisesRegex(ValueError, 'size limit'):
            list(self.diag.feed(padded(typed_frame(0x9d03, [0x02000004], b'd'))))
        self.assertFalse(self.diag.complete)

    def test_incomplete_transfer_is_reported(self):
        list(self.diag.feed(padded(offer())))
        self.diag.finish()
        self.assertEqual(self.events[-1], ('constellation_manifest_incomplete', {'bytes': 0}))

    def test_bad_signature_shape_does_not_request(self):
        bad = typed_frame(0x9d03, [0x8100004f, 0x02000001], field(1, b't' * 8))
        with self.assertRaisesRegex(ValueError, 'signature shape'):
            list(self.diag.feed(padded(bad)))
        self.assertFalse(self.diag.requested)

    def test_second_channel_is_rejected(self):
        list(self.diag.feed(padded(offer())))
        with self.assertRaisesRegex(ValueError, 'multiple Constellation channels'):
            list(self.diag.feed(padded(offer(0x9002))))

    def test_manifest_capability_preserves_unknown_enum_value(self):
        payload = field(1, b't' * 8) + field(2, b's' * 64) + field(3, 8)
        for value in (0, 1, 2, 99):
            with self.subTest(value=value):
                self.setUp()
                frame = typed_frame(0x9d03, [0x8100004f, 0x02000001],
                                    payload + field(7, field(1, value)))
                list(self.diag.feed(padded(frame)))
                self.assertEqual(self.events[0][1]['can_send_manifest_raw'], value)
                self.assertFalse(self.events[0][1]['identity_verified'])

    def test_absent_manifest_capability_is_unknown(self):
        list(self.diag.feed(padded(offer())))
        self.assertIsNone(self.events[0][1]['can_send_manifest_raw'])
