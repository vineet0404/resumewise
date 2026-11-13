"""The parts of WebAuthn (passkeys) the server needs, written by hand with the standard library.

- a small CBOR reader (RFC 8949), enough for the browser's attestation and public-key data
- NIST P-256 ECDSA signature checking (only checking, never signing, so no secret is involved)
- authenticator-data parsing

Passkeys use the "ES256" algorithm (COSE -7), which every current phone, Windows Hello and
password manager supports.
"""

import hashlib

# ---------------- CBOR ----------------

MAX_DEPTH = 8


class WebAuthnError(ValueError):
    pass


def _cbor_item(d, i, depth=0):
    if depth > MAX_DEPTH or i >= len(d):
        raise WebAuthnError("bad CBOR")
    major, info = d[i] >> 5, d[i] & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        if i + size > len(d):
            raise WebAuthnError("bad CBOR")
        n = int.from_bytes(d[i:i + size], "big")
        i += size
    else:
        raise WebAuthnError("unsupported CBOR")  # indefinite lengths are not used by WebAuthn
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(d):
            raise WebAuthnError("bad CBOR")
        chunk = d[i:i + n]
        return (bytes(chunk) if major == 2 else chunk.decode("utf-8")), i + n
    if major == 4:
        if n > len(d):
            raise WebAuthnError("bad CBOR")
        out = []
        for _ in range(n):
            v, i = _cbor_item(d, i, depth + 1)
            out.append(v)
        return out, i
    if major == 5:
        if n > len(d):
            raise WebAuthnError("bad CBOR")
        out = {}
        for _ in range(n):
            k, i = _cbor_item(d, i, depth + 1)
            v, i = _cbor_item(d, i, depth + 1)
            out[k] = v
        return out, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise WebAuthnError("unsupported CBOR")


def cbor_decode(data):
    try:
        value, end = _cbor_item(bytes(data), 0)
    except (IndexError, UnicodeDecodeError) as exc:
        raise WebAuthnError("bad CBOR") from exc
    if end != len(data):
        raise WebAuthnError("extra bytes after CBOR")
    return value


# ---------------- P-256 ----------------

P = 2 ** 256 - 2 ** 224 + 2 ** 192 + 2 ** 96 - 1
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def on_curve(point):
    x, y = point
    return 0 < x < P and 0 < y < P and (y * y - (x * x * x - 3 * x + B)) % P == 0


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    (x1, y1), (x2, y2) = a, b
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        m = (3 * x1 * x1 - 3) * pow(2 * y1, -1, P) % P
    else:
        m = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (m * m - x1 - x2) % P
    return x3, (m * (x1 - x3) - y1) % P


def mul(k, point):
    result, addend = None, point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def ecdsa_verify(public_point, message, der_signature):
    """True only if der_signature is a valid ES256 signature of message by public_point."""
    try:
        r, s = _parse_der_signature(der_signature)
    except WebAuthnError:
        return False
    if not (0 < r < N and 0 < s < N) or not on_curve(public_point):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _add(mul(e * w % N, G), mul(r * w % N, public_point))
    return point is not None and point[0] % N == r


def _parse_der_signature(sig):
    # SEQUENCE { INTEGER r, INTEGER s }, short-form lengths only (a P-256 signature is at most 72 bytes)
    try:
        if sig[0] != 0x30 or sig[1] != len(sig) - 2 or sig[1] >= 0x80:
            raise WebAuthnError("bad signature")
        i, out = 2, []
        for _ in range(2):
            if sig[i] != 0x02:
                raise WebAuthnError("bad signature")
            n = sig[i + 1]
            if n == 0 or n >= 0x80 or i + 2 + n > len(sig):
                raise WebAuthnError("bad signature")
            raw = sig[i + 2:i + 2 + n]
            if raw[0] & 0x80 or (n > 1 and raw[0] == 0 and not raw[1] & 0x80):
                raise WebAuthnError("bad signature")  # negative or not minimal
            out.append(int.from_bytes(raw, "big"))
            i += 2 + n
        if i != len(sig):
            raise WebAuthnError("bad signature")
        return out[0], out[1]
    except IndexError as exc:
        raise WebAuthnError("bad signature") from exc


# ---------------- authenticator data ----------------

FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40


def parse_auth_data(data):
    """Returns dict: rp_id_hash, flags, counter and, when present, credential_id and public_key (x, y)."""
    if len(data) < 37:
        raise WebAuthnError("authenticator data too short")
    out = {"rp_id_hash": bytes(data[:32]), "flags": data[32], "counter": int.from_bytes(data[33:37], "big")}
    if out["flags"] & FLAG_AT:
        rest = bytes(data[37:])
        if len(rest) < 18:
            raise WebAuthnError("credential data too short")
        cid_len = int.from_bytes(rest[16:18], "big")
        if cid_len == 0 or cid_len > 1023 or len(rest) < 18 + cid_len:
            raise WebAuthnError("bad credential id")
        out["credential_id"] = rest[18:18 + cid_len]
        try:
            key, _ = _cbor_item(rest, 18 + cid_len)
        except IndexError as exc:
            raise WebAuthnError("bad public key") from exc
        if not (isinstance(key, dict) and key.get(1) == 2 and key.get(3) == -7 and key.get(-1) == 1):
            raise WebAuthnError("only ES256 (P-256) passkeys are supported")
        x, y = key.get(-2), key.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
            raise WebAuthnError("bad public key")
        point = (int.from_bytes(x, "big"), int.from_bytes(y, "big"))
        if not on_curve(point):
            raise WebAuthnError("public key is not on the curve")
        out["public_key"] = point
    return out
