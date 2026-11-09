import base64
from concurrent.futures import Future
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from enroll_band import private_write, register_identity, verify
from enrollment import EnrollmentHandshake
from extract_telemetry import DataXStream, checked_fields
from mac_band_probe import field, typed_frame
from meta_pair import MetaPairClient, SessionExpired, post


def padded(frame):
    n = -len(frame) % 16
    return frame + bytes([0xc0 + n]) * n


class Executor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        future = Future()
        self.calls.append((fn, args, future))
        return future


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.events, self.saved = [], []
        self.executor = Executor()
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.probe = EnrollmentHandshake(lambda e, **d: self.events.append((e, d)), self.key,
                                        MetaPairClient({"access_token": "test-only"}),
                                        self.executor, lambda *a: self.saved.append(a), clock=lambda: self.now)
        # State-machine tests inspect plaintext requests; transport is tested below.
        self.probe.encrypt_frame = lambda frame: frame

    def reply(self, word, payload=b"", channel=2):
        self.probe.receive(padded(typed_frame(channel, [word], payload)))

    def request(self):
        data = bytes(self.probe.rpc_outgoing)
        self.probe.rpc_outgoing.clear()
        rows = list(DataXStream().feed(padded(data), {}))
        self.assertEqual(len(rows), 1)
        return rows[0][0:3]

    def nonce(self):
        self.reply(0x02003001, field(1, b"c" * 300) + field(2, b"serial") + field(5, b"s" * 300))
        self.assertEqual(self.request(), (0x8002, [0x02002000], b""))
        self.reply(0x02002001, field(1, b"n" * 16))

    def finish_request(self):
        self.nonce()
        self.executor.calls[-1][2].set_result((b"sig", ' { "pending": 1 }\n'))
        self.probe.tick()
        channel, words, payload = self.request()
        self.assertEqual(words, [0x02002002])
        self.assertEqual(checked_fields(payload)[2, 2], b' { "pending": 1 }\n')
        self.reply(0x02002003, field(1, b"device-sig") + field(2, b' {"device":true}\n'))
        self.assertEqual(self.executor.calls[-1][1], (b"device-sig", ' {"device":true}\n'))
        self.executor.calls[-1][2].set_result((b"final-sig", '{"final":true}', None))
        self.probe.tick()
        self.assertEqual(self.saved, [("finish_pending", None)])
        self.assertEqual(self.request()[1], [0x02002004])

    def test_ceremony_preserves_signed_bytes_and_requires_final_ack(self):
        self.finish_request()
        self.assertFalse(self.probe.complete)
        self.reply(0x03001000)
        self.assertFalse(self.probe.complete)
        self.reply(0x02002005)
        self.assertTrue(self.probe.complete)
        self.assertEqual(self.saved[-1], ("confirmed", None))
        self.assertFalse(self.probe.startup_sent)

    def test_new_public_key_sent_and_no_request_while_waiting(self):
        self.nonce()
        args = self.executor.calls[0][1]
        expected = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                       serialization.PublicFormat.UncompressedPoint)[1:]
        self.assertEqual(args[-1], expected)
        self.probe.tick()
        self.assertEqual(self.probe.rpc_outgoing, b"")
        self.assertEqual(self.saved, [])

    def test_rejects_out_of_order_duplicate_and_wrong_channel(self):
        self.reply(0x02002005, channel=3)
        self.assertEqual(self.probe.stage, "identity")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.reply(0x02002005)
        self.nonce()
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.reply(0x02002001, field(1, b"n" * 16))

    def test_invalid_nonce_and_nonempty_confirmation(self):
        self.reply(0x02003001, field(1, b"c" * 300) + field(2, b"serial") + field(5, b"s" * 300))
        with self.assertRaisesRegex(ValueError, "nonce"):
            self.reply(0x02002001, field(1, b"short"))
        self.setUp()
        self.finish_request()
        with self.assertRaisesRegex(ValueError, "not empty"):
            self.reply(0x02002005, field(1, 1))
        self.assertFalse(self.probe.complete)

    def test_wrong_account_expiry_timeout_and_cancel_do_not_complete(self):
        with self.assertRaisesRegex(ValueError, "different Meta account"):
            self.reply(0x03001042)
        self.nonce()
        self.executor.calls[-1][2].set_exception(SessionExpired("expired"))
        with self.assertRaises(SessionExpired):
            self.probe.tick()
        self.assertFalse(self.probe.complete)
        self.now = 100
        with self.assertRaisesRegex(ValueError, "timed out"):
            self.probe.tick()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.probe.cancel_pending()

    def test_checkpoint_failure_prevents_final_ownership_request(self):
        self.nonce()
        self.executor.calls[-1][2].set_result((b"sig", "pending"))
        self.probe.tick()
        self.request()
        self.reply(0x02002003, field(1, b"sig") + field(2, b"device"))
        self.executor.calls[-1][2].set_result((b"sig", "final", None))
        self.probe.checkpoint = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            self.probe.tick()
        self.assertEqual(self.probe.rpc_outgoing, b"")

    def test_logs_do_not_include_transport_material(self):
        self.probe.observe("session_material", shared_secret="SECRET")
        self.probe.observe("stream_bytes", hex="SECRET")
        self.probe.observe("peer_setup", certificate="SECRET")
        self.assertEqual(self.events, [])

    def test_encrypted_startup_only_sends_identity_query(self):
        from airshield import derive_keys, StreamDecryptor
        from analyze_capture import protobuf_fields
        # Restore actual encryption and exchange with an independent peer.
        del self.probe.encrypt_frame
        peer = ec.generate_private_key(ec.SECP256R1())
        public = peer.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)[1:]
        request = typed_frame(0x8001, [0x81000005, 0x02000001],
                              field(1, public) + field(2, b"c" * 16) + field(4, 27))
        enable = typed_frame(1, [0x02000002], field(1, public) + field(2, b"s" * 32) +
                             field(3, b"i" * 16) + field(4, 10) + field(5, 26))
        outgoing = b"".join(self.probe.feed(bytes([b])) for b in request + enable)
        size = (int.from_bytes(outgoing[:2], "big") & 0x7fff) + 4
        local = {n: v for n, w, v in protobuf_fields(outgoing[8:size])}
        secret = peer.exchange(ec.ECDH(), self.probe.private.public_key())
        decoder = StreamDecryptor(derive_keys(secret, b"c" * 16, local[2], 26),
                                   local[3], local[4], 26)
        packets = list(decoder.feed(outgoing[size:]))
        frames = list(DataXStream().feed(packets[0].plaintext, {}))
        self.assertEqual(len(packets), 1)
        self.assertEqual(frames[0][1], [0x81000024, 0x02003000])
        self.assertFalse(self.probe.startup_sent)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.probe.finish()


class PersistenceTests(unittest.TestCase):
    def test_private_candidate_never_overwrites_existing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owner.pem"
            private_write(path, b"first", exclusive=True)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                private_write(path, b"second", exclusive=True)
            self.assertEqual(path.read_bytes(), b"first")

    def test_mapping_preserves_other_band_and_failed_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            private_write(directory / "dashboard-identities.json", b'{"other":"/old.pem"}')
            register_identity("new", directory / "new.pem", directory)
            mapping = json.loads((directory / "dashboard-identities.json").read_text())
            self.assertEqual(mapping["other"], "/old.pem")
            with patch("enroll_band.run_probe", return_value=True):
                with self.assertRaisesRegex(ValueError, "did not confirm"):
                    verify("new", directory / "new.pem", lambda *a, **k: None)


class PairClientTests(unittest.TestCase):
    def test_http_fields_and_signed_receipt_preservation(self):
        requests = []
        value = ' { "signed": true }\n'
        def transport(route, fields):
            requests.append((route, fields))
            return {("pending_ownership_receipt" if route == "pair_request" else "final_ownership_receipt"): value,
                    "receipt_signature": base64.b64encode(b"sig").decode()}
        client = MetaPairClient({"access_token": "test"}, transport)
        self.assertEqual(client.pair_request(b"cert", "serial", b"secondary", b"n" * 16, b"p" * 64), (b"sig", value))
        additional = json.loads(requests[-1][1]["additional_data"])
        self.assertEqual(base64.b64decode(additional["app_pubkey"]), b"p" * 64)
        self.assertEqual(client.pair(b"sig", value), (b"sig", value, None))
        self.assertEqual(requests[-1][1]["device_pending_ownership_receipt"], value)

    def test_expired_session_is_sanitized(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, *a): return b'{"error":{"code":190,"message":"SECRET"}}'
        with patch("meta_pair.build_opener") as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaises(SessionExpired) as error:
                post("pair", {"user_access_token": "SECRET"})
            self.assertNotIn("SECRET", str(error.exception))


if __name__ == "__main__":
    unittest.main()
