# -*- coding: utf-8 -*-
"""獨立驗證:不信任建置程式,重新讀取遊戲資料夾的輸出檔,逐項與「官方原檔」比對。

檢查:
  1. 未被中文化改動的檔案,與官方版本(zh_state.json 記錄的 SHA-1)完全相同;pristine/ 的官方原檔也正確。
  2. 改動過的序列化檔:物件集合、型別、Unity 版本、外部參照都不變;只有預期類別的物件有差異。
  3. 介面雙語元件:有翻譯的都已是中文且兩欄一致;沒有翻譯的維持原文。
  4. 字型:LiberationSans 換成 PingFang TC、動態後備字型設定、TMP 全域後備清單。
  5. metadata:區段連續、字串常值數不變、取代內容正確、其他區段逐位元組相同、譯文可安全當格式字串。
  6. 譯文用到的字元都在 PingFang TC 裡。
  7. 卡片資料庫:只有日文欄位改變;規則程式讀的英文欄位與數碼爆發判斷不變;詳細資料面板不會因欄位數量出錯。
"""
import base64
import collections
import hashlib
import json
import os
import re
import struct
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)

import meta_dump as md
import ttc_extract as TX
import ttf_util as T
import zh_all
import zh_assets as A
import zh_tw
from unity_text import read_str

STATE = os.environ.get("ZH_STATE", os.path.join(S, "zh_state.json"))
DEST = A.DEST
GAME = os.path.dirname(DEST)
fail = 0
warn = 0


def ok(cond, msg):
    global fail
    print(("  ✓ " if cond else "  ✗ 失敗: ") + msg)
    if not cond:
        fail += 1


def note(msg):
    global warn
    warn += 1
    print("  ! 提醒: " + msg)


def sha1b64(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode().rstrip("=")


# ---------------------------------------------------------------- 1. 官方檔案完整性
print("== 1. 官方檔案完整性 ==")
try:
    state = json.load(open(STATE, encoding="utf-8"))
except Exception:
    state = {}
files = state.get("files") or {}
if not files:
    note("沒有官方檔案清單(zh_state.json),略過此項")
else:
    bad = []
    for rel, h in files.items():
        if rel.startswith("DCGO_Data/") and rel[len("DCGO_Data/"):] in A.LOCALIZED:
            p = os.path.join(A.ORIG_ROOT, rel)          # 中文化改動的檔案:比對 pristine 官方原檔
        else:
            p = os.path.join(GAME, rel)
        if not os.path.exists(p) or sha1b64(p) != h:
            bad.append(rel)
    ok(not bad, f"{state.get('version')} 版的 {len(files)} 個官方檔案全部正確" + (f";不符: {bad[:5]}" if bad else ""))

# ---------------------------------------------------------------- 2. 序列化檔逐物件比對
print("\n== 2. 序列化檔逐物件比對 ==")
scripts = A.script_map()
expect_cls = {"LocalizeTMPro", "TextMeshProUGUI", "Text", "TMP_FontAsset", "TMP_Settings", "Font", "CEntity_Base"}
loaded = {}
for fname in ["sharedassets0.assets", "resources.assets", "level0", "level1", "sharedassets1.assets",
              "sharedassets2.assets"]:
    print(f"-- {fname}")
    fo = A.load_file(A.orig(fname))
    fn_ = A.load_file(os.path.join(DEST, fname))
    loaded[fname] = (fo, fn_)
    ok(set(fo.objects) == set(fn_.objects), f"物件集合相同({len(fo.objects)} 個)")
    ok(all(fo.objects[p].type.name == fn_.objects[p].type.name for p in fo.objects), "每個物件的型別相同")
    ok(fo.unity_version == fn_.unity_version, f"Unity 版本相同({fo.unity_version})")
    ok(A.ext_names(fo) == A.ext_names(fn_), "外部參照清單相同")
    raw = open(os.path.join(DEST, fname), "rb").read()
    hdr_fs = struct.unpack_from(">q", raw, 24)[0]
    ok(hdr_fs == len(raw), f"檔頭 file_size 與實際大小一致({len(raw):,})")
    diffs = [p for p in fo.objects if fo.objects[p].get_raw_data() != fn_.objects[p].get_raw_data()]
    classes = collections.Counter()
    for p in diffs:
        o = fn_.objects[p]
        if o.type.name == "MonoBehaviour":
            _, spid = struct.unpack_from("<iq", o.get_raw_data(), 16)
            classes[scripts.get(spid, f"?{spid}")] += 1
        else:
            classes[o.type.name] += 1
    ok(set(classes) <= expect_cls, f"有差異的物件 {len(diffs)} 個,類別 {dict(classes)}(皆在預期範圍)")

# ---------------------------------------------------------------- 3. 介面雙語元件
print("\n== 3. 介面雙語元件 ==")
cjk = re.compile(r"[一-鿿]")
tot, done, untrans, bad = 0, 0, [], []
for fname in ["level0", "level1", "sharedassets0.assets", "sharedassets1.assets"]:
    fo, fn_ = loaded[fname]
    for pid, o in fo.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        r0 = o.get_raw_data()
        _, spid = struct.unpack_from("<iq", r0, 16)
        if scripts.get(spid) != "LocalizeTMPro":
            continue
        eng, off = read_str(r0, 88)
        jpn, _ = read_str(r0, off)
        if not eng and not jpn:
            continue
        tot += 1
        r1 = fn_.objects[pid].get_raw_data()
        e1, off1 = read_str(r1, 88)
        j1, _ = read_str(r1, off1)
        if eng in zh_tw.LOC:
            if e1 == j1 == zh_tw.LOC[eng] and cjk.search(e1):
                done += 1
            else:
                bad.append((fname, pid, eng))
        else:
            untrans.append(eng)
            if r1 != r0:
                bad.append((fname, pid, "無翻譯卻被改動"))
ok(not bad, f"有內容的雙語元件 {tot} 個,已翻成中文 {done} 個" + (f";異常 {bad[:3]}" if bad else ""))
if untrans:
    note(f"{len(untrans)} 個介面文字沒有翻譯、維持原文(多半是新版本新增的介面): {untrans[:5]}")

# ---------------------------------------------------------------- 4. 字型設定
print("\n== 4. 字型設定 ==")
fo0, f0 = loaded["sharedassets0.assets"]
font_pid = A.find_named(fo0, "Font", A.FONT_NAME)
fb_pid = A.find_mb(fo0, A.FALLBACK_NAME)
raw = f0.objects[fb_pid].get_raw_data()
ok(struct.unpack_from("<iq", raw, 0x84) == (0, font_pid), f"後備字型來源仍為 {A.FONT_NAME}(其內容已換成 PingFang TC)")
ok(struct.unpack_from("<i", raw, 0x90)[0] == 1, "仍為動態模式")
ok(struct.unpack_from("<i", raw, 0x11c)[0] == 1, "多張圖集已開啟")
ok(struct.unpack_from("<2i", raw, 0x1ac) == (2048, 2048) and struct.unpack_from("<iiii", raw, 0x12c) == (0, 0, 2047, 2047), "圖集大小 2048² 且空閒矩形同步")
raw0 = fo0.objects[fb_pid].get_raw_data()
ok(raw[0x10c:0x118] == raw0[0x10c:0x118], "圖集貼圖參照不變")
fnt = f0.objects[font_pid].read()
fdata = bytes(fnt.m_FontData)
want_font, want_family = A.cjk_font()
ok(fdata[:4] in (b"OTTO", b"\x00\x01\x00\x00", b"true") and fdata == want_font,
   f"{A.FONT_NAME} 內容 = 本機系統字型 {want_family}({len(fdata):,} bytes)")
asc, desc, lsp, _ = TX.hhea_metrics(fdata, 16.0)
ok(list(fnt.m_FontNames) == [want_family] and abs(fnt.m_Ascent - asc) < 0.01 and abs(fnt.m_Descent - desc) < 0.01,
   f"字高 asc={fnt.m_Ascent:.2f} desc={fnt.m_Descent:.2f} line={fnt.m_LineSpacing:.2f}")
ok(len(fnt.m_KerningValues) == 0, "舊字型的字距表已清空")
other_fonts_same = all(f0.objects[p].get_raw_data() == fo0.objects[p].get_raw_data()
                       for p, o in fo0.objects.items() if o.type.name == "Font" and p != font_pid)
ok(other_fonts_same, "其他字型保持不動")
ro, rn = loaded["resources.assets"]
tp = A.find_mb(ro, A.TMP_SETTINGS_NAME)
sa0_fid = A.ext_names(ro).index("sharedassets0.assets") + 1
rs0 = ro.objects[tp].get_raw_data()
rs = rn.objects[tp].get_raw_data()
ok(struct.unpack_from("<i", rs, 0x98)[0] == 1 and struct.unpack_from("<iq", rs, 0x9c) == (sa0_fid, fb_pid), f"TMP Settings 全域後備清單 = [sharedassets0:{fb_pid}]")
ok(struct.unpack_from("<i", rs, 0xa8)[0] == 1, "matchMaterialPreset 仍為 1(位置已後移 12 bytes)")
ok(len(rs) == len(rs0) + 12 and rs[:0x98] == rs0[:0x98] and rs[0xa8:] == rs0[0x9c:], f"TMP Settings 其餘內容不變(長度 {len(rs0)} → {len(rs)})")

# ---------------------------------------------------------------- 5. metadata
print("\n== 5. metadata ==")
bo = open(A.orig("il2cpp_data/Metadata/global-metadata.dat"), "rb").read()
bn = open(os.path.join(DEST, "il2cpp_data/Metadata/global-metadata.dat"), "rb").read()
vo, so = md.parse_header(bo)
vn, sn = md.parse_header(bn)
ok(vo == vn == 31 and bn[:4] == bo[:4], "sanity 與版本相同")
names_ = md.SECTIONS
cont = all(sn[names_[i]][0] + sn[names_[i]][1] == sn[names_[i + 1]][0] for i in range(len(names_) - 1))
ok(cont, "新檔各區段首尾相接")
ok(sn[names_[-1]][0] + sn[names_[-1]][1] == len(bn), "最後區段結尾 = 檔案大小")
delta = sn["stringLiteralData"][1] - so["stringLiteralData"][1]
ok(delta % 4 == 0 and delta >= 0, f"字串資料區增加 {delta} bytes(4 位元組對齊)")
lo = md.literals(bo, so)
ln = md.literals(bn, sn)
ok(len(lo) == len(ln), f"字串常值總數不變 {len(lo):,}")
present = set()
changed, wrong = 0, []
for (i, l1, d1, r1), (j, l2, d2, r2) in zip(lo, ln):
    try:
        k = r1.decode("utf-8")
    except UnicodeDecodeError:
        k = None
    if k is not None and k in zh_all.ALL:
        present.add(k)
        changed += 1
        if r2.decode("utf-8") != zh_all.ALL[k]:
            wrong.append(k)
    elif r1 != r2:
        wrong.append(k or f"#{i}")
ok(not wrong, f"已取代 {changed:,} 筆且內容正確;其餘 {len(lo) - changed:,} 筆完全不變" + (f";異常 {wrong[:3]}" if wrong else ""))
missing = [k for k in zh_all.ALL if k not in present]
if missing:
    note(f"翻譯表有 {len(missing)} 句原文不在這個版本中(已被移除或改寫),不影響遊戲")
same_secs = True
for name in names_:
    if name in ("stringLiteral", "stringLiteralData"):
        continue
    oo, os_ = so[name]
    no, ns = sn[name]
    if os_ != ns or bo[oo:oo + os_] != bn[no:no + ns]:
        same_secs = False
        print("    區段不同:", name)
ok(same_secs, f"其餘 {len(names_) - 2} 個 metadata 區段內容逐位元組相同(僅位移改變)")
bad_fmt = []
for k in present:
    v = zh_all.ALL[k]
    ho = {int(x) for x in re.findall(r"\{(\d+)(?::[^}]*)?\}", k)}
    hv = {int(x) for x in re.findall(r"\{(\d+)(?::[^}]*)?\}", v)}
    if not hv <= ho:
        bad_fmt.append((k[:40], "多出格式洞"))
        continue
    if ho:
        try:
            v.format(*(["a"] * (max(ho) + 1)))
        except Exception as e:
            bad_fmt.append((k[:40], str(e)))
    elif re.sub(r"\{\{|\}\}", "", v).count("{") != re.sub(r"\{\{|\}\}", "", k).count("{"):
        bad_fmt.append((k[:40], "多出大括號"))
ok(not bad_fmt, f"所有譯文可安全作為格式字串{(' ' + str(bad_fmt[:3])) if bad_fmt else ''}")

# ---------------------------------------------------------------- 6. 字元涵蓋
print(f"\n== 6. 譯文用到的字元是否都在 {want_family} 裡 ==")
allchars = set()
for v in list(zh_tw.LOC.values()) + list(zh_tw.SCENE.values()) + [zh_all.ALL[k] for k in present]:
    allchars |= {c for c in v if ord(c) > 127 and not c.isspace() and not (0xE000 <= ord(c) <= 0xF8FF)}   # 私用區字元只拿來讓 Replace 比對失效,不會顯示
fcps = T.cmap_codepoints(fdata)
miss = sorted(c for c in allchars if ord(c) not in fcps)
ok(not miss, f"譯文共用到 {len(allchars)} 種非 ASCII 字元,全部涵蓋" + (f";缺: {''.join(miss)}" if miss else ""))

# ---------------------------------------------------------------- 7. 卡片資料庫
print("\n== 7. 卡片資料庫(卡名、特徵、效果文字寫在日文欄位) ==")
import carddb  # noqa: E402

DB_JP = re.compile("デジバースト[0-9]")     # DataBase.DigiBurstJpnRegex
DB_EN = re.compile("Digi-Burst [0-9]")      # DataBase.DigiBurstEngRegex


def digiburst(c):
    return bool(c["EffectDiscription_JPN"] and DB_JP.search(c["EffectDiscription_JPN"])) or \
        bool(c["EffectDiscription_ENG"] and DB_EN.search(c["EffectDiscription_ENG"]))


try:
    card_text = json.load(open(A.CARD_TEXT, encoding="utf-8"))
except FileNotFoundError:
    card_text = None
    note("沒有卡片文字資料(cards/card_text_zh.json),卡片資料庫應維持原文")
fo2, fn2 = loaded["sharedassets2.assets"]
n_cards, bad_other, bad_len, bad_burst, blank, zh_cnt, mism = 0, [], [], [], [], 0, []
card_chars = set()
for pid, o in fo2.objects.items():
    if o.type.name != "MonoBehaviour":
        continue
    r0 = o.get_raw_data()
    _, spid = struct.unpack_from("<iq", r0, 16)
    if scripts.get(spid) != "CEntity_Base":
        continue
    a = carddb.parse_entity(r0)
    b = carddb.parse_entity(fn2.objects[pid].get_raw_data())
    n_cards += 1
    if any(a[k] != b[k] for k in a if k not in carddb.JPN_FIELDS):
        bad_other.append(a["CardSpriteName"])
    if any(len(b[f"{k}_JPN"]) < len(b[f"{k}_ENG"]) for k in ("Form", "Attribute")):
        bad_len.append(a["CardSpriteName"])
    if digiburst(a) != digiburst(b):
        bad_burst.append(a["CardSpriteName"])
    if b["CardName_ENG"] and not b["CardName_JPN"]:
        blank.append(a["CardSpriteName"])
    if card_text is None:
        if r0 != fn2.objects[pid].get_raw_data():
            bad_other.append(a["CardSpriteName"] + "(沒有卡片文字資料卻被改動)")
        continue
    rec = card_text["cards"].get(b["CardID"])
    if rec:
        zh_cnt += 1
        if rec.get("name") and b["CardName_JPN"] != rec["name"]:
            mism.append((b["CardSpriteName"], "卡名"))
        if rec.get("effect") and b["EffectDiscription_JPN"] != rec["effect"] and not digiburst(a):
            mism.append((b["CardSpriteName"], "效果"))
    for k in carddb.JPN_FIELDS:
        if b[k] == a[k]:
            continue                          # 保留的原文(日文)由遊戲原本的日文字型顯示
        v = b[k] if isinstance(b[k], list) else [b[k]]
        for s in v:
            card_chars |= {ch for ch in s if ord(ch) > 127 and not ch.isspace()}
ok(n_cards > 1000 and not bad_other, f"{n_cards} 張卡:英文欄位與其他資料(規則程式使用的部分)完全不變"
   + (f";異常 {bad_other[:3]}" if bad_other else ""))
ok(not bad_len, "形態/屬性的日文欄位數量不少於英文欄位(詳細資料面板逐項讀取,不會出錯)" + (f";異常 {bad_len[:3]}" if bad_len else ""))
ok(not bad_burst, "唯一讀日文欄位的規則判斷(數碼爆發)結果與原版相同" + (f";不同 {bad_burst[:3]}" if bad_burst else ""))
ok(not blank, "沒有空白的卡名" + (f";空白 {blank[:3]}" if blank else ""))
if card_text is not None:
    ok(not mism, f"{zh_cnt} 張卡的中文卡名、效果與 card_text_zh.json 一致" + (f";不符 {mism[:3]}" if mism else ""))
    miss2 = sorted(c for c in card_chars if ord(c) not in fcps and not (0xE000 <= ord(c) <= 0xF8FF))
    ok(not miss2, f"卡片文字共用到 {len(card_chars)} 種非 ASCII 字元,{want_family} 全部涵蓋" + (f";缺: {''.join(miss2)}" if miss2 else ""))

print(f"\n{'全部通過 ✓' if fail == 0 else f'有 {fail} 項失敗 ✗'}" + (f"(另有 {warn} 項提醒)" if warn else ""))
sys.exit(1 if fail else 0)
