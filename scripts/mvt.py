"""MVT(Mapbox Vector Tile) 최소 인코더. 정사각형 폴리곤과 포인트만 다룬다."""

EXTENT = 4096


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(num, wire, payload):
    if wire == 0:
        return varint(num << 3) + varint(payload)
    return varint(num << 3 | 2) + varint(len(payload)) + payload


def zz(n):
    return (n << 1) ^ (n >> 31)


def packed(nums):
    return b"".join(varint(n) for n in nums)


def square(x0, y0, size):
    """시계 방향(화면 좌표) 정사각형 외곽선."""
    return 3, [9, zz(x0), zz(y0), 26, zz(size), 0, 0, zz(size), zz(-size), 0, 15]


def point(x, y):
    return 1, [9, zz(x), zz(y)]


def polygon(rings):
    """rings: [[(x, y), ...], ...] 정수 타일 좌표. 첫 링은 외곽(양의 면적), 나머지는 구멍(음의 면적)으로 이미 정렬돼 있어야 한다.
    링마다 닫는 점은 빼고 넘긴다."""
    cmds, cx, cy = [], 0, 0
    for ring in rings:
        x, y = ring[0]
        cmds += [9, zz(x - cx), zz(y - cy)]
        cx, cy = x, y
        cmds.append(2 | (len(ring) - 1) << 3)
        for x, y in ring[1:]:
            cmds += [zz(x - cx), zz(y - cy)]
            cx, cy = x, y
        cmds.append(15)
    return 3, cmds


def encode_value(v):
    if isinstance(v, str):
        return field(1, 2, v.encode())
    if isinstance(v, bool):
        return field(7, 0, int(v))
    if isinstance(v, int):
        return field(5, 0, v) if v >= 0 else field(6, 0, zz(v))
    raise TypeError(type(v))


def encode_layer(name, keys, features):
    """features: [(fid or None, (geom_type, geom_cmds), [values in keys order; None은 생략])]"""
    values, value_idx, feats = [], {}, []
    for fid, (gtype, geom), props in features:
        tags = []
        for ki, v in enumerate(props):
            if v is None:
                continue
            if v not in value_idx:
                value_idx[v] = len(values)
                values.append(v)
            tags += (ki, value_idx[v])
        body = (field(1, 0, fid) if fid is not None else b"") + field(2, 2, packed(tags)) + field(3, 0, gtype) + field(4, 2, packed(geom))
        feats.append(field(2, 2, body))
    layer = field(15, 0, 2) + field(1, 2, name.encode()) + b"".join(feats)
    layer += b"".join(field(3, 2, k.encode()) for k in keys)
    layer += b"".join(field(4, 2, encode_value(v)) for v in values)
    layer += field(5, 0, EXTENT)
    return field(3, 2, layer)
