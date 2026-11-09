# Band connection guidance

Read [docs/mac-enrollment.md](docs/mac-enrollment.md) before changing connection,
identity, pairing, or authentication code. It is the current operational guide.

- **Default: connect directly from macOS using the existing Keychain identity.**
  Clients automatically resolve the selected band from
  `~/Library/Application Support/NeuralBand/identities.json`.
  Normal connections do not require a phone, another login, or re-enrollment.
- **Recovery: use `instrumentation/enroll_band.py` and native Meta sign-in.**
  First try a saved candidate Keychain reference with `--verify-key` without
  changing ownership again.
- Do not return to Android/ADB/root/Frida identity extraction as the default.
  That is historical research, superseded by the successful Mac enrollment
  and raw-EMG hardware test on November 9, 2026. Do not reintroduce the old
  instruction to unpair/reset before ordinary connections.
- Enrollment changes the owner app identity. Reuse the working key first;
  do not automatically enroll on every connection failure or reset the band.
  Diagnose Bluetooth contention, pairing state, and the actual error first.
- Private owner keys and Meta sessions belong in macOS Keychain. Never commit
  keys/tokens or paste them in logs. New enrollment must save and read back its
  candidate in Keychain before sending any ownership request.
- The durable identity registry contains references only and survives worktree
  deletion. It takes precedence over legacy checkout mappings. Keychain denial
  must fail visibly, never trigger re-enrollment or fallback to another key.
  Captures and recovery metadata remain ignored and checkout-local.
- Meta can return either `oculus://frl_login` or `fb-viewapp://frl_login`.
  Preserve support for both exact endpoints and request-token validation.
- Keep the CoreBluetooth delegate class registered only once per process;
  enrollment performs a second connection to verify the new key.

Relevant checks: `python -m unittest discover -s instrumentation -p 'test_*.py'`,
`python -m unittest discover -s dashboard/tests -p 'test_*.py'`, and the compiled
Meta login helper's `--self-test`. Mock tests do not establish hardware success;
record live validation separately.
