# -*- coding: utf-8 -*-
"""核對翻譯表:重複鍵、是否存在於建置、原始碼用途分類、佔位符與標籤是否保留。"""
import ast
import json
import os
import re
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import zh_tw

problems = 0

# ---- 1. 找出字典重複鍵(Python 會靜默覆蓋) ----
tree = ast.parse(open(f"{S}/zh_tw.py", encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
        name = node.targets[0].id
        seen = {}
        for k, v in zip(node.value.keys, node.value.values):
            ks, vs = ast.literal_eval(k), ast.literal_eval(v)
            if ks in seen and seen[ks] != vs:
                print(f"[重複鍵且翻譯不同] {name}: {ks!r}: {seen[ks]!r} vs {vs!r}")
                problems += 1
            seen[ks] = vs

# ---- 2. CODE:存在性與用途 ----
lits = [json.loads(l) for l in open(f"{S}/literals.jsonl", encoding="utf-8")]
meta = {x["s"]: x["i"] for x in lits}
src = json.load(open(f"{S}/src_literals.json", encoding="utf-8"))
SAFE = {"bilingual", "prompt", "ui_text", "buttons"}
print(f"CODE 條目: {len(zh_tw.CODE)}")
missing, flagged = [], []
for k, v in zh_tw.CODE.items():
    if k not in meta:
        missing.append(k)
        continue
    info = src.get(k)
    if info is None:
        flagged.append((k, "原始碼分析中找不到(可能是日文字面值或格式差異)", {}))
        continue
    cats = set(info["cats"])
    if not cats <= SAFE:
        flagged.append((k, "含非顯示用途", info["cats"]))
print(f"\n不存在於建置字串表的鍵: {len(missing)}")
for k in missing:
    print("   ", repr(k))
print(f"\n需人工確認(用途不全是顯示): {len(flagged)}")
for k, why, c in flagged:
    print(f"   {k[:60]!r:64s} {why} {c}")

# ---- 3. 佔位符/標籤保留 ----
print("\n佔位符與標籤檢查:")
ph = re.compile(r"\{\d+\}")
tag = re.compile(r"<[^>]+>")
for label, d in (("CODE", zh_tw.CODE), ("SCENE", zh_tw.SCENE), ("LOC", zh_tw.LOC)):
    for k, v in d.items():
        pk, pv = set(ph.findall(k)), set(ph.findall(v))
        if not pv <= pk:
            print(f"   [{label}] 譯文多出佔位符 {k!r} -> {v!r}")
            problems += 1
        dropped = pk - pv
        if dropped and label == "CODE":
            # 允許丟掉複數後綴 {1}(card{1})
            if not (dropped == {"{1}"} and "card{1}" in k):
                print(f"   [{label}] 譯文弄丟佔位符 {sorted(dropped)}: {k!r} -> {v!r}")
                problems += 1
        if sorted(tag.findall(k)) != sorted(tag.findall(v)):
            print(f"   [{label}] 標籤不一致 {k!r} -> {v!r}")
            problems += 1
print("   (完成)")

# ---- 4. 場景:鍵是否存在於實際元件 ----
R = json.load(open(f"{S}/texts_all.json", encoding="utf-8"))
eng_keys = {r["eng"] for r in R if r["cls"] == "LocalizeTMPro" and (r["eng"] or r["jpn"])}
scene_texts = {r["text"] for r in R if r["cls"] in ("TextMeshProUGUI", "Text") and r.get("text") and not r["localized"]}
print(f"\nLOC 鍵總數 {len(zh_tw.LOC)};場景實際 ENG 鍵 {len(eng_keys)}")
print("  LOC 缺少翻譯的 ENG 鍵:", sorted(eng_keys - set(zh_tw.LOC)))
print("  LOC 多餘(場景沒有)的鍵:", sorted(set(zh_tw.LOC) - eng_keys))
unused = [k for k in zh_tw.SCENE if k not in scene_texts]
print(f"SCENE 鍵 {len(zh_tw.SCENE)};場景中找不到的: {unused}")
print("\n問題總數:", problems)
