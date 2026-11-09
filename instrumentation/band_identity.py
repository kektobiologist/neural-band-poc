"""Keychain owner identities and durable, non-secret band-to-key references."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

SUPPORT = Path.home() / "Library/Application Support/NeuralBand"
REGISTRY = SUPPORT / "identities.json"
SERVICE = "local.neural-band-poc.identity"


def fingerprint(key):
    public = key.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)
    return hashlib.sha256(public).hexdigest()


def reference_parts(value):
    parts = str(value).split(":")
    if len(parts) != 3 or parts[0] != "keychain" or len(parts[2]) != 64:
        raise ValueError("Invalid Keychain identity reference")
    try:
        identifier = str(uuid.UUID(parts[1])).upper()
        bytes.fromhex(parts[2])
    except ValueError:
        raise ValueError("Invalid Keychain identity reference") from None
    if parts[2] != parts[2].lower():
        raise ValueError("Invalid Keychain fingerprint")
    return identifier, parts[2]


def normalize_reference(value):
    value = str(value)
    if value.startswith("keychain:"):
        identifier, digest = reference_parts(value)
        return f"keychain:{identifier}:{digest}"
    return str(Path(value).expanduser().resolve())


def helper():
    source = Path(__file__).resolve().parent / "meta_login/IdentityStore.swift"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    directory = SUPPORT / "tools"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = directory / ("identity-store-" + digest)
    if not binary.exists():
        fd, temporary = tempfile.mkstemp(dir=directory)
        os.close(fd)
        try:
            result = subprocess.run(["xcrun", "swiftc", "-parse-as-library", str(source), "-o", temporary],
                                    capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError("Identity helper compilation failed: " + result.stderr)
            os.replace(temporary, binary)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return binary


def keychain(command, reference, raw=None):
    identifier, digest = reference_parts(reference)
    try:
        result = subprocess.run([str(helper()), command, identifier + ":" + digest],
                                input=raw, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError("Keychain access timed out; unlock it and retry") from None
    if result.returncode:
        # Errors from this helper contain status codes only, never key bytes.
        raise ValueError(result.stderr.decode(errors="replace").strip() or "Keychain access failed")
    if len(result.stdout) != 32:
        raise ValueError("Keychain returned an invalid identity")
    key = ec.derive_private_key(int.from_bytes(result.stdout, "big"), ec.SECP256R1())
    if fingerprint(key) != digest:
        raise ValueError("Keychain identity does not match its reference")
    return key


def load_identity(value):
    if str(value).startswith("keychain:"):
        return keychain("read", value)
    key = serialization.load_pem_private_key(Path(value).expanduser().read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Owner identity must be a P-256 private key")
    return key


def store_identity(identifier, key):
    identifier = str(uuid.UUID(identifier)).upper()
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Owner identity must be a P-256 private key")
    reference = f"keychain:{identifier}:{fingerprint(key)}"
    saved = keychain("store", reference, key.private_numbers().private_value.to_bytes(32, "big"))
    if fingerprint(saved) != fingerprint(key):
        raise ValueError("Keychain readback did not match; original key retained")
    return reference


def read_registry(path=None):
    path = REGISTRY if path is None else path
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Invalid identity registry")
    return data


def resolve_identity(identifier, captures=None):
    # A durable active identity takes priority over stale worktree mappings.
    identity = read_registry().get(identifier)
    if identity is None and captures is not None:
        identity = read_registry(Path(captures) / "dashboard-identities.json").get(identifier)
    return normalize_reference(identity) if identity else None


def activate_identity(identifier, reference, path=None):
    identifier = str(uuid.UUID(identifier)).upper()
    reference = normalize_reference(reference)
    reference_parts(reference)
    path = REGISTRY if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_registry(path)
        data[identifier] = reference
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier")
    parser.add_argument("--import-pem", type=Path, required=True,
                        help="store/read back an existing PEM; does not activate, enroll, or delete it")
    args = parser.parse_args()
    try:
        print(store_identity(args.identifier, load_identity(args.import_pem)))
        print("Stored and read back from Keychain. Verify the reference with enroll_band.py --verify-key before activation.")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")
