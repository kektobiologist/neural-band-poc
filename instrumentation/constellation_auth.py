"""Diagnostic subset of service 0x4f, recovered from Meta AI 292 Android DEX.

Consumes MAC-verified plaintext only. Retrieves at most one manifest per session;
never accepts trust, signs challenges, registers an app, or installs a manifest.
Manifest transfer completion does not establish its validity or peer identity.
"""
import hashlib

from extract_telemetry import DataXStream, checked_fields


class ConstellationDiagnostic:
    def __init__(self, emit, request_manifest=False, max_manifest_bytes=1024 * 1024):
        self.emit = emit
        self.request_manifest = request_manifest
        self.max_manifest_bytes = max_manifest_bytes
        self.frames = DataXStream()
        self.channel = None
        self.requested = False
        self.complete = False
        self.manifest = bytearray()

    def feed(self, plaintext):
        """Yield (reply channel, result word) for a single NEED_MANIFEST response."""
        for channel, words, payload, _ in self.frames.feed(plaintext, {}):
            if words[:1] == [0x8100004f]:
                if not channel & 0x8000:
                    raise ValueError("Constellation service opened without remote channel bit")
                if self.channel is not None and self.channel != channel:
                    raise ValueError("multiple Constellation channels are unsupported")
                self.channel = channel
                words = words[1:]
            if self.channel is None or channel != self.channel:
                continue
            if words == [0x02000001]:
                fields = checked_fields(payload)
                tag = fields.get((1, 2), b"")
                signature = fields.get((2, 2), b"")
                version = fields.get((3, 0), 0)
                if len(tag) != 8 or len(signature) != 64:
                    raise ValueError("unsupported Constellation key tag/signature shape")
                capabilities = checked_fields(fields.get((7, 2), b""))
                # Generated schema identifies an enum, not a boolean. Its value
                # names are not recovered; preserve 2 rather than calling it True.
                can_send_manifest = capabilities.get((1, 0))
                self.emit("constellation_trust_offer", manifest_version=version,
                          can_send_manifest_raw=can_send_manifest,
                          key_tag_bytes=len(tag), signature_bytes=len(signature),
                          identity_verified=False)
                if self.request_manifest and version > 0 and not self.requested:
                    self.requested = True
                    self.emit("constellation_manifest_requested", channel=channel & 0x7fff)
                    yield channel & 0x7fff, 0x03000003
            elif words in ([0x02000002], [0x02000004]):
                if not self.requested or self.complete:
                    raise ValueError("unsolicited or repeated Constellation manifest transfer")
                if len(self.manifest) + len(payload) > self.max_manifest_bytes:
                    raise ValueError("Constellation manifest exceeds diagnostic size limit")
                self.manifest.extend(payload)
                if words == [0x02000004]:
                    self.complete = True
                    self.emit("constellation_manifest_complete", bytes=len(self.manifest),
                              sha256=hashlib.sha256(self.manifest).hexdigest(),
                              empty=not self.manifest, manifest_verified=False)
            else:
                self.emit("constellation_unhandled", words=words, payload_bytes=len(payload))

    def finish(self):
        self.frames.finish()
        if self.requested and not self.complete:
            self.emit("constellation_manifest_incomplete", bytes=len(self.manifest))
