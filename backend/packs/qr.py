"""QR code encoder, written by hand (standard library only).

Byte mode, error correction level L, versions 1 to 15 (up to 520 characters), best of the 8 masks
by the standard penalty rules. encode(text) returns a list of strings of "0" and "1", one per row
(1 = dark). The caller draws it with a 4-module empty border.

Used to show the authenticator-app setup code. Checked in the tests by decoding with an
independent reader (OpenCV) when it is installed.
"""

# version: (ec codewords per block, [(blocks, data codewords per block), ...]) for level L
_BLOCKS = {
    1: (7, [(1, 19)]), 2: (10, [(1, 34)]), 3: (15, [(1, 55)]), 4: (20, [(1, 80)]), 5: (26, [(1, 108)]),
    6: (18, [(2, 68)]), 7: (20, [(2, 78)]), 8: (24, [(2, 97)]), 9: (30, [(2, 116)]),
    10: (18, [(2, 68), (2, 69)]), 11: (20, [(4, 81)]), 12: (24, [(2, 92), (2, 93)]),
    13: (26, [(4, 107)]), 14: (30, [(3, 115), (1, 116)]), 15: (22, [(5, 87), (1, 88)]),
}
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
    9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62],
    14: [6, 26, 46, 66], 15: [6, 26, 48, 70],
}
_LEVEL_L_BITS = 1

# ---- Reed-Solomon over GF(256), polynomial 0x11D ----
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree):
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        poly = nxt
    return poly


def _remainder(data, degree):
    gen = _generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _mul(gen[i + 1], factor)
    return rem


def _capacity(version):
    ec, groups = _BLOCKS[version]
    return sum(n * d for n, d in groups)


def _pick_version(length):
    for v in range(1, 16):
        header = 4 + (8 if v < 10 else 16)
        if (header + 8 * length + 7) // 8 <= _capacity(v):
            return v
    raise ValueError("text is too long for the QR encoder (limit about 520 characters)")


def _codewords(raw, version):
    bits = "0100" + format(len(raw), "08b" if version < 10 else "016b") + "".join(format(b, "08b") for b in raw)
    total = _capacity(version) * 8
    bits += "0" * min(4, total - len(bits))
    bits += "0" * (-len(bits) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(data) < _capacity(version):
        data.append(pad[(len(data) - len(bits) // 8) % 2])
    ec_len, groups = _BLOCKS[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[pos:pos + size])
            pos += size
    ecs = [_remainder(b, ec_len) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec_len):
        out += [e[i] for e in ecs]
    return out


# ---- matrix ----

def _bch(value, poly, shift):
    d = value << shift
    top = poly.bit_length()
    while d.bit_length() >= top:
        d ^= poly << (d.bit_length() - top)
    return (value << shift) | d


def _function_patterns(version):
    size = 17 + 4 * version
    m = [[None] * size for _ in range(size)]

    def finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < size and 0 <= c0 + c < size:
                    m[r0 + r][c0 + c] = ((0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6))
                                         or (2 <= r <= 4 and 2 <= c <= 4))
    finder(0, 0); finder(size - 7, 0); finder(0, size - 7)
    pos = _ALIGN[version]
    for r in pos:
        for c in pos:
            if m[r][c] is None:
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        m[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    for i in range(8, size - 8):
        if m[i][6] is None:
            m[i][6] = i % 2 == 0
        if m[6][i] is None:
            m[6][i] = i % 2 == 0
    return m


def _set_format(m, version, mask, reserve_only=False):
    size = len(m)
    bits = _bch((_LEVEL_L_BITS << 3) | mask, 0x537, 10) ^ 0x5412
    for i in range(15):
        bit = (not reserve_only) and bool((bits >> i) & 1)
        m[i if i < 6 else i + 1 if i < 8 else size - 15 + i][8] = bit
        m[8][size - i - 1 if i < 8 else 15 - i if i < 9 else 14 - i] = bit
    m[size - 8][8] = True  # the always-dark module
    if version >= 7:
        vbits = _bch(version, 0x1F25, 12)
        for i in range(18):
            bit = bool((vbits >> i) & 1)
            m[i // 3][i % 3 + size - 11] = bit
            m[i % 3 + size - 11][i // 3] = bit


_MASKS = [
    lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r * c) % 3 + (r + c) % 2) % 2 == 0,
]


def _place(m, data, mask):
    size, fn = len(m), _MASKS[mask]
    bit_total = len(data) * 8
    index, row, step = 0, size - 1, -1
    for col in range(size - 1, 0, -2):
        if col <= 6:
            col -= 1
        while True:
            for c in (col, col - 1):
                if m[row][c] is None:
                    dark = index < bit_total and bool((data[index // 8] >> (7 - index % 8)) & 1)
                    m[row][c] = dark != fn(row, c)
                    index += 1
            row += step
            if row < 0 or row >= size:
                row -= step
                step = -step
                break


def _penalty(m):
    size, score = len(m), 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for line in grid:
            run = 1
            for i in range(1, size):
                if line[i] == line[i - 1]:
                    run += 1
                else:
                    score += run - 2 if run >= 5 else 0
                    run = 1
            score += run - 2 if run >= 5 else 0
            text = "".join("1" if x else "0" for x in line)
            for pat in ("10111010000", "00001011101"):
                start = text.find(pat)
                while start != -1:
                    score += 40
                    start = text.find(pat, start + 1)
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(x for line in m for x in line)
    score += 10 * (abs(dark * 100 // (size * size) - 50) // 5)
    return score


def encode(text):
    raw = text.encode("utf-8")
    version = _pick_version(len(raw))
    data = _codewords(raw, version)
    base = _function_patterns(version)
    _set_format(base, version, 0, reserve_only=True)
    best = None
    for mask in range(8):
        m = [row[:] for row in base]
        _place(m, data, mask)
        _set_format(m, version, mask)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return ["".join("1" if x else "0" for x in row) for row in best[1]]
