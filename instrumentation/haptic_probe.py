"""Bounded haptic pulses and comparisons using the established band transport."""
import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import mac_band_probe as probe
from extract_telemetry import DataXStream, checked_fields
from handwriting import field
from haptic_settings import COMPARISON_AMPLITUDES, DEFAULT_HAPTICS, validate_haptics


class Pulse:
    """One/two selected-intensity pulses or a four-intensity comparison; stop each pulse, and require its ack before repeating."""
    channel = 0x8001
    pulse_id = 0x20000001
    stop_id = 0x20000002

    def __init__(self, send, emit, clock, settings=None):
        self.send, self.emit, self.clock = send, emit, clock
        self.settings = validate_haptics(DEFAULT_HAPTICS if settings is None else settings)
        self.amplitudes = COMPARISON_AMPLITUDES if self.settings['count'] == 4 else (self.settings['amplitude'],) * self.settings['count']
        self.ready_at = self.stop_at = self.next_at = None
        self.deadline = clock() + 20
        self.index = 0
        self.sent = self.stopped = self.cancelled = False
        self.acks, self.requests = set(), {}
        self.frames = DataXStream()
        self.types = {}

    def request(self, command, body):
        request_id = self.pulse_id + self.index * 2 + (command == 'stop')
        self.requests[request_id] = (command, self.index + 1)
        self.send(self.channel, field(1, request_id) + field(17, body))
        self.emit('haptic_' + command + '_sent', pulse=self.index + 1, count=self.settings['count'], amplitude=self.amplitudes[self.index])

    def cancel(self):
        if not self.cancelled:
            self.cancelled = True
            if self.sent and not self.stopped:
                self.stop_at = self.clock()
            self.emit('haptic_cancelled')

    def tick(self, ready):
        now = self.clock()
        if not ready:
            return
        if self.ready_at is None and not self.cancelled:
            self.ready_at = now + 3
            self.emit('haptic_countdown', settings=self.settings, amplitudes=list(self.amplitudes),
                      send_at=datetime.fromtimestamp(datetime.now(UTC).timestamp() + 3,
                                                     UTC).isoformat())
        if not self.cancelled and not self.sent and now >= self.ready_at:
            if now + 2.5 >= self.deadline:
                self.cancel()
                self.emit('probe_error', message='Connection took too long to finish the pulse safely. Retry the test.')
                return
            self.request('pulse', field(1, field(1, self.settings['duration']) +
                                       field(3, self.amplitudes[self.index])))
            self.sent = True
            # Duration units are unverified. This is a host-side guard, not a unit conversion.
            self.stop_at = now + (.15 if self.settings['count'] > 1 else 1.5)
        if self.sent and not self.stopped and now >= self.stop_at:
            self.request('stop', field(3, b''))
            self.stopped = True
            self.next_at = now + self.settings['gap_ms'] / 1000
        if (not self.cancelled and self.stopped and self.index + 1 < self.settings['count']
                and now >= self.next_at and self.stop_id + 2 * self.index in self.acks
                and self.pulse_id + 2 * self.index in self.acks):
            self.index += 1
            self.sent = self.stopped = False
            self.ready_at = now

    def observe(self, plain):
        for channel, words, payload, _ in self.frames.feed(plain, None):
            if words:
                self.types[channel] = words[-1]
            if channel & 0x7fff != 1 or self.types.get(channel) != 0x02000315:
                continue
            fields = checked_fields(payload)
            request = fields.get((1, 0))
            if request not in self.requests:
                continue
            accepted = fields.get((2, 0)) == 1 and (18, 2) in fields
            if accepted:
                self.acks.add(request)
            command, pulse = self.requests[request]
            self.emit('haptic_reply', command=command, pulse=pulse, count=self.settings['count'],
                      accepted=accepted, request_id=request)


class HapticHandshake(probe.BandHandshake):
    settings = DEFAULT_HAPTICS

    def __init__(self, emit, **kwargs):
        def observe(event, **details):
            emit(event, **details)
            if event == 'authenticated_packet':
                self.pulse.observe(bytes.fromhex(details['plaintext']))
        super().__init__(observe, **kwargs)
        self.pulse = Pulse(self.handwriting_request, emit, self.clock, self.settings)

    def cancel_pending(self):
        self.pulse.cancel()

    def tick(self):
        super().tick()
        self.pulse.tick(self.startup_sent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('identifier')
    parser.add_argument('--identity-key', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    for name, default in DEFAULT_HAPTICS.items():
        parser.add_argument('--' + name.replace('_', '-'), type=int, default=default)
    cli = parser.parse_args()
    try:
        HapticHandshake.settings = validate_haptics({name: getattr(cli, name) for name in DEFAULT_HAPTICS})
    except ValueError as error:
        parser.error(str(error))
    args = SimpleNamespace(identifier=cli.identifier, identity_key=cli.identity_key,
                           seconds=20, query_device_info=False, end_link_setup=True,
                           stream_control=None, query_config=False, hand=None,
                           query_manifest=False, dial_settings=None, standby_after=None)
    probe.BandHandshake = HapticHandshake
    completed = set()
    cancelled = False
    issued = set()
    with cli.output.open('x') as capture:
        os.chmod(cli.output, 0o600)

        def emit(event, **details):
            nonlocal cancelled
            row = dict(event=event, timestamp=datetime.now(UTC).isoformat(), **details)
            capture.write(json.dumps(row) + '\n')
            capture.flush()
            if event == 'haptic_reply' and details['accepted']:
                completed.add((details['command'], details['pulse']))
            if event == 'haptic_pulse_sent':
                issued.add(details['pulse'])
            if event == 'haptic_cancelled':
                cancelled = True
            if event.startswith('haptic_') or event == 'probe_error':
                print(json.dumps(row), flush=True)
        try:
            with probe.band_connection():
                success = probe.run_probe(args, emit)
            expected = {('stop', n) for n in issued} if cancelled else {(command, n) for n in range(1, cli.count + 1) for command in ('pulse', 'stop')}
            if not success or not expected.issubset(completed):
                raise ValueError('Pulse and stop acknowledgements were not both received. Try reconnecting.')
        except (OSError, ValueError, RuntimeError) as error:
            emit('probe_error', message=str(error))
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
