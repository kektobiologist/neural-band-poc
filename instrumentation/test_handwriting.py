import unittest
from handwriting import Handwriting, TextDecoder, field


class HandwritingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sent, self.events = [], []
        self.hw = Handwriting(lambda e, **d: self.events.append((e, d)),
                              lambda c, p: self.sent.append((c, p)), lambda: self.now)
        self.values = {'data-collection': 0, 'data-collection-model': 4}

    def answer(self):
        self.hw.tick()
        op, name, value, rid, deadline = self.hw.pending
        if op == 'count':
            body = field(14, field(1, field(1, 32)))
        elif op == 'lookup':
            found = {28: 'data-collection', 29: 'data-collection-model'}.get(value, 'unrelated')
            body = field(14, field(2, field(3, found.encode()) + field(4, value)))
        elif op == 'streams':
            body = field(5, b''.join(field(n, value) for n in (4, 22, 23)))
        else:
            if op == 'write':
                self.values[name] = value
            answer = field(1, self.hw.ids[name]) + (field(2, 1) if op == 'write' else b'')
            if op != 'write':
                answer += field(8 if name == 'data-collection' else 11, (field(1, self.values[name]) if self.values[name] else b''))
            body = field(14, field(3, answer))
        self.hw.receive(5 if op == 'streams' else 1, field(1, rid) + field(2, 1) + body)

    def prepare(self):
        self.hw.start()
        while self.hw.ops or self.hw.pending:
            self.answer()

    def test_activation_and_exact_restore(self):
        self.prepare()
        self.assertEqual(self.values, {'data-collection': 1, 'data-collection-model': 5})
        self.assertEqual(self.hw.original, {'data-collection': 0, 'data-collection-model': 4})
        self.hw.stop()
        while self.hw.ops or self.hw.pending:
            self.answer()
        self.hw.tick()
        self.assertTrue(self.hw.restored)
        self.assertEqual(self.values, self.hw.original)

    def test_stop_after_first_write_restores_both(self):
        self.hw.start()
        while not self.hw.mutated:
            self.answer()
        self.hw.stop()
        while self.hw.ops or self.hw.pending:
            self.answer()
        self.hw.tick()
        self.assertTrue(self.hw.restored)
        self.assertEqual(self.values, self.hw.original)

    def test_missing_name_never_writes(self):
        self.hw.start()
        self.hw.ops.clear()
        self.hw.ops.append(('snapshot', 'data-collection', None))
        self.hw.tick()
        self.assertFalse(self.hw.mutated)
        self.assertEqual(self.hw.phase, 'restoring')
        self.assertFalse(self.sent)

    def test_restore_readback_mismatch_is_not_success(self):
        self.prepare()
        self.hw.stop()
        self.answer()
        self.answer()
        self.values['data-collection-model'] = 5
        self.answer()
        while self.hw.ops or self.hw.pending:
            self.answer()
        self.hw.tick()
        self.assertFalse(self.hw.restored)

    def test_long_blanks_do_not_insert_spaces_but_explicit_space_does(self):
        decoder = TextDecoder()
        classes = [0] + [99]*20 + [1, 99, 96, 2, 99, 88, 3]
        for seq, cls in enumerate(classes):
            scores = [-1000.] * 100
            scores[cls] = 0.
            decoder.sample(seq, seq * 156250, scores)
        self.assertEqual(decoder.text, 'ab c d')

    def test_missing_samples_do_not_create_word_boundary(self):
        d = TextDecoder()
        def sample(seq, cls):
            scores = [-1000.] * 100
            scores[cls] = 0.
            d.sample(seq, seq * 156250, scores)
        sample(0, 0)
        sample(1, 99)
        sample(10, 1)
        self.assertEqual(d.text, 'ab')
        self.assertEqual(d.missing, 8)

    def test_ctc_repeats_blanks_edits_and_gap(self):
        d = TextDecoder()
        for seq, cls in enumerate([0, 0, 99, 0, 96, 1, 94, 97, 2]):
            scores = [-1000.] * 100
            scores[cls] = 0.
            d.sample(seq, seq * 156250, scores)
        self.assertEqual(d.text, 'aa C')
        d.sample(12, 12 * 156250, scores)
        self.assertEqual(d.text, 'aa Cc')
        self.assertEqual(d.missing, 3)
        with self.assertRaises(ValueError):
            d.sample(13, 13 * 156250, [0.] * 100)

if __name__ == '__main__':
    unittest.main()
