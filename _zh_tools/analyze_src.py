"""分析 DCGO 原始碼中每個字串常值的用途,並與建置內的 metadata 字串表對照。"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_lex

S = os.path.dirname(os.path.abspath(__file__))
ROOT = f"{S}/dcgo-src/Assets/Scripts"

lits = [json.loads(l) for l in open(f"{S}/literals.jsonl", encoding="utf-8")]
meta = {x["s"]: x["i"] for x in lits}

CAT_ORDER = ["bilingual", "network", "prefs", "debug", "compare", "effect_name", "prompt", "effect_desc",
             "ui_text", "buttons", "identifier", "other"]


def statement_before(src, start, maxlen=260):
    seg = src[max(0, start - maxlen):start]
    # 只取到上一個語句邊界之後(; { }),但保留函式呼叫括號內的內容
    k = max(seg.rfind(";"), seg.rfind("{\n"), seg.rfind("}\n"))
    return seg[k + 1:] if k >= 0 else seg


def classify(src, st, en, text, interp):
    before = statement_before(src, st)
    bnorm = re.sub(r"\s+", " ", before)
    after = src[en:en + 80]
    anorm = re.sub(r"\s+", " ", after)
    if "GetLocalizedString" in bnorm:
        return "bilingual"
    if re.search(r"PhotonNetwork|\.RPC\(|SetCustomProperties|CustomProperties|photonView", bnorm + anorm):
        return "network"
    if "PlayerPrefs" in bnorm:
        return "prefs"
    if re.search(r"Debug\.(Log|LogWarning|LogError)|Console\.Write|Debug\.Assert", bnorm):
        return "debug"
    # 比對 / 搜尋 / 鍵值
    if re.search(r"(==|!=)\s*$", bnorm) or re.match(r"^\s*(==|!=)", anorm):
        return "compare"
    if re.search(r"\.(Equals|Contains|StartsWith|EndsWith|IndexOf|LastIndexOf|Replace|Split|Compare|Trim|TrimStart|TrimEnd|ContainsKey|Remove|Find|FindIndex)\(\s*$", bnorm):
        return "compare"
    if re.search(r"(^|\W)case\s*$", bnorm) and anorm.lstrip().startswith(":"):
        return "compare"
    if re.search(r"\[\s*$", bnorm) and anorm.lstrip().startswith("]"):
        return "compare"
    if re.search(r"(Dictionary|HashSet)<", bnorm) or re.search(r"\{\s*$", bnorm) and anorm.lstrip().startswith(","):
        return "compare"
    # 效果名稱
    if re.search(r"SetUpICardEffect\(\s*$", bnorm) or re.search(r"SetEffectName\(\s*$", bnorm) or re.search(r"EffectName\s*=\s*$", bnorm):
        return "effect_name"
    # 玩家提示句
    if re.search(r"(SetUpCustomMessage\w*\(\s*(?:[^,()]*,\s*)*$)|(message\s*:\s*$)|(message\s*=\s*$)|(\bmessage\w*\s*:\s*$)", bnorm, re.I):
        return "prompt"
    if re.search(r"SetUpCustomMessage", bnorm):
        return "prompt"
    # 效果說明(卡片文字)
    if re.match(r"^\s*(\[[A-Z][A-Za-z' ]+\]|<[A-Z])", text) and len(text) > 12:
        return "effect_desc"
    if re.search(r"EffectDiscription|SetEffectDiscription", bnorm):
        return "effect_desc"
    # 畫面文字
    if re.search(r"\.text\s*=\s*$", bnorm) or re.search(r"SetText\(\s*$", bnorm):
        return "ui_text"
    if re.search(r"new List<string>\s*(\(\))?\s*\{[^}]*$", bnorm):
        return "buttons"
    if " " not in text.strip() and re.fullmatch(r"[A-Za-z0-9_\-./#:\[\]()<>+*&%$@!?,'\"|=~^]*", text.strip() or "x") and len(text) < 40:
        return "identifier"
    return "other"


def main():
    per_text = collections.defaultdict(lambda: {"cats": collections.Counter(), "files": set(), "interp": False, "n": 0})
    for dp, dn, fn in os.walk(ROOT):
        for f in fn:
            if not f.endswith(".cs"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT)
            src = open(p, encoding="utf-8-sig", errors="replace").read()
            for st, en, text, interp, verb in cs_lex.lex_strings(src):
                if not text.strip():
                    continue
                cat = classify(src, st, en, text, interp)
                d = per_text[text]
                d["cats"][cat] += 1
                d["n"] += 1
                d["interp"] = d["interp"] or interp
                if len(d["files"]) < 4:
                    d["files"].add(rel)
    out = {}
    for t, d in per_text.items():
        out[t] = {"cats": dict(d["cats"]), "files": sorted(d["files"]), "interp": d["interp"], "n": d["n"],
                  "meta_index": meta.get(t.replace("\r\n", "\n"), meta.get(t))}
    json.dump(out, open(f"{S}/src_literals.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("來源中獨特字串:", len(out))
    inb = {t: v for t, v in out.items() if v["meta_index"] is not None}
    print("其中同時存在於建置 metadata 字串表的:", len(inb))

    # 以「最嚴格」的分類(任何一處是 compare/network/prefs 即視為不安全)彙總
    unsafe_cats = {"compare", "network", "prefs", "effect_name"}
    def bucket(v):
        c = set(v["cats"])
        if c & {"compare"}: return "UNSAFE:compare"
        if c & {"network"}: return "UNSAFE:network"
        if c & {"prefs"}: return "UNSAFE:prefs"
        if c & {"effect_name"}: return "RISK:effect_name"
        for k in ("bilingual", "prompt", "ui_text", "buttons", "effect_desc", "debug", "identifier", "other"):
            if k in c:
                return k
        return "other"
    cnt = collections.Counter(bucket(v) for v in inb.values())
    print("\n--- 存在於建置的字串,依用途分類(獨特字串數) ---")
    for k, v in cnt.most_common():
        print(f"  {v:6d}  {k}")
    # 路徑分類:卡片腳本 vs 核心
    cnt2 = collections.Counter()
    for t, v in inb.items():
        b = bucket(v)
        iscard = all(f.startswith("CardEffect/") for f in v["files"])
        cnt2[(b, "CardEffect" if iscard else "Script/其他")] += 1
    print("\n--- 加上來源位置 ---")
    for (b, w), v in sorted(cnt2.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {v:6d}  {b:18s} {w}")


if __name__ == "__main__":
    main()
