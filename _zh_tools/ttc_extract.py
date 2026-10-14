# -*- coding: utf-8 -*-
"""從 TTC 抽出單一字型面,輸出獨立的 OpenType/TrueType 檔(不依賴 fontTools)。"""
import io
import os
import struct
import sys

PINGFANG = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"


def _csum(data):
    data = data + b"\0" * ((-len(data)) % 4)
    return sum(struct.unpack(f">{len(data)//4}I", data)) & 0xFFFFFFFF


def extract_face(ttc_path, index):
    b = open(ttc_path, "rb").read()
    assert b[:4] == b"ttcf", "不是 TTC"
    n = struct.unpack_from(">I", b, 8)[0]
    offs = struct.unpack_from(f">{n}I", b, 12)
    off = offs[index]
    sfnt = b[off:off + 4]
    num = struct.unpack_from(">H", b, off + 4)[0]
    recs = []
    for i in range(num):
        tag, cs, o, ln = struct.unpack_from(">4sIII", b, off + 12 + i * 16)
        recs.append((tag, bytearray(b[o:o + ln])))
    recs.sort(key=lambda r: r[0])
    # head.checkSumAdjustment 先歸零
    for tag, data in recs:
        if tag == b"head":
            data[8:12] = b"\0\0\0\0"
    # 目錄參數
    mx = 1
    while mx * 2 <= num:
        mx *= 2
    search_range = mx * 16
    entry_selector = mx.bit_length() - 1
    range_shift = num * 16 - search_range
    header = sfnt + struct.pack(">HHHH", num, search_range, entry_selector, range_shift)
    pos = 12 + 16 * num
    directory = b""
    body = b""
    head_pos = None
    for tag, data in recs:
        d = bytes(data)
        pad = (-len(d)) % 4
        directory += struct.pack(">4sIII", tag, _csum(d), pos, len(d))
        if tag == b"head":
            head_pos = pos
        body += d + b"\0" * pad
        pos += len(d) + pad
    font = bytearray(header + directory + body)
    # 全檔校驗和 → head.checkSumAdjustment
    adj = (0xB1B0AFBA - _csum(bytes(font))) & 0xFFFFFFFF
    font[head_pos + 8:head_pos + 12] = struct.pack(">I", adj)
    return bytes(font)


def hhea_metrics(font_bytes, size=16.0):
    """回傳 Unity Font 物件用的 (ascent, descent, lineSpacing),以 hhea × 字級 計。"""
    num = struct.unpack_from(">H", font_bytes, 4)[0]
    tb = {}
    for i in range(num):
        tag, cs, o, ln = struct.unpack_from(">4sIII", font_bytes, 12 + i * 16)
        tb[tag] = (o, ln)
    ho = tb[b"hhea"][0]
    asc, desc, gap = struct.unpack_from(">hhh", font_bytes, ho + 4)
    upem = struct.unpack_from(">H", font_bytes, tb[b"head"][0] + 18)[0]
    k = size / upem
    return asc * k, desc * k, (asc - desc + gap) * k, (asc, desc, gap, upem)


if __name__ == "__main__":
    import hashlib
    from PIL import Image, ImageChops, ImageDraw, ImageFont
    S = os.path.dirname(os.path.abspath(__file__))
    font = extract_face(PINGFANG, 2)   # PingFang TC Regular
    open(f"{S}/PingFangTC-Regular.otf", "wb").write(font)
    print("已輸出 PingFangTC-Regular.otf", len(font), "bytes", hashlib.sha256(font).hexdigest()[:12])
    a, d, ls, raw = hhea_metrics(font)
    print("hhea(asc,desc,gap,upem) =", raw, " → Unity m_Ascent/m_Descent/m_LineSpacing =", round(a, 4), round(d, 4), round(ls, 4))
    # 以 FreeType 開啟拆出的字型,與直接從 TTC 載入的版本逐像素比對
    text = "牌組 對戰 啟用 查看 內存值 進化源 數碼寶貝 DP 5000 Lv.4 請選擇要消滅的卡片。"
    imgs = []
    for src in (ImageFont.truetype(io.BytesIO(font), 40), ImageFont.truetype(PINGFANG, 40, index=2)):
        im = Image.new("L", (1500, 70), 255)
        ImageDraw.Draw(im).text((10, 8), text, fill=0, font=src)
        imgs.append(im)
    diff = ImageChops.difference(imgs[0], imgs[1]).getbbox()
    print("拆出的字型 vs 原 TTC 載入:渲染像素", "完全一致 ✓" if diff is None else f"有差異 ✗ {diff}")
    imgs[0].save(f"{S}/pingfang_test.png")
