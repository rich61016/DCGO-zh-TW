# -*- coding: utf-8 -*-
"""建置繁體中文版遊戲資料:永遠讀「官方原檔」、寫「遊戲資料夾」,可重複執行。

官方原檔放在 _zh_tools/pristine/(由 zh_update.py 從官方更新伺服器下載並驗證雜湊);
未被中文化改動的檔案直接讀遊戲資料夾。物件一律依名稱尋找,不寫死編號,遊戲改版後也能套用。

用法: python build_zh.py [--dry-run]
環境變數: ZH_ORIG(官方原檔根目錄,預設 _zh_tools/pristine)、ZH_DEST(遊戲根目錄,預設 _zh_tools 的上一層)
"""
import collections
import json
import os
import re
import struct
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)

import meta_dump as md
import ttc_extract as TX
import zh_all
import zh_assets as A
import zh_tw
from unity_text import pack_str, read_str

DEST = A.DEST
DRY = "--dry-run" in sys.argv

ATLAS_SIZE = 2048
FONT_SIZE_FOR_METRICS = 16.0   # 與 Font 物件原本的 m_FontSize 一致

report = collections.OrderedDict()
CJK_FONT_PID = None            # 由 sharedassets0 依名稱找到(Font 'LiberationSans')


def log(file, key, n=1):
    report.setdefault(file, collections.Counter())[key] += n


def write_atomic(path, data):
    if DRY:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-zh"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------
# 建置單一序列化檔
# ----------------------------------------------------------------------------
def build_asset(fname, scripts, do_localize=True, do_scene=True, special=None):
    path = A.orig(fname)
    orig_bytes = open(path, "rb").read()
    f = A.load_file(path)
    externals = A.ext_names(f)
    gen_fid = 0 if fname == "sharedassets0.assets" else (externals.index("sharedassets0.assets") + 1
                                                         if "sharedassets0.assets" in externals else None)
    # GameObject → 元件類別
    go_classes = {}
    cls_of = {}
    for pid, o in f.objects.items():
        if o.type.name == "MonoBehaviour":
            raw = o.get_raw_data()
            fid, spid = struct.unpack_from("<iq", raw, 16)
            cls_of[pid] = scripts.get(spid, f"?{spid}")
    for pid, o in f.objects.items():
        if o.type.name == "GameObject":
            raw = o.get_raw_data()
            n = struct.unpack_from("<i", raw, 0)[0]
            comps = []
            for i in range(n):
                cfid, cpid = struct.unpack_from("<iq", raw, 4 + 12 * i)
                if cfid == 0 and cpid in cls_of:
                    comps.append(cls_of[cpid])
            go_classes[pid] = comps

    changed = {}   # pid → new raw

    for pid, o in f.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        cn = cls_of[pid]
        if cn not in ("LocalizeTMPro", "TextMeshProUGUI", "Text"):
            continue
        raw = o.get_raw_data()
        _, gopid = struct.unpack_from("<iq", raw, 0)

        if cn == "LocalizeTMPro" and do_localize:
            eng, off = read_str(raw, 88)
            jpn, off2 = read_str(raw, off)
            assert off2 == len(raw), (fname, pid, "LocalizeTMPro 版面不符")
            if not eng and not jpn:
                log(fname, "LocalizeTMPro 空白(程式動態設定)略過")
                continue
            if eng not in zh_tw.LOC:
                log(fname, "LocalizeTMPro 無翻譯(維持原文)")
                print(f"  [提醒] {fname} pid={pid} 介面文字沒有翻譯,維持原文: {eng!r}")
                continue
            zh = zh_tw.LOC[eng]
            ptrs = [raw[32 + 12 * i: 44 + 12 * i] for i in range(4)]   # TMP_ENG, TMP_JPN, Font_ENG, Font_JPN
            isnull = lambda b: struct.unpack("<iq", b) == (0, 0)
            fs_eng, fs_jpn = struct.unpack_from("<ii", raw, 80)
            sib = go_classes.get(gopid, [])
            kind = "TMP" if "TextMeshProUGUI" in sib else ("Text" if "Text" in sib else None)
            if kind == "TMP":
                if not isnull(ptrs[1]):
                    ptrs[0] = ptrs[1]               # 英文欄採用日文欄的 TMP 字型
            elif kind == "Text":
                # 舊式 Text 無法逐字後備,必須整個元件使用涵蓋完整的字型(英文欄、日文欄都指向它)
                ptrs[3] = struct.pack("<iq", gen_fid, CJK_FONT_PID)
                ptrs[2] = ptrs[3]
            else:
                log(fname, "LocalizeTMPro 同物件找不到文字元件")
                print(f"  [警告] {fname} pid={pid} 同物件找不到 TMP/Text: {sib}")
            if fs_jpn > 0:
                fs_eng = fs_jpn
            new = raw[:32] + b"".join(ptrs) + struct.pack("<ii", fs_eng, fs_jpn) + pack_str(zh) + pack_str(zh)
            changed[pid] = new
            log(fname, f"LocalizeTMPro 已翻譯({kind})")
            continue

        # 寫死的文字元件(不含被 LocalizeTMPro 接管的)
        if not do_scene:
            continue
        if "LocalizeTMPro" in go_classes.get(gopid, []):
            continue
        calls = struct.unpack_from("<i", raw, 84)[0]
        if calls != 0:
            continue
        if cn == "TextMeshProUGUI":
            text, end = read_str(raw, 88)
            if text in zh_tw.SCENE:
                zh = zh_tw.SCENE[text]
                changed[pid] = raw[:88] + pack_str(zh) + raw[end:]
                log(fname, "TMP 寫死文字已翻譯")
        else:  # Text
            text, end = read_str(raw, 144)
            assert end == len(raw), (fname, pid, "Text 版面不符")
            if text in zh_tw.SCENE:
                zh = zh_tw.SCENE[text]
                new = bytearray(raw[:144]) + pack_str(zh)
                if gen_fid is None:
                    raise RuntimeError(f"{fname} 找不到 sharedassets0 的外部參照")
                new[88:100] = struct.pack("<iq", gen_fid, CJK_FONT_PID)    # 舊式 Text:一律用涵蓋完整的字型
                log(fname, "Text 字型改為 PingFang TC")
                changed[pid] = bytes(new)
                log(fname, "Text 寫死文字已翻譯")

    # ---- 特殊補丁 ----
    if special:
        special(f, changed, externals)

    for pid, new in changed.items():
        f.objects[pid].set_raw_data(bytes(new))
    out = f.save() if changed else orig_bytes
    return orig_bytes, out, changed


# ----------------------------------------------------------------------------
# 特殊補丁:字型
# ----------------------------------------------------------------------------
FALLBACK_PID = None


def special_sharedassets0(f, changed, externals):
    o = f.objects[FALLBACK_PID]
    raw = bytearray(o.get_raw_data())
    assert A.mb_name(bytes(raw)) == A.FALLBACK_NAME, "後備字型名稱不符"
    assert bytes(raw[0x84:0x90]) == struct.pack("<iq", 0, CJK_FONT_PID), "來源字型參照位置不符(應指向 LiberationSans Font)"
    assert struct.unpack_from("<i", raw, 0x90)[0] == 1, "不是動態模式"
    atlas_fid, atlas_pid = struct.unpack_from("<iq", raw, 0x10c)
    assert atlas_fid == 0 and f.objects[atlas_pid].type.name == "Texture2D", "圖集貼圖參照位置不符"
    assert struct.unpack_from("<i", raw, 0x11c)[0] == 0 and struct.unpack_from("<i", raw, 0x120)[0] == 1, "旗標位置不符"
    struct.pack_into("<i", raw, 0x11c, 1)                        # 開啟多張圖集(原本關閉:512×512 只能放約 24 個中文字)
    # 對戰文字用到數千種中文字,把每張圖集由 512×512 放大為 2048×2048(每張約可放 400 字,減少換頁)
    assert struct.unpack_from("<4i", raw, 0x124 + 4)[0] == 1 and struct.unpack_from("<iiii", raw, 0x12c) == (0, 0, 511, 511), "空閒矩形位置不符"
    assert struct.unpack_from("<2i", raw, 0x1ac) == (512, 512), "圖集大小位置不符"
    struct.pack_into("<2i", raw, 0x134, ATLAS_SIZE - 1, ATLAS_SIZE - 1)
    struct.pack_into("<2i", raw, 0x1ac, ATLAS_SIZE, ATLAS_SIZE)
    changed[FALLBACK_PID] = bytes(raw)
    log("sharedassets0.assets", f"動態後備字型:開啟多張圖集、圖集 {ATLAS_SIZE}²")

    # LiberationSans Font 的內容換成 PingFang TC(後備字型的來源),並校正字高欄位
    fo = f.objects[CJK_FONT_PID]
    orig_raw = fo.get_raw_data()                                  # 注意:get_raw_data() 永遠回傳「原始檔」的位元組
    tt = fo.read_typetree()
    assert tt["m_Name"] == A.FONT_NAME and tt["m_FontSize"] == FONT_SIZE_FOR_METRICS
    # 真正的往返測試:不改欄位,以 save_typetree 的「回傳值」(而非 get_raw_data)與原始位元組比對
    assert fo.save_typetree(tt) == orig_raw, "Font 型別樹往返不一致,停止"
    font_bytes, family = A.cjk_font()                            # macOS:蘋方-繁;Windows:微軟正黑體(皆取自本機系統字型)
    asc, desc, lsp, _ = TX.hhea_metrics(font_bytes, FONT_SIZE_FOR_METRICS)
    tt["m_FontData"] = font_bytes
    tt["m_Ascent"], tt["m_Descent"], tt["m_LineSpacing"] = asc, desc, lsp
    tt["m_FontNames"] = [family]
    tt["m_KerningValues"] = []
    new_raw = fo.save_typetree(tt)                               # 回傳值才是新資料
    assert new_raw != orig_raw and len(new_raw) > len(orig_raw) + 1_000_000, "Font 資料沒有真的改變"
    changed[CJK_FONT_PID] = new_raw
    log("sharedassets0.assets", f"Font {A.FONT_NAME} 內容換成 {family}({len(font_bytes):,} bytes)")


def special_resources(f, changed, externals):
    sa0_fid = externals.index("sharedassets0.assets") + 1
    tp = A.find_mb(f, A.TMP_SETTINGS_NAME)
    raw = f.objects[tp].get_raw_data()
    dfid, _ = struct.unpack_from("<iq", raw, 0x50)
    assert dfid == sa0_fid, "預設字型參照位置不符"
    assert struct.unpack_from("<i", raw, 0x98)[0] == 0, "全域後備清單不是空的"
    assert struct.unpack_from("<i", raw, 0x9c)[0] == 1, "matchMaterialPreset 位置不符"
    new = raw[:0x98] + struct.pack("<i", 1) + struct.pack("<iq", sa0_fid, FALLBACK_PID) + raw[0x9c:]
    assert len(new) == len(raw) + 12
    changed[tp] = new
    log("resources.assets", "TMP 全域後備字型清單:加入動態後備")


# ----------------------------------------------------------------------------
# 卡片資料庫:卡名、特徵、效果文字寫進日文欄位(遊戲規則只讀英文欄位)
# ----------------------------------------------------------------------------
DIGIBURST_JPN = re.compile("デジバースト[0-9]")        # DataBase.DigiBurstJpnRegex
DIGIBURST_ENG = re.compile("Digi-Burst [0-9]")         # DataBase.DigiBurstEngRegex
EFFECT_FIELDS = (("EffectDiscription", "effect"), ("InheritedEffectDiscription", "inherited"),
                 ("SecurityEffectDiscription", "security"))


def has_digiburst(jpn_effect, eng_effect):
    """CardSource.HasDigiBurst 唯一讀日文欄位的規則判斷:日文欄位比對日文樣式,之後一定再比對英文欄位。"""
    return bool(jpn_effect and DIGIBURST_JPN.search(jpn_effect)) or bool(eng_effect and DIGIBURST_ENG.search(eng_effect))


def card_jpn(c, text):
    """一張卡的日文欄位要寫成什麼。官方簡中有資料就用繁中;沒有就保留日文;日文也沒有就用英文(原本是空白)。"""
    rec = text["cards"].get(c["CardID"])
    traits = text.get("traits", {})
    j = {"CardName_JPN": (rec or {}).get("name") or c["CardName_JPN"] or c["CardName_ENG"]}
    for fld, key in (("Form", "form"), ("Attribute", "attribute"), ("Type", "type")):
        eng, jp = c[f"{fld}_ENG"], c[f"{fld}_JPN"]
        own = (rec or {}).get(key) or []
        if own and len(own) == len(eng):
            j[f"{fld}_JPN"] = list(own)
        else:
            # 詳細資料面板以英文欄位的數量為準逐項讀日文欄位,長度必須相同(原版缺日文資料時會在這裡出錯)
            j[f"{fld}_JPN"] = [traits.get(key, {}).get(e) or (jp[i] if i < len(jp) and jp[i] else e)
                               for i, e in enumerate(eng)]
    for fld, key in EFFECT_FIELDS:
        jf, ef = f"{fld}_JPN", f"{fld}_ENG"
        zh = (rec or {}).get(key) or ""
        if zh:
            j[jf] = zh
        elif rec and not c[ef].strip():
            j[jf] = ""
        else:
            j[jf] = c[jf] or c[ef]
    if has_digiburst(j["EffectDiscription_JPN"], c["EffectDiscription_ENG"]) != \
            has_digiburst(c["EffectDiscription_JPN"], c["EffectDiscription_ENG"]):
        j["EffectDiscription_JPN"] = c["EffectDiscription_JPN"]          # 會改變規則判斷:維持原文
        log("sharedassets2.assets", "效果文字會影響數碼爆發判斷,維持原文")
    return j


def build_card_db(scripts):
    import carddb
    fname = "sharedassets2.assets"
    path = A.orig(fname)
    orig_bytes = open(path, "rb").read()
    try:
        with open(A.CARD_TEXT, encoding="utf-8") as fh:
            text = json.load(fh)
    except FileNotFoundError:
        print("  [資訊] 沒有卡片文字資料(cards/card_text_zh.json),卡片資料庫維持原文。")
        log(fname, "沒有卡片文字資料,維持原文")
        return orig_bytes, orig_bytes, {}
    f = A.load_file(path)
    changed = {}
    for pid, o in f.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        _, spid = struct.unpack_from("<iq", raw, 16)
        if scripts.get(spid) != "CEntity_Base":
            continue
        c = carddb.parse_entity(raw)
        j = card_jpn(c, text)
        diff = {k: v for k, v in j.items() if v != c[k]}
        log(fname, "卡片(全部)")
        if c["CardID"] in text["cards"]:
            log(fname, "卡片:官方簡中轉繁中")
        elif c["CardName_JPN"]:
            log(fname, "卡片:官方簡中沒有,保留日文")
        else:
            log(fname, "卡片:官方簡中與日文都沒有,改用英文(原本空白)")
        if diff:
            changed[pid] = carddb.patch_entity(raw, diff)
    for pid, new in changed.items():
        f.objects[pid].set_raw_data(new)
    out = f.save() if changed else orig_bytes
    return orig_bytes, out, changed


# ----------------------------------------------------------------------------
# metadata
# ----------------------------------------------------------------------------
def build_metadata():
    src = A.orig("il2cpp_data/Metadata/global-metadata.dat")
    buf = open(src, "rb").read()
    version, sec = md.parse_header(buf)
    assert version == 31, f"metadata 版本 {version} 不是 31,需要更新工具"
    t_off, t_size = sec["stringLiteral"]
    d_off, d_size = sec["stringLiteralData"]
    assert d_off == t_off + t_size
    n = t_size // 8
    entries = [struct.unpack_from("<Ii", buf, t_off + 8 * i) for i in range(n)]
    strings = [bytes(buf[d_off + di: d_off + di + ln]) for ln, di in entries]
    appended = bytearray()
    new_entries = list(entries)
    applied = {}
    for i, s in enumerate(strings):
        try:
            k = s.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if k in zh_all.ALL:
            zh = zh_all.ALL[k].encode("utf-8")
            new_entries[i] = (len(zh), d_size + len(appended))
            appended += zh
            applied[k] = i
    missing = [k for k in zh_all.ALL if k not in applied]
    if missing:
        # 新版本移除或改寫了這些原文:對應的譯文自然用不到(不影響其他翻譯)
        print(f"  [資訊] 翻譯表中有 {len(missing)} 句原文已不在這個版本中(已移除或改寫),略過。例如: {[m[:50] for m in missing[:3]]}")
        log("global-metadata.dat", "翻譯表中已不存在於此版本的原文", len(missing))
    appended += b"\x00" * ((-len(appended)) % 4)
    delta = len(appended)
    end_of_data = d_off + d_size

    header = bytearray(buf[:t_off])
    # 更新 stringLiteralData 大小;其後所有區段位移 += delta
    for idx, name in enumerate(md.SECTIONS):
        off, size = struct.unpack_from("<ii", header, 8 + idx * 8)
        if name == "stringLiteralData":
            struct.pack_into("<ii", header, 8 + idx * 8, off, size + delta)
        elif off >= end_of_data:
            struct.pack_into("<ii", header, 8 + idx * 8, off + delta, size)
    table = b"".join(struct.pack("<Ii", ln, di) for ln, di in new_entries)
    out = bytes(header) + table + buf[d_off:end_of_data] + bytes(appended) + buf[end_of_data:]
    assert len(out) == len(buf) + delta
    return buf, out, applied, delta, missing


# ----------------------------------------------------------------------------
def main():
    global CJK_FONT_PID, FALLBACK_PID
    scripts = A.script_map()
    f0 = A.load_file(A.orig("sharedassets0.assets"))
    CJK_FONT_PID = A.find_named(f0, "Font", A.FONT_NAME)
    FALLBACK_PID = A.find_mb(f0, A.FALLBACK_NAME)
    del f0
    plan = [
        ("sharedassets0.assets", dict(special=special_sharedassets0)),
        ("resources.assets", dict(do_localize=False, do_scene=False, special=special_resources)),
        ("level0", {}),
        ("level1", {}),
        ("sharedassets1.assets", {}),
    ]
    outputs = {}
    for fname, kw in plan:
        orig, out, changed = build_asset(fname, scripts, **kw)
        print(f"{fname:24s} 改動物件 {len(changed):5d}  {len(orig):>11,} → {len(out):>11,} bytes")
        outputs[fname] = out
    orig, out, changed = build_card_db(scripts)
    print(f"{'sharedassets2.assets':24s} 改動物件 {len(changed):5d}  {len(orig):>11,} → {len(out):>11,} bytes(卡片資料庫)")
    outputs["sharedassets2.assets"] = out

    borig, bout, applied, delta, missing = build_metadata()
    print(f"{'global-metadata.dat':24s} 取代字串 {len(applied):5d}  {len(borig):>11,} → {len(bout):>11,} bytes (+{delta})")
    # 全部建置成功後才寫入(避免只寫了一半)
    for fname, out in outputs.items():
        write_atomic(os.path.join(DEST, fname), out)
    write_atomic(os.path.join(DEST, "il2cpp_data/Metadata/global-metadata.dat"), bout)

    print("\n=== 統計 ===")
    for fname, c in report.items():
        print(f"[{fname}]")
        for k, v in c.most_common():
            print(f"   {v:5d}  {k}")
    rep = {k: dict(v) for k, v in report.items()}
    rep["_metadata"] = {"applied": len(applied), "missing_in_version": missing}
    json.dump(rep, open(f"{S}/build_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + ("(乾跑模式:未寫入任何檔案)" if DRY else "已寫入遊戲資料夾。"))


if __name__ == "__main__":
    main()
