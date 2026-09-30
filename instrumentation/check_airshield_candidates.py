"""Offline hypothesis checks for Mac probe captures; never enables a wire mode.

Reports MAC-verified packet counts without emitting keys or plaintext. A match
on host TX only identifies what the experimental host sent, not band support.
"""

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from airshield import AuthenticatedPacket, DirectionalKeys, StreamDecryptor, derive_keys
from analyze_capture import protobuf_fields, setup_summary


def split_setup(data):
    messages = []
    for expected in ("RequestEncryption", "EnableEncryption"):
        if len(data) < 4 or not data[0] & 0x80:
            raise ValueError("missing or truncated setup header")
        size = (int.from_bytes(data[:2], "big") & 0x7fff) + 4
        if size < 8 or len(data) < size:
            raise ValueError("truncated setup message")
        frame, data = data[:size], data[size:]
        if setup_summary(frame)["message"] != expected:
            raise ValueError("unexpected setup ordering")
        offset = 12 if frame[2] & 0x80 else 8
        fields = {n: v for n, wire, v in protobuf_fields(frame[offset:])}
        messages.append(fields)
    if messages[0][1] != messages[1][1]:
        raise ValueError("public key changed during setup")
    return messages, data


def candidates(secret, challenge, seed):
    sha = lambda value: hashlib.sha256(value).digest()

    def hkdf(ikm, salt, info=b"AirShield"):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)

    legacy = derive_keys(secret, challenge, seed, 3)
    modern = derive_keys(secret, challenge, seed, 31)
    yield "verified-3", legacy
    yield "verified-31", modern
    yield "candidate-7", DirectionalKeys(legacy.encryption, hkdf(
        sha(secret), sha(seed + challenge + b"hmac_derive" + sha(secret))))
    yield "candidate-26-shared-modern-key", DirectionalKeys(modern.encryption, modern.encryption)
    # Native Meta AI 292 ARM64 image: 136 bytes at VA 0x2b53ce.
    # Selected by a separate internal field, NOT proven to be set for this band.
    context = b"AirShield" + bytes(119) + bytes.fromhex("2000000000010000")
    enc = hkdf(secret, sha(challenge + seed), context)
    mac = hkdf(secret, sha(seed + challenge + b"hmac_derive"), context)
    yield "candidate-long-context-shared", DirectionalKeys(enc, enc)
    yield "candidate-long-context-separate", DirectionalKeys(enc, mac)


def check_records(data, keys, iv, base, framing):
    decoder = StreamDecryptor(keys, iv, base, framing)
    authenticated = opaque = 0
    error = None
    try:
        for record in decoder.feed(data):
            if isinstance(record, AuthenticatedPacket):
                authenticated += 1
            else:
                opaque += 1
        decoder.finish()
    except ValueError as exc:
        error = str(exc)
    return {"authenticated_packets": authenticated, "opaque_records": opaque,
            "complete": error is None, "error": error}


def check_capture(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    material = [row for row in rows if row.get("event") == "session_material"]
    if len(material) != 1:
        raise ValueError("expected exactly one session_material event")
    material = material[0]
    streams = {direction: bytearray() for direction in ("tx", "rx")}
    for row in rows:
        if row.get("event") != "stream_bytes":
            continue
        chunk = bytes.fromhex(row["hex"])
        if len(chunk) != row["count"]:
            raise ValueError("stream byte count does not match captured bytes")
        streams[row["direction"]].extend(chunk)
    parsed = {direction: split_setup(bytes(data)) for direction, data in streams.items()}
    local = parsed["tx"][0]
    for name, observed in (("challenge", local[0][2]), ("seed", local[1][2]), ("iv", local[1][3])):
        if bytes.fromhex(material[name]) != observed:
            raise ValueError(f"session material {name} disagrees with wire")
    if material["base"] != local[1].get(4, 0):
        raise ValueError("session material counter disagrees with wire")
    result = {"capture": path.name, "directions": {}}
    for direction, (messages, data) in parsed.items():
        opposite = "rx" if direction == "tx" else "tx"
        enable = messages[1]
        checks = []
        for name, keys in candidates(bytes.fromhex(material["shared_secret"]),
                                     parsed[opposite][0][0][2], enable[2]):
            for framing in (3, 31):
                checks.append({"candidate": name, "mac_prefix": "" if framing == 3 else "02020000",
                               **check_records(data, keys, enable[3], enable.get(4, 0), framing)})
        result["directions"][direction] = {"offered": messages[0].get(4, 0),
            "selected": enable.get(5, 0), "post_setup_bytes": len(data), "checks": checks}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for path in args.captures:
        try:
            results.append(check_capture(path))
        except (ValueError, KeyError, TypeError) as exc:
            results.append({"capture": path.name, "error": str(exc)})
    with args.output.open("x") as output:
        json.dump(results, output, indent=2)
        output.write("\n")
    print(f"Checked {len(results)} captures; report: {args.output}")
    # Rejected hypotheses are normal research results, malformed inputs are not.
    raise SystemExit(int(any("error" in result for result in results)))
