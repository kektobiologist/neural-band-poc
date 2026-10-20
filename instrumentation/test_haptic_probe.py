import unittest

from handwriting import field
from haptic_probe import Pulse
from haptic_settings import DEFAULT_HAPTICS, validate_haptics
from mac_band_probe import typed_frame


class PulseTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sent = []
        self.events = []
        self.pulse = self.make_pulse()

    def make_pulse(self, **settings):
        return Pulse(lambda *a: self.sent.append(a),
                     lambda event, **kw: self.events.append((event, kw)), lambda: self.now,
                     dict(DEFAULT_HAPTICS, **settings))

    def advance(self, now):
        self.now = now
        self.pulse.tick(True)

    def reply(self, request, channel=1, status=1, nested=True):
        frame = typed_frame(channel, [0x02000315], field(1, request) + field(2, status) +
                            (field(18, b'') if nested else b''))
        padding = 16 - len(frame) % 16
        self.pulse.observe(frame + bytes([0xc0 + padding]) * padding)

    def test_single_pulse_then_stop_and_no_repeats(self):
        self.pulse.tick(False)
        self.assertEqual(self.events, [])
        self.advance(0)
        self.advance(2.99)
        self.assertEqual(self.sent, [])
        self.advance(3)
        self.assertEqual(self.sent[0][1], field(1, Pulse.pulse_id) +
                         field(17, field(1, field(1, 150) + field(3, 128))))
        self.advance(4.5)
        self.assertEqual(self.sent[-1][1], field(1, Pulse.stop_id) + field(17, field(3, b'')))
        self.advance(10)
        self.assertEqual(len(self.sent), 2)

    def test_double_requires_both_acks_and_gap(self):
        self.pulse = self.make_pulse(count=2, amplitude=200, duration=500, gap_ms=100)
        self.advance(0)
        self.advance(3)
        self.assertIn(field(1, 500) + field(3, 200), self.sent[0][1])
        self.advance(3.151)
        self.reply(Pulse.stop_id)
        self.advance(3.26)
        self.assertEqual(len(self.sent), 2)
        self.reply(Pulse.pulse_id)
        self.advance(3.27)
        self.advance(3.28)
        self.assertEqual(len(self.sent), 3)
        self.advance(3.431)
        self.assertEqual(len(self.sent), 4)
        self.advance(15)
        self.assertEqual(len(self.sent), 4)

    def test_quick_double_finishes_in_under_half_a_second(self):
        self.pulse = self.make_pulse(count=2)
        self.advance(0)
        self.advance(3)
        self.advance(3.149)
        self.assertEqual(len(self.sent), 1)
        self.advance(3.151)
        self.reply(Pulse.pulse_id)
        self.reply(Pulse.stop_id)
        self.advance(3.249)
        self.assertEqual(len(self.sent), 2)
        self.advance(3.252)
        self.advance(3.254)
        self.assertEqual(len(self.sent), 3)
        self.advance(3.405)
        self.assertEqual(len(self.sent), 4)

    def test_cancel_stops_active_pulse_and_prevents_second(self):
        self.pulse = self.make_pulse(count=2)
        self.advance(0)
        self.advance(3)
        self.pulse.cancel()
        self.advance(3.01)
        self.assertEqual(len(self.sent), 2)
        self.reply(Pulse.pulse_id)
        self.reply(Pulse.stop_id)
        self.advance(10)
        self.assertEqual(len(self.sent), 2)

    def test_cancel_during_countdown_sends_nothing(self):
        self.advance(0)
        self.pulse.cancel()
        self.advance(4)
        self.assertEqual(self.sent, [])

    def test_late_connection_never_starts_pulse_without_stop_time(self):
        self.advance(16)
        self.advance(19)
        self.assertEqual(self.sent, [])

    def test_reply_requires_correct_channel_id_type_status_and_response(self):
        self.advance(0)
        self.advance(3)
        self.reply(Pulse.pulse_id, channel=2)
        self.reply(Pulse.pulse_id + 100)
        self.reply(Pulse.pulse_id, status=2)
        self.reply(Pulse.pulse_id, nested=False)
        self.assertEqual(self.pulse.acks, set())
        self.reply(Pulse.pulse_id)
        self.assertEqual(self.pulse.acks, {Pulse.pulse_id})

    def test_four_pulse_comparison_order_duration_and_completion(self):
        from extract_telemetry import checked_fields
        from handwriting import nested
        self.pulse = self.make_pulse(count=4, amplitude=128, duration=300, gap_ms=100)
        self.advance(0)
        for index, amplitude in enumerate((128, 255, 256, 384)):
            start = 3 + index * .3
            if index:
                self.advance(start - .002)
            self.advance(start)
            frame = checked_fields(self.sent[-1][1])
            vibrate = nested(nested(frame, 17), 1)
            self.assertEqual(vibrate[3, 0], amplitude)
            self.assertEqual(vibrate[1, 0], 300)
            self.advance(start + .151)
            self.reply(Pulse.pulse_id + index * 2)
            self.reply(Pulse.stop_id + index * 2)
        self.assertEqual(len(self.sent), 8)
        self.assertEqual(len(self.pulse.acks), 8)
        self.advance(15)
        self.assertEqual(len(self.sent), 8)

    def test_higher_amplitudes_are_encoded_without_truncation(self):
        from extract_telemetry import checked_fields
        from handwriting import nested
        for amplitude in (255, 256, 511, 767, 1023):
            with self.subTest(amplitude=amplitude):
                self.now = 0
                self.sent.clear()
                self.pulse = self.make_pulse(amplitude=amplitude)
                self.advance(0)
                self.advance(3)
                request = checked_fields(self.sent[0][1])
                vibrate = nested(nested(request, 17), 1)
                self.assertEqual(vibrate[3, 0], amplitude)

    def test_validation_rejects_wrong_types_extra_keys_and_bounds(self):
        for key, value in [('amplitude', 1024), ('amplitude', True), ('duration', 0),
                           ('duration', 1001), ('count', 3), ('count', 1.0), ('gap_ms', -1),
                           ('other', 0)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_haptics(dict(DEFAULT_HAPTICS, **{key: value}))
        self.assertEqual(validate_haptics(DEFAULT_HAPTICS), DEFAULT_HAPTICS)


if __name__ == '__main__':
    unittest.main()
