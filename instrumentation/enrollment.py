"""One-attempt enrollment state machine over the existing encrypted transport.

Protocol adapted from callbacked/kinesis (MIT); see licenses/kinesis-MIT.txt.
"""
import time
from cryptography.hazmat.primitives import serialization
from extract_telemetry import DataXStream, checked_fields
from mac_band_probe import BandHandshake, typed_frame, field

ERRORS = {
    0x1040: "Ownership receipt rejected",
    0x1041: "Ownership nonce rejected; restart enrollment in pairing mode",
    0x1042: "Band belongs to a different Meta account; retry --login with its owner account",
    0x1043: "App identity rejected",
    0x1044: "Ownership signature rejected",
    0x1045: "Receipt timing rejected; check the Mac clock and retry",
    0xc001: "Identity service unavailable; put the band in pairing mode",
}


class EnrollmentHandshake(BandHandshake):
    def __init__(self, emit, key, client, executor, checkpoint, clock=time.monotonic):
        self.events = emit
        self.enrollment_frames = DataXStream()
        self.stage, self.complete = "identity", False
        self.key, self.client, self.executor = key, client, executor
        self.checkpoint = checkpoint
        self.future = None
        self.deadline = clock() + 45
        self.band_public = None
        super().__init__(self.observe, clock=clock)

    def observe(self, event, **details):
        # Enrollment must never emit transport secrets, certificates or receipts.
        if event == "authenticated_packet":
            self.receive(bytes.fromhex(details["plaintext"]))
        elif event not in ("session_material", "stream_bytes", "unauthenticated_record", "peer_setup"):
            self.events(event, **details)

    def start_services(self):
        # Base transport sends IdentityRead. Enrollment owns service 0x24 until
        # completion; no input services or owner proof on this connection.
        return b""

    def advance(self, stage):
        self.stage = stage
        self.deadline = self.clock() + 40
        self.events("enrollment_stage", stage=stage)

    def send(self, word, payload=b""):
        self.rpc_outgoing.extend(self.encrypt_frame(typed_frame(0x8002, [word], payload)))

    def receive(self, plain):
        for channel, words, payload, _ in self.enrollment_frames.feed(plain, {}):
            if channel & 0x7fff != 2:
                continue
            if words and words[-1] >> 24 == 3:
                code = words[-1] & 0xffff
                # A result acknowledgement is never an ownership completion.
                if code != 0x1000:
                    raise ValueError(ERRORS.get(code, f"Enrollment rejected: 0x{code:04x}"))
                continue
            if words and words[0] & 0x80000000:
                if words[0] != 0x81000024:
                    continue
                words = words[1:]
            expected = {"identity": 0x02003001, "nonce": 0x02002001,
                        "device_receipt": 0x02002003, "confirmation": 0x02002005}
            if not words or words != [expected.get(self.stage)]:
                raise ValueError(f"Unexpected identity response during {self.stage}")
            values = checked_fields(payload)
            if self.stage == "identity":
                cert, serial, secondary = (values.get((n, 2), b"") for n in (1, 2, 5))
                if len(cert) <= 256 or len(secondary) <= 256 or not serial or len(serial) > 128:
                    raise ValueError("Band did not return a usable enrollment identity")
                try:
                    serial = serial.decode("ascii")
                except UnicodeError:
                    raise ValueError("Band serial is not ASCII") from None
                self.identity = cert, serial, secondary
                self.advance("nonce")
                self.send(0x02002000)
            elif self.stage == "nonce":
                nonce = values.get((1, 2), b"")
                if len(nonce) != 16:
                    raise ValueError("Band returned an invalid ownership nonce")
                public = self.key.public_key().public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)[1:]
                self.advance("pending_receipt")
                self.future = self.executor.submit(self.client.pair_request, *self.identity, nonce, public)
            elif self.stage == "device_receipt":
                signature, value = values.get((1, 2), b""), values.get((2, 2), b"")
                if not signature or not value:
                    raise ValueError("Band returned an empty pending receipt")
                try:
                    value = value.decode("utf-8")
                except UnicodeError:
                    raise ValueError("Band returned an invalid receipt encoding") from None
                self.advance("final_receipt")
                self.future = self.executor.submit(self.client.pair, signature, value)
            elif self.stage == "confirmation":
                if payload:
                    raise ValueError("Ownership confirmation was not empty")
                self.checkpoint("confirmed", self.band_public)
                self.advance("confirmed")
                self.complete = True

    def tick(self):
        if self.complete:
            return
        if self.clock() >= self.deadline:
            raise ValueError(f"Enrollment timed out during {self.stage}; keep the band in pairing mode")
        if self.future is None or not self.future.done():
            return
        result = self.future.result()
        self.future = None
        if self.stage == "pending_receipt":
            signature, value = result
            self.advance("device_receipt")
            self.send(0x02002002, field(1, signature) + field(2, value.encode("utf-8")))
        elif self.stage == "final_receipt":
            signature, value, self.band_public = result
            # Persist a recovery marker BEFORE the irreversible finish request.
            self.checkpoint("finish_pending", self.band_public)
            self.advance("confirmation")
            self.send(0x02002004, field(1, signature) + field(2, value.encode("utf-8")))
        else:
            raise ValueError("Unexpected HTTP completion during enrollment")

    def cancel_pending(self):
        if self.future:
            self.future.cancel()
        raise ValueError("Enrollment cancelled; candidate PEM retained for recovery")

    def finish(self):
        super().finish()
        self.enrollment_frames.finish()
        if not self.complete:
            raise ValueError(f"Enrollment incomplete during {self.stage}; candidate PEM retained")
