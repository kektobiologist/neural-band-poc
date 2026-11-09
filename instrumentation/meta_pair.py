"""Meta ownership HTTP client. No account tokens or receipt bodies in errors/logs.

Protocol adapted from callbacked/kinesis (MIT); see licenses/kinesis-MIT.txt.
"""
import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

HW_CLIENT = "HW|1312539125771114|98588f106d5d542adbf590619ca071fe"


class SessionExpired(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post(route, fields):
    request = Request("https://graph.facebook-hardware.com/" + route,
                      data=urlencode(fields).encode("ascii"),
                      headers={"Content-Type": "application/x-www-form-urlencoded",
                               "Accept": "application/json"})
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            status, body = response.status, response.read(1024 * 1024 + 1)
    except HTTPError as error:
        status, body = error.code, error.read(1024 * 1024 + 1)
    except (URLError, TimeoutError, OSError):
        raise ValueError("Meta enrollment request failed; check your connection and retry.") from None
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError):
        data = {}
    error = data.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if status in (401, 403) or code == 190:
        raise SessionExpired("Meta session expired. Run enrollment again with --login.")
    if status != 200 or error is not None or not data:
        raise ValueError(f"Meta enrollment failed (HTTP {status}, code {code if isinstance(code, int) else 'unknown'}).")
    return data


def receipt(data, name):
    value = data.get(name)
    try:
        signature = base64.b64decode(data.get("receipt_signature", ""), validate=True)
    except (ValueError, TypeError):
        signature = b""
    if not isinstance(value, str) or not value or not signature:
        raise ValueError("Meta returned an invalid ownership receipt.")
    return signature, value


class MetaPairClient:
    def __init__(self, session, transport=post):
        self.session, self.transport = session, transport

    def fields(self):
        return {"access_token": HW_CLIENT, "user_access_token": self.session["access_token"],
                "user_token_universe": "ar", "pair_protocol_version": "3"}

    def pair_request(self, certificate, serial, secondary, nonce, public):
        b64 = lambda value: base64.b64encode(value).decode("ascii")
        fields = self.fields()
        fields.update(device_cert=b64(certificate), serial_number=serial,
                      additional_data=json.dumps({"device_nonce": b64(nonce), "app_pubkey": b64(public),
                                                  "secondary_cert": b64(secondary)}, separators=(",", ":")))
        return receipt(self.transport("pair_request", fields), "pending_ownership_receipt")

    def pair(self, signature, value):
        fields = self.fields()
        fields.update(device_pending_ownership_receipt=value,
                      device_pending_ownership_receipt_signature=base64.b64encode(signature).decode("ascii"))
        data = self.transport("pair", fields)
        signature, value = receipt(data, "final_ownership_receipt")
        # Preserve receipts byte-for-byte; parsing here is for optional metadata only.
        try:
            embedded = json.loads(value)
        except ValueError:
            embedded = {}
        band_key = None
        for candidate in (data, embedded):
            additional = candidate.get("additional_data") if isinstance(candidate, dict) else None
            if isinstance(additional, dict) and additional.get("device_ec_public_key"):
                try:
                    band_key = base64.b64decode(additional["device_ec_public_key"], validate=True)
                except (ValueError, TypeError):
                    raise ValueError("Meta returned an invalid band public key.") from None
                if len(band_key) != 64:
                    raise ValueError("Meta returned an invalid band public key length.")
                break
        return signature, value, band_key
