# -*- coding: utf-8 -*-
"""把新版本新增字串的譯文(含佔位符)驗證後併入 zh_v2_map.json。

用法: python zh_merge_new.py <items.json> <譯文.json> [--write]
  items.json:[{id, kind(prompt|name|desc), mode(whole|frag), key(metadata 原字串), en(含佔位符的英文)}]
  譯文.json :{id: 中文(含 [[T:..]] [[K:..]] [[N:..]] 佔位符)}
不加 --write 只檢查不寫入。
"""
import json
import os
import re
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import zh_glossary as G

PH = re.compile(r"\[\[(T|K|N):(.*?)\]\]")
FMT = re.compile(r"\{\d+(?::[^}]*)?\}")
BAD = re.compile("[“”‘’・　！＜＞-]")
OK_WORDS = {"DNA", "Blitz", "Mind", "Link", "Digi", "Burst", "Digisorption", "DP", "Lv", "Assembly", "Veemon"}
COMPARATOR_TAGS = ["On Play", "When Digivolving", "When Attacking", "On Deletion", "Hand", "Main", "Security", "All Turns"]
STARTS = ["On Play", "When Digivolving", "When Attacking", "On Deletion", "All Turns"]
CONTAINS = ["Hand", "Main", "Security"]
NAMES = G.names()
FW = str.maketrans({"(": "（", ")": "）"})


def denorm(zh, kind):
    def sub(m):
        k, tok = m.group(1), m.group(2)
        if k == "T":
            return "[" + G.TAGS[tok] + "]"
        if k == "K":
            z = G.kw_to_zh(tok)
            if z is None:
                raise KeyError(f"不認得的關鍵字 {tok}")
            return z
        if tok not in NAMES:
            raise KeyError(f"名詞對照表沒有「{tok}」")
        return "「" + NAMES[tok] + "」"
    t = PH.sub(sub, zh)
    if kind == "name":
        t = t.translate(FW)
    return t


def digits(s):
    return sorted(re.findall(r"\d+", PH.sub("", s)))


def check(it, zh):
    iss = []
    en = it["en"]
    if sorted(PH.findall(en)) != sorted(PH.findall(zh)):
        iss.append(f"佔位符不符 {sorted(set(PH.findall(en)) ^ set(PH.findall(zh)))}")
    if sorted(FMT.findall(en)) != sorted(FMT.findall(zh)):
        iss.append("格式洞不符")
    de, dz = digits(en), digits(zh)
    # 7K ↔ 7000 視為相同
    norm = lambda ds: sorted(d[:-3] if d.endswith("000") and len(d) > 3 else d for d in ds)
    if it["kind"] == "desc":
        if norm(de) != norm(dz):
            iss.append(f"數字不符 {de} → {dz}")
    else:
        left = list(norm(dz))
        for d in norm(de):
            if d in left:
                left.remove(d)
            else:
                iss.append(f"缺少數字 {d}")
    if en.count("\n") != zh.count("\n") or en.count("\r") != zh.count("\r"):
        iss.append("換行數不符")
    if BAD.search(zh):
        iss.append("含禁用字元 " + "".join(set(BAD.findall(zh))))
    words = [w for w in re.findall(r"[A-Za-z]{3,}", PH.sub("", zh)) if w not in OK_WORDS]
    if words:
        iss.append(f"殘留英文 {words[:3]}")
    lead_en = re.findall(r"^(?:\[\[T:[^\]]*\]\]\s*)+", en)
    lead_zh = re.findall(r"^(?:\[\[T:[^\]]*\]\]\s*)+", zh)
    if (lead_en[0].replace(" ", "") if lead_en else "") != (lead_zh[0].replace(" ", "") if lead_zh else ""):
        iss.append("開頭標籤不同")
    if it["mode"] == "frag" and it["key"].startswith("] ") and not zh.startswith("] "):
        iss.append("片段必須以「] 」開頭")
    if it["kind"] == "name" and re.search(r"[。.]$", zh.strip()):
        iss.append("效果名稱結尾不可有句號")
    if it["kind"] == "name" and any(p in it["key"] for p in G.NAME_PROTECT):
        iss.append("效果名稱含引擎會比對的英文字樣,不可翻")
    return iss


def parity(it, final):
    """引擎判斷(StartsWith/Contains)在英文與中文版本必須相同。"""
    iss = []
    src = it["key"]
    tr = final
    if it["mode"] == "frag" and src.startswith("] "):
        src = "[On Play" + src            # 以 SharedEffectDescription("On Play") 組合後檢查
        tr = "[登場時" + tr
    zh_tag = lambda t: "[" + G.TAGS[t] + "]"
    for t in STARTS:
        if src.startswith(f"[{t}]") != tr.startswith(zh_tag(t)):
            iss.append(f"StartsWith [{t}] 不一致")
    for t in CONTAINS:
        if (f"[{t}]" in src) != (zh_tag(t) in tr):
            iss.append(f"Contains [{t}] 不一致")
    for p in G.DESC_PROTECT:
        if (p in src) != (p in tr):
            iss.append(f"Contains {p} 不一致")
    return iss


def main():
    items = {str(i["id"]): i for i in json.load(open(sys.argv[1], encoding="utf-8"))}
    tr = json.load(open(sys.argv[2], encoding="utf-8"))
    out, bad = {}, 0
    for k, it in items.items():
        if k not in tr:
            print(f"[{k}] 缺譯文")
            bad += 1
            continue
        zh = tr[k]
        iss = check(it, zh)
        final = None
        if not iss:
            try:
                final = denorm(zh, it["kind"])
            except KeyError as e:
                iss.append(str(e))
        if final is not None and it["kind"] == "desc":
            iss += parity(it, final)
        if iss:
            bad += 1
            print(f"[{k}] {iss}\n     EN: {it['en'][:120]}\n     ZH: {zh[:120]}")
            continue
        out[it["key"]] = final
    extra = [k for k in tr if k not in items]
    if extra:
        print("多出的譯文 id:", extra)
    print(f"通過 {len(out)} 句,有問題 {bad} 句")
    if "--write" in sys.argv and not bad:
        p = os.path.join(S, "zh_v2_map.json")
        m = json.load(open(p, encoding="utf-8"))
        clash = [k for k in out if k in m and m[k] != out[k]]
        if clash:
            print("與既有翻譯衝突(保留既有):", clash[:5])
        for k, v in out.items():
            m.setdefault(k, v)
        json.dump(m, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"已併入 zh_v2_map.json,現在共 {len(m)} 句")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
