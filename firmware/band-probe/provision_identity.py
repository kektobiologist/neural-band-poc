"""Create a private, ignored firmware header from the already enrolled owner PEM."""
import argparse
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('pem', type=Path)
a = p.parse_args()
key = serialization.load_pem_private_key(a.pem.read_bytes(), password=None)
if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
    p.error('Owner key must be P-256')
private = key.private_numbers().private_value.to_bytes(32, 'big')
public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)[1:]
output = Path(__file__).parent / 'main' / 'owner_identity.h'
text = '// PRIVATE: generated locally; never commit this file or share this firmware.\n'
for name, value in [('owner_private', private), ('owner_public', public)]:
    text += f'static const unsigned char {name}[{len(value)}] = {{' + ','.join(f'0x{x:02x}' for x in value) + '};\n'
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(text)
os.chmod(output, 0o600)
print('Provisioned local owner identity header; key material not printed.')
