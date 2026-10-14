# -*- coding: utf-8 -*-
"""補充驗證:被翻譯的舊式 Text 的字型參照、以及輸出檔再存回的穩定性。"""
import os
import re
import struct
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import UnityPy
from unity_text import Project

DEST = os.path.join(os.path.dirname(S), "Game", "DCGO_Data")
fail = 0


def ok(c, m):
    global fail
    print(("  ✓ " if c else "  ✗ 失敗: ") + m)
    fail += (not c)


P = Project(DEST)
cjk = re.compile(r"[぀-ヿ一-鿿]")
print("== 被翻譯的舊式 Text / 雙語 Text 的字型是否都解析到 sharedassets0 的 Font 311 ==")
for fname in ["level0", "level1", "sharedassets1.assets"]:
    f = P.files[fname]
    ex = [os.path.basename(str(getattr(e, "name", e))) for e in f.externals]
    n = bad = 0
    bad_ex = []
    for pid, o in f.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        cn = P.cls_of(o)
        raw = o.get_raw_data()
        if cn == "Text":
            s, end = None, None
            try:
                from unity_text import read_str
                s, end = read_str(raw, 144)
            except Exception:
                continue
            if not cjk.search(s):
                continue
            fid, fpid = struct.unpack_from("<iq", raw, 88)
            tgt = (ex[fid - 1] if fid else fname, fpid)
            n += 1
            if tgt != ("sharedassets0.assets", 311):
                bad += 1
                bad_ex.append((pid, s, tgt))
        elif cn == "LocalizeTMPro":
            from unity_text import read_str
            eng, off = read_str(raw, 88)
            if not cjk.search(eng):
                continue
            # 只檢查 Text 型(字型欄 56/68 非空者)
            for off_ in (56, 68):
                fid, fpid = struct.unpack_from("<iq", raw, off_)
                if (fid, fpid) == (0, 0):
                    continue
                tgt = (ex[fid - 1] if fid else fname, fpid)
                n += 1
                if tgt != ("sharedassets0.assets", 311):
                    bad += 1
                    bad_ex.append((pid, eng, tgt))
    ok(bad == 0 and n > 0, f"{fname}: 檢查 {n} 個字型參照,不符 {bad} {bad_ex[:3] if bad_ex else ''}")

print("\n== 輸出檔再讀取→存回是否穩定(標準格式) ==")
for fname in ["sharedassets0.assets", "resources.assets", "level0", "level1", "sharedassets1.assets"]:
    path = os.path.join(DEST, fname)
    cur = open(path, "rb").read()
    env = UnityPy.load(path)
    out = list(env.files.values())[0].save()
    ok(out == cur, f"{fname}: 再存回 {'位元組完全相同' if out == cur else f'不同 ({len(cur)} vs {len(out)})'}")

print("\n全部通過 ✓" if not fail else f"\n{fail} 項失敗 ✗")
sys.exit(1 if fail else 0)
