"""極簡 TrueType/OpenType 解析:取字型名稱、字形數,並檢查 cmap 是否含指定碼位(不依賴 fontTools)。"""
import struct


def _tables(b, base=0):
    if b[base:base + 4] == b"ttcf":
        raise ValueError("ttc")
    num = struct.unpack_from(">H", b, base + 4)[0]
    t = {}
    for i in range(num):
        tag, cs, off, ln = struct.unpack_from(">4sIII", b, base + 12 + i * 16)
        t[tag.decode("latin1")] = (off, ln)
    return t


def font_names(b):
    t = _tables(b)
    if "name" not in t:
        return {}
    off, ln = t["name"]
    fmt, count, str_off = struct.unpack_from(">HHH", b, off)
    out = {}
    for i in range(count):
        pid, eid, lid, nid, length, o = struct.unpack_from(">6H", b, off + 6 + i * 12)
        raw = b[off + str_off + o: off + str_off + o + length]
        try:
            s = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("mac_roman")
        except Exception:
            continue
        if nid in (1, 2, 4, 6) and nid not in out:
            out[nid] = s
    return out


def num_glyphs(b):
    t = _tables(b)
    if "maxp" in t:
        return struct.unpack_from(">H", b, t["maxp"][0] + 4)[0]
    return None


def cmap_codepoints(b):
    """回傳 Unicode cmap 所涵蓋的碼位集合。"""
    t = _tables(b)
    if "cmap" not in t:
        return set()
    base, _ = t["cmap"]
    ver, n = struct.unpack_from(">HH", b, base)
    best = None
    for i in range(n):
        pid, eid, off = struct.unpack_from(">HHI", b, base + 4 + i * 8)
        fmt = struct.unpack_from(">H", b, base + off)[0]
        score = 0
        if (pid, eid) == (3, 10) and fmt == 12:
            score = 3
        elif pid == 0 and fmt == 12:
            score = 3
        elif (pid, eid) == (3, 1) and fmt == 4:
            score = 2
        elif pid == 0 and fmt == 4:
            score = 2
        if score and (best is None or score > best[0]):
            best = (score, base + off, fmt)
    if not best:
        return set()
    _, o, fmt = best
    cps = set()
    if fmt == 12:
        ngroups = struct.unpack_from(">I", b, o + 12)[0]
        for g in range(ngroups):
            s, e, gid = struct.unpack_from(">III", b, o + 16 + g * 12)
            if e - s > 200000:
                continue
            cps.update(range(s, e + 1))
    elif fmt == 4:
        segx2 = struct.unpack_from(">H", b, o + 6)[0]
        seg = segx2 // 2
        ends = struct.unpack_from(f">{seg}H", b, o + 14)
        starts = struct.unpack_from(f">{seg}H", b, o + 16 + segx2)
        for s, e in zip(starts, ends):
            if s == 0xFFFF:
                continue
            cps.update(range(s, e + 1))
    return cps


def sniff(b):
    return b[:4]
