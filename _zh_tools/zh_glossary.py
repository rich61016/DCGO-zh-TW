# -*- coding: utf-8 -*-
"""對戰文字翻譯的固定詞彙(與第二版相同):時機標籤、關鍵字、卡名/特徵對照。

設計重點(不破壞引擎的字串判斷):
  * 引擎用 StartsWith/Contains 檢查說明文字的標籤([On Play]、[Hand]、[Main]、[Security]、[All Turns]…),
    標籤一律換成同一個中文標籤(方括號維持 ASCII),比對用的字串常值也同步替換。
  * Blitz / Mind Link / Digi-Burst / Digisorption - 這四個英文子字串會被引擎檢查,中文關鍵字寫成雙語保留英文。
  * 卡名/特徵寫成「中文名」;對照表來自副本根目錄的「名詞對照表.txt」(第四節)與 names_extra.json。
"""
import json
import os
import re

S = os.path.dirname(os.path.abspath(__file__))

TAGS = {
    "On Play": "登場時", "When Digivolving": "進化時", "When Attacking": "攻擊時", "On Deletion": "消滅時",
    "All Turns": "雙方的回合", "Your Turn": "我方的回合", "Opponent's Turn": "對方的回合",
    "Once Per Turn": "每回合1次", "Twice Per Turn": "每回合2次", "Main": "主要", "Security": "安防", "Hand": "手牌",
    "Counter": "反擊", "End of Attack": "攻擊結束時", "Start of Your Main Phase": "我方的主要階段開始時",
    "Start of Opponent's Main Phase": "對方的主要階段開始時", "Start of Your Turn": "我方的回合開始時",
    "Start of Opponent's Turn": "對方的回合開始時", "End of Your Turn": "我方的回合結束時",
    "End of Opponent's Turn": "對方的回合結束時", "End of All Turns": "雙方的回合結束時", "When Linking": "連結時",
    "When Moving": "移動時", "Breeding": "育成", "Trash": "廢棄區", "Digivolve": "進化", "Delay": "延遲", "Link": "連結",
    "De-Digivolve": "退化", "Start of Main Phase": "主要階段開始時", "End of Turn": "回合結束時", "Rule": "規則",
}
TAG_VARIANTS = {
    "once per turn": "Once Per Turn", "one per turn": "Once Per Turn", "your turn": "Your Turn", "all turns": "All Turns",
    "opponent's turn": "Opponent's Turn", "start of your turn": "Start of Your Turn", "end of your turn": "End of Your Turn",
    "end of opponent's turn": "End of Opponent's Turn", "end of opponents turn": "End of Opponent's Turn",
    "at end of opponent's turn": "End of Opponent's Turn", "start of your main phase": "Start of Your Main Phase",
    "start of opponent's turn": "Start of Opponent's Turn", "start of opponent's main phase": "Start of Opponent's Main Phase",
    "end of all turns": "End of All Turns", "when linked": "When Linking", "when linking": "When Linking",
    "twice per turn": "Twice Per Turn", "start of main phase": "Start of Main Phase", "end of turn": "End of Turn",
}
COLORS = {"red": "紅", "blue": "藍", "yellow": "黃", "green": "綠", "white": "白", "black": "黑", "purple": "紫"}
SIMPLE_KW = {
    "blocker": "《阻擋者》", "rush": "《速攻》", "piercing": "《貫通》", "jamming": "《干擾》", "reboot": "《重啟》",
    "retaliation": "《同歸於盡》", "raid": "《突進》", "alliance": "《聯協》", "barrier": "《屏障》",
    "delay": "《延遲》", "save": "《保存》", "collision": "《衝突》", "fortitude": "《不屈》", "evade": "《回避》",
    "vortex": "《旋風》", "progress": "《進程》", "execute": "《處決》", "overclock": "《超頻》", "ascension": "《升天》",
    "partition": "《分裂》", "training": "《訓練》", "guard": "《守護》", "engage": "《急襲》", "scapegoat": "《替罪》", "iceclad": "《冰裝》",
    "armor purge": "《裝甲解除》", "decode": "《解碼》", "blast digivolve": "《突風進化》", "blast dna digivolve": "《突風合步進化》",
    "blitz": "《進擊 Blitz》", "mind link": "《意識連結 Mind Link》", "digisorption": "《吸收進化 Digisorption》",
    "digi-burst": "《數碼爆裂 Digi-Burst》",
}
DESC_PROTECT = ("Blitz", "Mind Link", "Digi-Burst", "Digisorption -")
NAME_PROTECT = ("Digisorption", "Blast", "Decode", "Set Memory to ")


def tag_key(tok):
    s = tok.strip()
    if s in TAGS:
        return s
    return TAG_VARIANTS.get(s.lower())


def kw_to_zh(tok):
    t = tok.strip()
    tl = t.lower()
    if tl in SIMPLE_KW:
        return SIMPLE_KW[tl]
    m = re.fullmatch(r"draw\s*(\d+)?", tl)
    if m:
        return f"抽 {m.group(1)} 張卡片" if m.group(1) else "抽牌"
    m = re.fullmatch(r"de-?\s?digivolve\s*-?\s*(\d+)?", tl)
    if m:
        return f"退化 {m.group(1)}" if m.group(1) else "退化"
    m = re.fullmatch(r"(?:recovery|revovery|recover)\s*\+\s*(\d+)\s*(\(deck\)|<deck>)?", tl)
    if m:
        return f"恢復+{m.group(1)}《牌組》" if m.group(2) else f"恢復+{m.group(1)}"
    m = re.fullmatch(r"(?:security attack|security a\.?|security atk|sec a\.?)\s*([+-])\s*(\d+)", tl)
    if m:
        return f"《安防攻擊{m.group(1)}{m.group(2)}》"
    if tl == "security attack":
        return "《安防攻擊》"
    m = re.fullmatch(r"digi-burst\s*(\d+)", tl)
    if m:
        return f"《數碼爆裂 Digi-Burst {m.group(1)}》"
    m = re.fullmatch(r"digisorption\s*-\s*(\d+)", tl)
    if m:
        return f"《吸收進化 Digisorption -{m.group(1)}》"
    m = re.fullmatch(r"material save\s*(\d+|\{0\})", tl)
    if m:
        return f"《素材保存 {m.group(1)}》"
    m = re.fullmatch(r"decoy\s*\(?\s*(.+?)\s*\)?", tl)
    if m:
        parts = re.split(r"\s*/\s*|\s*\)\s*/\s*\(\s*", m.group(1))
        if all(p in COLORS for p in parts):
            return "《誘餌《" + "/".join(COLORS[p] for p in parts) + "》》"
    return None


def names():
    """卡名/特徵對照(英文 → 中文)。"""
    out = {}
    p = os.path.join(os.path.dirname(S), "名詞對照表.txt")
    if os.path.exists(p):
        sec = False
        for line in open(p, encoding="utf-8"):
            if line.startswith("■ 四"):
                sec = True
                continue
            if sec and line.startswith("■"):
                break
            if sec:
                m = re.match(r"^  (.+?)  →  (.+)$", line.rstrip("\n"))
                if m:
                    out[m.group(1)] = m.group(2)
    extra = os.path.join(S, "names_extra.json")
    if os.path.exists(extra):
        out.update(json.load(open(extra, encoding="utf-8")))
    return out
