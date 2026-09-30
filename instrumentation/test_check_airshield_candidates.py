import unittest

from airshield import DirectionalKeys
from check_airshield_candidates import candidates, check_records, split_setup
from mac_band_probe import field, typed_frame
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


class CandidateChecks(unittest.TestCase):
    def test_public_vector_identifies_modern_keys_and_prefix(self):
        secret = bytes.fromhex("f2f6f1f1a56fb52122ec338ed887338b42b976290253dbd6f48f3cc0b15b2ba8")
        seed = bytes.fromhex("c58e0f4bf291a0b2f50a40955b0bd53c9c7fd5a9f5fdbf7b14272efed585ca14")
        packet = bytes.fromhex("40f4d00bc5a22d9ecd0055ff7a63ea6ac9f1723721ffa9d7f4a7")
        matches = []
        for name, keys in candidates(secret, b"0123456789abcdef", seed):
            for framing in (3, 31):
                result = check_records(packet, keys, bytes(16), 0xba8d8b80, framing)
                if result["authenticated_packets"]:
                    matches.append((name, framing))
        self.assertEqual(matches, [("verified-31", 31)])

    def test_bad_tag_and_partial_record_are_not_matches(self):
        keys = DirectionalKeys(bytes(range(32)), bytes(range(32)))
        packet = bytes.fromhex("40c9f748fb0f0ae8e0018675352ee743a1e58ccd288d25d27f6e72551887e4aad6fc68175e7287a1eee1")
        for bad in (packet[:1] + bytes([packet[1] ^ 1]) + packet[2:], packet[:-1]):
            result = check_records(bad, keys, bytes(range(16)), 0xffffffff, 3)
            self.assertEqual(result["authenticated_packets"], 0)
            self.assertFalse(result["complete"])

    def test_empty_stream_is_not_positive_evidence(self):
        result = check_records(b"", DirectionalKeys(bytes(32), bytes(32)), bytes(16), 0, 3)
        self.assertEqual(result["authenticated_packets"], 0)

    def test_setup_boundaries_and_truncation(self):
        public = ec.derive_private_key(1, ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)[1:]
        request = typed_frame(0x8001, [0x81000005, 0x02000001],
                              field(1, public) + field(2, bytes(16)) + field(4, 27))
        enable = typed_frame(1, [0x02000002], field(1, public) + field(2, bytes(32))
                             + field(3, bytes(16)) + field(5, 26))
        messages, tail = split_setup(request + enable + b"opaque")
        self.assertEqual(messages[0][4], 27)
        self.assertEqual(messages[1][5], 26)
        self.assertEqual(tail, b"opaque")
        for broken in (b"", request[:-1], request + enable[:-1], enable + request):
            with self.assertRaises(ValueError):
                split_setup(broken)


if __name__ == "__main__":
    unittest.main()
