import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric import ec
import band_identity as identity

UUID = "ABCBABE4-D7A6-4B05-BB42-E675678CFABA"

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.ref = f"keychain:{UUID}:{identity.fingerprint(self.key)}"

    def test_reference_validation(self):
        self.assertEqual(identity.normalize_reference(self.ref), self.ref)
        for value in ["keychain:x:y", self.ref + "x", self.ref.replace(UUID, "invalid")]:
            with self.assertRaises(ValueError):
                identity.reference_parts(value)

    def test_key_uses_private_pipe_and_checks_readback(self):
        raw = self.key.private_numbers().private_value.to_bytes(32, "big")
        with patch.object(identity, "helper", return_value=Path("/helper")), patch.object(
            identity.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=raw)) as run:
            self.assertEqual(identity.store_identity(UUID, self.key), self.ref)
            self.assertEqual(run.call_args.kwargs["input"], raw)
            self.assertNotIn(raw.hex(), str(run.call_args.args))
        other = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, "big")
        with patch.object(identity, "helper", return_value=Path("/helper")), patch.object(
            identity.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=other)):
            with self.assertRaisesRegex(ValueError, "does not match"):
                identity.load_identity(self.ref)

    def test_durable_registry_wins_and_preserves_other_bands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = root / "identities.json"
            registry.write_text(json.dumps({"other": "preserved"}))
            identity.activate_identity(UUID, self.ref, registry)
            self.assertEqual(json.loads(registry.read_text())["other"], "preserved")
            (root / "dashboard-identities.json").write_text(json.dumps({UUID: "/stale.pem"}))
            with patch.object(identity, "REGISTRY", registry):
                self.assertEqual(identity.resolve_identity(UUID, root), self.ref)
                self.assertIsNone(identity.resolve_identity("unknown", root))
