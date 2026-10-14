# -*- coding: utf-8 -*-
"""從遊戲的 sharedassets2.assets 讀出全部 CEntity_Base(卡片資料),不需要型別樹。

欄位順序來自原始碼 CEntity_Base.cs(Unity 序列化依宣告順序)。
解析後會驗證「結束位置 == 物件大小」,不符就報錯。
"""
import json
import os
import struct
import sys

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import UnityPy

CARD_KIND = ["Digimon", "Tamer", "Option", "DigiEgg"]
COLOR = ["Red", "Blue", "Yellow", "Green", "White", "Black", "Purple", "None"]
RARITY = ["C", "U", "R", "SR", "UR", "SEC", "P", "None"]


class R:
    def __init__(self, b, pos=0):
        self.b, self.p = b, pos

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.p)[0]
        self.p += 4
        return v

    def s(self):
        n = self.i32()
        if n < 0 or self.p + n > len(self.b):
            raise ValueError("bad string")
        t = self.b[self.p:self.p + n].decode("utf-8")
        self.p += (n + 3) & ~3
        return t

    def ints(self):
        n = self.i32()
        if n < 0 or n > 10000:
            raise ValueError("bad list")
        return [self.i32() for _ in range(n)]

    def strs(self):
        n = self.i32()
        if n < 0 or n > 10000:
            raise ValueError("bad list")
        return [self.s() for _ in range(n)]


def parse_entity(raw):
    r = R(raw, 28)
    r.s()                                   # m_Name(從位移 28 開始;前 28 bytes 為 GameObject/Enabled/Script)
    d = {}
    d["CardIndex"] = r.i32()
    d["cardColors"] = [COLOR[x] if 0 <= x < len(COLOR) else x for x in r.ints()]
    d["PlayCost"] = r.i32()
    n = r.i32()
    d["EvoCosts"] = [(r.i32(), r.i32(), r.i32()) for _ in range(n)]
    d["Level"] = r.i32()
    d["CardName_JPN"] = r.s()
    d["CardName_ENG"] = r.s()
    for k in ("Form_JPN", "Form_ENG", "Attribute_JPN", "Attribute_ENG", "Type_JPN", "Type_ENG"):
        d[k] = r.strs()
    d["CardSpriteName"] = r.s()
    d["cardKind"] = [CARD_KIND[x] if 0 <= x < len(CARD_KIND) else x for x in r.ints()]
    for k in ("EffectDiscription_JPN", "EffectDiscription_ENG", "InheritedEffectDiscription_JPN",
              "InheritedEffectDiscription_ENG", "SecurityEffectDiscription_JPN", "SecurityEffectDiscription_ENG",
              "CardEffectClassName"):
        d[k] = r.s()
    d["DP"] = r.i32()
    x = r.i32()
    d["rarity"] = RARITY[x] if 0 <= x < len(RARITY) else x
    d["OverflowMemory"] = r.i32()
    d["LinkDP"] = r.i32()
    for k in ("LinkEffect", "LinkRequirement", "dualEffect"):
        d[k] = r.s()
    d["OptionCardColorRequirements"] = [COLOR[x] if 0 <= x < len(COLOR) else x for x in r.ints()]
    d["OptionEffect"] = r.s()
    d["CardID"] = r.s()
    d["MaxCountInDeck"] = r.i32()
    if r.p != len(raw):
        raise ValueError(f"解析結束位置 {r.p} != 物件大小 {len(raw)}")
    return d


def load_cards(data_dir):
    env = UnityPy.load(os.path.join(data_dir, "sharedassets2.assets"))
    f = list(env.files.values())[0]
    gm = UnityPy.load(os.path.join(data_dir, "globalgamemanagers.assets"))
    scripts = {pid: o.read().m_ClassName for pid, o in list(gm.files.values())[0].objects.items() if o.type.name == "MonoScript"}
    cards, bad = [], []
    for pid, o in f.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        fid, spid = struct.unpack_from("<iq", raw, 16)
        if scripts.get(spid) != "CEntity_Base":
            continue
        try:
            d = parse_entity(raw)
            d["_pid"] = pid
            cards.append(d)
        except Exception as e:
            bad.append((pid, str(e)))
    return cards, bad


if __name__ == "__main__":
    data = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(S), "Game", "DCGO_Data")
    cards, bad = load_cards(data)
    print(f"解析成功 {len(cards)} 張,失敗 {len(bad)} 張")
    for b in bad[:5]:
        print("  失敗:", b)
    json.dump(cards, open(f"{S}/card_db.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("已輸出 card_db.json")
