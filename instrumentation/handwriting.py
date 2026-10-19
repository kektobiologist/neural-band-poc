"""Bounded handwriting mode and greedy CTC decoding.

Protocol reference: beyondlevi/rokid-lumen, commit
4fe237668683cbe7e613e3c0121723a9f176102a, model_capture.rs / handwriting.rs.
See licenses/rokid-lumen-MIT.txt for the reference implementation's license.
"""
import math
import struct
from collections import deque

from extract_telemetry import DataXStream, checked_fields


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(n, value):
    if isinstance(value, int):
        return varint(n << 3) + varint(value)
    return varint(n << 3 | 2) + varint(len(value)) + value


def nested(fields, n):
    return checked_fields(fields[n, 2])


class TextDecoder:
    characters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' + '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'

    def __init__(self):
        self.text = ''
        self.previous = None
        self.sequence = None
        self.timestamp = None
        self.shift = False
        self.missing = 0

    def sample(self, sequence, timestamp, scores):
        if len(scores) != 100 or not all(math.isfinite(v) and v <= 1e-6 for v in scores) or abs(sum(math.exp(v) for v in scores) - 1) > 1e-4:
            raise ValueError('Unexpected handwriting distribution')
        if self.sequence is not None and (sequence != self.sequence + 1 or timestamp <= self.timestamp or timestamp - self.timestamp > 1_000_000):
            self.missing += max(0, sequence - self.sequence - 1)
            self.previous = None
        self.sequence, self.timestamp = sequence, timestamp
        best = max(range(100), key=scores.__getitem__)
        old, self.previous = self.previous, best
        if best == 99 or best == old:
            return best
        if best in (87, 98):
            pass
        elif best in (88, 96):
            self.text += ' '
        elif best == 94:
            self.text = self.text[:-1]
        elif best == 95:
            self.text += '\n'
        elif best == 97:
            self.shift = True
        elif best < len(self.characters):
            letter = self.characters[best]
            self.text += letter.upper() if self.shift else letter
            self.shift = False
        return best


class Handwriting:
    names = ('data-collection', 'data-collection-model')

    def __init__(self, emit, send, clock):
        self.emit, self.send, self.clock = emit, send, clock
        self.frames, self.types = DataXStream(), {}
        self.ids, self.original = {}, {}
        self.pending = None
        self.ops = deque()
        self.request_id = 0x10000000
        self.phase = 'idle'
        self.mutated = False
        self.problem = None
        self.restore_errors = []
        self.restored = False
        self.samples = 0
        self.decoder = TextDecoder()
        self.last_sample = None

    def start(self):
        self.phase = 'preparing'
        self.deadline = self.clock() + 60
        self.ops.append(('count', None, None))
        self.emit('handwriting_preparing')
        self.publish()

    def stop(self):
        if self.phase in ('idle', 'restoring', 'finished'):
            return
        self.phase = 'restoring'
        self.pending = None
        self.ops.clear()
        self.deadline = self.clock() + 35
        if self.mutated:
            for name in reversed(self.names):
                self.ops.append(('write', name, self.original[name]))
            for name in reversed(self.names):
                self.ops.append(('verify', name, self.original[name]))
        self.ops.append(('streams', None, 0))
        self.emit('handwriting_restoring', originals=self.original)
        self.publish()

    def fail(self, message):
        self.emit('handwriting_error', message=message, phase=self.phase)
        if self.phase == 'restoring':
            self.restore_errors.append(message)
            self.pending = None
        else:
            self.problem = message
            self.stop()

    def tick(self):
        if self.phase in ('idle', 'finished'):
            return
        now = self.clock()
        if now >= self.deadline:
            if self.phase == 'restoring':
                self.restore_errors.append('Restoration deadline expired')
                self.complete()
                return
            self.fail('Handwriting preparation timed out')
        if self.pending and now >= self.pending[4]:
            op, name, value, _, _ = self.pending
            self.pending = None
            if op != 'lookup':
                self.fail(f'Timed out: {op} {name}')
        if self.pending:
            return
        while self.ops:
            op, name, value = self.ops.popleft()
            if op == 'lookup' and len(self.ids) == 2:
                continue
            if op == 'snapshot' and len(self.ids) != 2:
                self.fail('Both handwriting settings were not identified by name')
                return
            if op == 'streams':
                body = field(4, b''.join(field(n, value) for n in (4, 22, 23)))
                channel = 0x8005
            else:
                channel = 0x8001
                if op == 'count':
                    body = field(1, field(1, 2))
                elif op == 'lookup':
                    body = field(2, field(1, 2) + field(2, value))
                else:
                    setting = self.ids[name]
                    writing = op == 'write'
                    body = field(1, setting) + field(2, int(writing))
                    if writing:
                        if len(self.original) != 2:
                            self.fail('Refusing to write without both original values')
                            return
                        self.mutated = True
                        body += field(7 if name == self.names[0] else 10, field(1, value))
                    body = field(3, body)
                body = field(14, body)
            self.request_id += 1
            self.pending = (op, name, value, self.request_id, now + (1.5 if op == 'lookup' else 5))
            self.emit('handwriting_request', operation=op, name=name, value=value, request_id=self.request_id)
            self.send(channel, field(1, self.request_id) + body)
            return
        if self.phase == 'restoring':
            self.complete()
        elif self.phase == 'preparing' and self.samples >= 5:
            self.phase = 'ready'
            self.deadline = float('inf')
            self.emit('handwriting_ready', samples=self.samples, settings=self.ids)
            self.publish()
        elif self.phase == 'ready' and now - self.last_sample > 3:
            self.fail('Handwriting samples stopped')

    def publish(self):
        self.emit('handwriting_state', phase=self.phase, text=self.decoder.text,
                  raw_text=self.decoder.text, samples=self.samples,
                  missing_samples=self.decoder.missing, restored=self.restored,
                  problem=self.problem, restore_errors=self.restore_errors)

    def complete(self):
        self.phase = 'finished'
        self.restored = not self.restore_errors
        self.emit('handwriting_finished', restored=self.restored, restore_errors=self.restore_errors,
                  problem=self.problem, samples=self.samples, text=self.decoder.text,
                  missing_samples=self.decoder.missing)
        self.publish()

    def receive(self, channel, payload):
        if not self.pending:
            return
        op, name, value, request_id, deadline = self.pending
        expected_channel = 5 if op == 'streams' else 1
        if channel & 0x7fff != expected_channel:
            return
        fields = checked_fields(payload)
        if fields.get((1, 0)) != request_id:
            return
        self.pending = None
        if fields.get((2, 0)) != 1 or self.clock() >= deadline:
            if op != 'lookup':
                self.fail(f'Rejected or late response: {op} {name}')
            return
        try:
            if op == 'streams':
                flags = nested(fields, 5)
                if any(flags.get((n, 0), 0) != value for n in (4, 22, 23)):
                    raise ValueError('Band did not confirm requested stream flags')
            elif op == 'count':
                count = nested(nested(fields, 14), 1)[1, 0]
                if not 2 <= count <= 512:
                    raise ValueError('Invalid settings count')
                candidates = [n for n in (28, 29, 27) if n <= count]
                candidates += [n for n in range(1, count + 1) if n not in candidates]
                self.ops.extend(('lookup', None, n) for n in candidates)
                self.ops.extend(('snapshot', n, None) for n in self.names)
                self.ops.append(('streams', None, 1))
                self.ops.extend(('write', n, v) for n, v in zip(self.names, (1, 5)))
                self.ops.extend(('verify', n, v) for n, v in zip(self.names, (1, 5)))
            elif op == 'lookup':
                info = nested(nested(fields, 14), 2)
                decoded = info.get((3, 2), b'').decode('utf8')
                if decoded in self.names and info.get((4, 0)) == value:
                    self.ids[decoded] = value
                    self.emit('handwriting_setting_found', name=decoded, setting_id=value)
            else:
                answer = nested(nested(fields, 14), 3)
                if answer.get((1, 0)) != self.ids[name] or answer.get((2, 0), 0) != int(op == 'write') or answer.get((3, 0), 0) != 0:
                    raise ValueError('Invalid setting response')
                if op != 'write':
                    actual = nested(answer, 8 if name == self.names[0] else 11).get((1, 0), 0)
                    if op == 'snapshot':
                        self.original[name] = actual
                        self.emit('handwriting_original', name=name, value=actual)
                    elif actual != value:
                        raise ValueError(f'{name} read back {actual}, expected {value}')
        except (KeyError, ValueError, UnicodeError) as error:
            self.fail(f'{op}: {error}')

    def feed(self, plain):
        for channel, words, payload, _ in self.frames.feed(plain, None):
            if words:
                self.types[channel] = words[-1]
            kind = self.types.get(channel)
            if kind == 0x02000315:
                self.receive(channel, payload)
            elif kind == 0x0200020c and self.phase in ('preparing', 'ready'):
                fields = checked_fields(payload)
                if fields.get((10, 0)) != 3:
                    continue
                try:
                    scores = struct.unpack('<100f', fields[3, 2])
                    before = self.decoder.text
                    best = self.decoder.sample(fields[1, 0], fields[2, 0], scores)
                    self.samples += 1
                    self.last_sample = self.clock()
                    self.emit('handwriting_sample', sequence=fields[1, 0], timestamp_us=fields[2, 0],
                              scores=scores, best_class=best)
                    if before != self.decoder.text:
                        self.emit('handwriting_text', text=self.decoder.text)
                    self.publish()
                except (KeyError, ValueError, struct.error) as error:
                    self.fail(str(error))
