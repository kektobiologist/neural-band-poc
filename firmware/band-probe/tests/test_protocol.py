"""Exercise the actual C protocol against the independent Python implementation.

Build mbedTLS for the host first; pass --mbedtls-source and --mbedtls-build.
Tests use a synthetic owner key, never the enrolled device identity.
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'instrumentation'))
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from airshield import StreamDecryptor, derive_keys
from analyze_capture import protobuf_fields
from mac_band_probe import BandHandshake, field, typed_frame


def fields(data):
    return {n: v for n, w, v in protobuf_fields(data)}


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)[1:]


def build(source, library, folder):
    owner = ec.derive_private_key(1, ec.SECP256R1())
    header = ''
    for name, value in [('owner_private', (1).to_bytes(32, 'big')), ('owner_public', public(owner))]:
        header += f'static const unsigned char {name}[] = {{' + ','.join(str(x) for x in value) + '};\n'
    (folder / 'test_owner.h').write_text(header)
    (folder / 'esp_log.h').write_text('''#include <stdio.h>
#define ESP_LOGI(tag, fmt, ...) printf("LOG " fmt "\\n", ##__VA_ARGS__)
#define ESP_LOGE(tag, fmt, ...) printf("LOG " fmt "\\n", ##__VA_ARGS__)
''')
    (folder / 'esp_random.h').write_text('''#include <stdlib.h>
static inline void esp_fill_random(void *out, size_t len) { arc4random_buf(out, len); }
''')
    (folder / 'harness.c').write_text('''#include <stdio.h>
#include <string.h>
#include "band_protocol.h"
static bool send_data(const unsigned char *p,size_t n) {
    printf("TX ");for(size_t i=0;i<n;i++)printf("%02x",p[i]);puts("");return true;
}
int main(void) {
    char line[20000];unsigned char data[8192];
    while(fgets(line,sizeof(line),stdin)) {
        bool ok=false;
        if(!strncmp(line,"start",5))ok=band_protocol_start(send_data);
        else {
            size_t n=strcspn(line,"\\r\\n")/2;
            if(n>sizeof(data))return 2;
            for(size_t i=0;i<n;i++){unsigned v;if(sscanf(line+i*2,"%2x",&v)!=1)return 3;data[i]=v;}
            ok=band_protocol_feed(data,n);
        }
        printf("STATUS %d %d %u %u\\n",ok,band_protocol_streaming(),band_protocol_gestures(),band_protocol_packets());
        fflush(stdout);
    }
    band_protocol_close();return 0;
}
''')
    executable = folder / 'protocol_test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Wno-unused-parameter',
        '-Wno-unused-variable', '-DCONFIG_BAND_OWNER_AUTH=1', '-DBAND_OWNER_HEADER="test_owner.h"',
        '-I' + str(folder), '-I' + str(source / 'include'),
        '-I' + str(ROOT / 'firmware/band-probe/main'),
        str(folder / 'harness.c'), str(ROOT / 'firmware/band-probe/main/band_protocol.c'),
        str(library / 'library/libmbedcrypto.a'), '-o', str(executable)], check=True)
    return executable, owner


class Harness:
    def __init__(self, executable):
        self.p = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def command(self, data):
        self.p.stdin.write(data + '\n')
        self.p.stdin.flush()
        tx, logs = [], []
        while True:
            line = self.p.stdout.readline().strip()
            if line.startswith('TX '):
                tx.append(bytes.fromhex(line[3:]))
            elif line.startswith('STATUS '):
                return tx, logs, tuple(map(int, line.split()[1:]))
            elif line.startswith('LOG '):
                logs.append(line[4:])
            elif not line:
                raise AssertionError('C harness exited unexpectedly')

    def feed(self, data, split=False):
        tx, logs, status = [], [], None
        chunks = [data[i:i + 1] for i in range(len(data))] if split else [data]
        for chunk in chunks:
            t, l, status = self.command(chunk.hex())
            tx.extend(t)
            logs.extend(l)
        return tx, logs, status

    def close(self):
        self.p.stdin.close()
        assert self.p.wait(timeout=5) == 0


def session(h, owner, mode):
    tx, _, status = h.command('start')
    assert status[0] == 1 and len(tx) == 1
    hello = fields(tx[0][12:])
    assert hello[4] == 31
    peer = ec.generate_private_key(ec.SECP256R1())
    challenge, seed, iv, counter = b'c' * 16, b's' * 32, b'i' * 16, 42
    request = typed_frame(0x8001, [0x81000005, 0x02000001],
        field(1, public(peer)) + field(2, challenge) + field(4, 31 if mode == 26 else 3))
    tx, _, status = h.feed(request, split=True)
    assert status[0] == 1 and len(tx) == 1
    enable = fields(tx[0][8:])
    secret = peer.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b'\x04' + hello[1]))
    decoder = StreamDecryptor(derive_keys(secret, challenge, enable[2], enable[5]), enable[3], enable[4], enable[5])
    peer_enable = typed_frame(1, [0x02000002], field(1, public(peer)) + field(2, seed) + field(3, iv) + field(4, counter) + field(5, mode))
    tx, _, status = h.feed(peer_enable)
    assert status[0] == 1 and len(tx) == 1
    proof_record = list(decoder.feed(tx[0]))[0].plaintext
    size = (int.from_bytes(proof_record[:2], 'big') & 0x7fff) + 4
    proof = fields(proof_record[12:size])
    assert proof[1] == hashlib.sha256(public(owner)).digest() and proof[3] == 2
    digest = hashlib.sha256(hashlib.sha256(challenge + public(peer)).digest() + hashlib.sha256(enable[2] + hello[1]).digest()).digest()
    signature = utils.encode_dss_signature(int.from_bytes(proof[2][:32], 'big'), int.from_bytes(proof[2][32:], 'big'))
    owner.public_key().verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    encoder = BandHandshake(lambda *args, **kwargs: None)
    encoder.tx_keys = derive_keys(secret, hello[2], seed, mode)
    encoder.tx_parameters, encoder.iv, encoder.base = mode, iv, counter
    return encoder, decoder


def exercise(executable, owner):
    h = Harness(executable)
    try:
        for mode in (26, 3):
            encoder, decoder = session(h, owner, mode)
            offer = typed_frame(0x8003, [0x81000024, 0x02001001], field(2, b'p' * 64))
            ack = typed_frame(2, [0x03001000])
            setup = typed_frame(0x9001, [0x02001000], field(2, b'u' * 16))
            wire = encoder.encrypt_frame(offer) + encoder.encrypt_frame(ack + setup)
            tx, _, status = h.feed(wire, split=True)
            assert status[0] == 1 and status[1] == 0
            packets = list(decoder.feed(b''.join(tx)))
            assert len(packets) == 4  # peer ack, EndLinkSetup, query, enable
            response = typed_frame(5, [0x02000315], field(1, 3) + field(2, 1) + field(5, field(3, 1)))
            _, _, status = h.feed(encoder.encrypt_frame(response))
            assert status[:2] == (1, 1)
            gesture = typed_frame(0x9005, [0x0200020d], field(1, 9) + field(2, 1234567890123) + field(3, 2) + field(4, 3) + field(5, 1))
            encrypted = encoder.encrypt_frame(gesture)
            _, logs, status = h.feed(encrypted, split=True)
            assert status[2] == 1 and any('finger=index action=tap derived=singleTap synthetic=0 band_us=1234567890123' in line for line in logs)
            _, logs, status = h.feed(encrypted)  # replay must fail MAC, release no gesture
            assert status[:3] == (0, 0, 1) and any('MAC mismatch' in line for line in logs)
            print(f'PASS mode {mode}: fragmented handshake, independent proof verification, authenticated startup, gesture decoding, replay rejection')
        encoder, _ = session(h, owner, 26)
        _, logs, status = h.feed(encoder.encrypt_frame(typed_frame(2, [0x03001043])))
        assert status[:3] == (0, 0, 0) and any('identity rejected' in line for line in logs)
        print('PASS owner rejection never enables streaming')
    finally:
        h.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mbedtls-source', type=Path, required=True)
    parser.add_argument('--mbedtls-build', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='band-protocol-test-') as temp:
        executable, owner = build(args.mbedtls_source, args.mbedtls_build, Path(temp))
        exercise(executable, owner)
