"""Enroll a Mac-generated owner identity using Meta sign-in; no Android required."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives.asymmetric import ec
from band_identity import load_identity, store_identity, normalize_reference, activate_identity
from band_access import band_connection
from enrollment import EnrollmentHandshake
from mac_band_probe import run_probe
from meta_pair import MetaPairClient, SessionExpired

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "captures"


def private_write(path, data, exclusive=False):
    """Private from creation; atomic replacement and durable contents."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def login_helper():
    sources = [ROOT / "instrumentation/meta_login" / name for name in ("MetaAuth.swift", "Login.swift")]
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest()[:16]
    binary = CAPTURES / "tools" / ("meta-login-" + digest)
    if not binary.exists():
        binary.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["xcrun", "swiftc", "-parse-as-library", *map(str, sources),
                                 "-o", str(binary)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Meta login helper failed to compile:\n" + result.stderr)
    return binary


def session(binary, force=False):
    print("Opening Meta sign-in if needed. Your session is saved in macOS Keychain.", flush=True)
    diagnostics = CAPTURES / "meta-login-status.log"
    fd = os.open(diagnostics, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as errors:
            result = subprocess.run([str(binary), "--login" if force else "--session"],
                                    stdout=subprocess.PIPE, stderr=errors, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise ValueError("Meta sign-in timed out. Run enrollment again.") from None
    if result.returncode:
        # Helper errors are deliberately sanitized, but never print stdout.
        messages = [line.removeprefix("[meta-login] ") for line in diagnostics.read_text().splitlines()
                    if line.startswith("[meta-login] ")]
        if result.returncode == 2:
            raise ValueError("Meta sign-in was cancelled.")
        raise ValueError(messages[-1] if messages else "Meta sign-in failed; see the private login status log.")
    try:
        value = json.loads(result.stdout)
        if value.get("universe") != "ar" or not value.get("access_token") or not value.get("user_id"):
            raise ValueError()
        return value
    except (ValueError, AttributeError):
        raise ValueError("Meta login helper returned an invalid session") from None


def probe_args(identifier, seconds=35, key=None):
    return SimpleNamespace(identifier=identifier, seconds=seconds, identity_key=key,
                           query_device_info=key is not None, end_link_setup=False, stream_control=None,
                           query_config=False, hand=None, dial_settings=None)


def verify(identifier, key, emit):
    accepted = False
    def observe(event, **data):
        nonlocal accepted
        if event == "probe_result":
            accepted = data.get("owner_identity_accepted", False)
        emit(event, **data)
    if not run_probe(probe_args(identifier, key=key), observe) or not accepted:
        raise ValueError("Fresh connection did not confirm the new identity; key retained, dashboard unchanged")


def register_identity(identifier, key, directory=CAPTURES):
    path = directory / "dashboard-identities.json"
    identities = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(identities, dict):
        raise ValueError("Existing dashboard identity mapping is invalid; key retained")
    identities[identifier] = normalize_reference(key)
    private_write(path, json.dumps(identities, indent=2).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier", nargs="?", help="band CoreBluetooth UUID; otherwise scan and require exactly one band")
    parser.add_argument("--login", action="store_true", help="sign in again, including to change Meta accounts")
    parser.add_argument("--prepare", action="store_true", help="compile the native login helper without signing in or connecting")
    parser.add_argument("--login-only", action="store_true", help="sign in and save the session without touching the band")
    parser.add_argument("--verify-key", help="retry a Keychain reference or existing PEM without enrolling again")
    parser.add_argument("--no-dashboard", action="store_true", help="leave the dashboard identity mapping unchanged")
    args = parser.parse_args()
    if args.prepare:
        print(login_helper())
        return 0
    identifier = str(uuid.UUID(args.identifier)).upper() if args.identifier else None
    binary = login_helper() if not args.verify_key else None
    account = session(binary, args.login) if binary else None
    if args.login_only:
        print("Meta sign-in succeeded. The session is saved for enrollment.", flush=True)
        return 0
    print("Put the band in pairing mode. Accept any macOS Bluetooth pairing prompt.", flush=True)
    with band_connection():
        if not identifier:
            from scan_band import scan_bands
            bands = asyncio.run(scan_bands())
            if len(bands) != 1:
                print(json.dumps(bands, indent=2))
                raise ValueError("Expected exactly one band. Retry with its UUID, or put it in pairing mode.")
            identifier = str(uuid.UUID(bands[0]["address"])).upper()
        print("Band: " + identifier, flush=True)
        CAPTURES.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        log = CAPTURES / ("enrollment-" + stamp + ".jsonl")
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as capture:
            def emit(event, **data):
                # Allowlist events: no raw traffic, credentials, receipt, or session material.
                allowed = {"bluetooth_state", "connected", "disconnected", "psm_discovered", "l2cap_open",
                           "enrollment_stage", "owner_trust_accepted", "peer_link_setup_received",
                           "probe_result", "enrollment_error"}
                if event not in allowed:
                    return
                row = {"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
                capture.write(json.dumps(row) + "\n")
                capture.flush()
                print(json.dumps(row), flush=True)
            key_path = normalize_reference(args.verify_key) if args.verify_key else None
            if not args.verify_key:
                key = ec.generate_private_key(ec.SECP256R1())
                key_path = store_identity(identifier, key)
                metadata = CAPTURES / "identities" / f"{identifier}-{stamp}.json"
                def checkpoint(state, band_public):
                    private_write(metadata, json.dumps({"identifier": identifier, "identity": key_path, "state": state,
                                  "band_public_key": band_public.hex() if band_public else None}).encode())
                checkpoint("candidate", None)
                print("Recovery Keychain reference: " + str(key_path), flush=True)
                # HTTP work runs off the CoreBluetooth/main run loop.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    handshake = EnrollmentHandshake(emit, key, MetaPairClient(account), executor, checkpoint)
                    try:
                        run_probe(probe_args(identifier, seconds=180), emit, handshake=handshake)
                    except SessionExpired:
                        subprocess.run([str(binary), "--forget"], capture_output=True)
                        raise
            print("Checking the identity on a fresh band connection…", flush=True)
            verify(identifier, key_path, emit)
            if not args.no_dashboard:
                if not key_path.startswith("keychain:"):
                    key_path = store_identity(identifier, load_identity(key_path))
                activate_identity(identifier, key_path)
                register_identity(identifier, key_path)
            print("Enrolled identity verified: " + str(key_path), flush=True)
            print("Use this reference with mac_band_probe.py --identity-key.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print("Enrollment failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
