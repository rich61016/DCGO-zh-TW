#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把牌表(digimonmeta / Tabletop Simulator 的 JSON、或「張數 卡名 卡號」文字)做成 DCGO 的牌組檔。

做的事(全部依 DCGO 原始碼的規則):
  1. 以遊戲自己的查卡規則(先比 CardID、再比 CardSpriteName,取 CardList 中第一個)解析每個卡號;
  2. 檢查:找不到的卡號(遊戲載入時會「默默略過」)、超過張數上限、主牌組 50 張 / 數碼蛋 ≤5 張;
  3. 輸出遊戲自己的檔案格式:  <牌組名>_<11 碼 ID>.txt  (LF 換行、無 BOM);
  4. 重新讀回檔案,用「遊戲載入器的逐行演算法(含它會吃掉下一行的怪癖)」模擬載入,確認結果與預期完全一致;
  5. (可選)對照線上禁卡表,預測遊戲載入時會不會自動修剪。

用法:
  python3 make_deck.py 牌表.json --name "Royal Knights" --game-root /path/to/DCGO資料夾
  python3 make_deck.py - --name X < 牌表.txt         # 從標準輸入讀
  加 --dry-run 只檢查不寫檔;加 --check-banlist 會連線取得 dcgo.online 的禁卡表。

注意:遊戲只在「啟動時」讀取牌組檔,寫入後需重開遊戲才會看到。
"""
import argparse
import collections
import json
import os
import random
import re
import string
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ALNUM = string.ascii_uppercase + string.ascii_lowercase + string.digits
ID_RE = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9_\-]+$")
BANLIST_URL = "https://www.dcgo.online/Banlist.json"


# ------------------------------------------------------------------ 卡片資料庫
class Cards:
    def __init__(self, index_path):
        data = json.load(open(index_path, encoding="utf-8"))
        self.cards = data["cards"]                       # 依遊戲 CardList 順序
        self.by_id = collections.defaultdict(list)
        self.by_sprite = {}
        for c in self.cards:
            self.by_id[c["CardID"]].append(c)
            self.by_sprite.setdefault(c["CardSpriteName"], c)

    def find(self, token):
        """等同 DeckCodeUtility.GetCardFromCardID:先比 CardID(取第一個),再比 CardSpriteName。"""
        v = self.by_id.get(token)
        if v:
            return v[0]
        return self.by_sprite.get(token)


# ------------------------------------------------------------------ 輸入解析
def parse_input(text):
    """回傳 [(卡號token, 張數), ...](保持輸入順序);也回傳被忽略的標頭字串。"""
    text = text.strip()
    ignored = []
    try:
        arr = json.loads(text)
    except Exception:
        arr = None
    order = collections.OrderedDict()
    if isinstance(arr, list):
        for x in arr:
            if isinstance(x, str) and ID_RE.match(x.strip()):
                order[x.strip()] = order.get(x.strip(), 0) + 1
            else:
                ignored.append(x)
        return list(order.items()), ignored
    # 文字格式:每行「N 卡名 卡號」或「N 卡號」
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.lower().startswith(("name:", "key card:", "sort index:")):
            continue
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if m:
            n, rest = int(m.group(1)), m.group(2).strip()
            tok = rest.split()[-1] if rest else ""
            if ID_RE.match(tok):
                order[tok] = order.get(tok, 0) + n
                continue
        ignored.append(line)
    return list(order.items()), ignored


# ------------------------------------------------------------------ 輸出
def ascii_fix(t):
    for a, b in (("＜", "<"), ("＞", ">"), ("、", ","), ("，", ","), ("“", '"'), ("・", ""), ("　", ""), ("！", "!")):
        t = t.replace(a, b)
    return t


def validate_name(name):
    kept = "".join(ch for ch in name if ch.isascii() and (ch.isalnum() or ch == " "))
    return kept


def new_deck_id(existing):
    while True:
        s = "".join(random.SystemRandom().sample(ALNUM, 11))     # 與遊戲相同:62 個字元不重複抽 11 個
        if s not in existing:
            return s


def build_file_text(name, key_card, sort_index, entries):
    """entries: [(cardinfo, count)],順序 = 數碼蛋在前、主牌組在後(同遊戲 AllDeckCards 的順序)。"""
    t = f"Name: {name}\nKey Card: {key_card}\nSort Index: {sort_index}\n\n// DeckList\n\n"
    for c, n in entries:
        t += f"{n} {c['CardName_ENG']}   {c['CardSpriteName']} \n"
    return ascii_fix(t)


# ------------------------------------------------------------------ 遊戲載入器模擬
def simulate_load(file_text, db):
    """逐行重現 LoadDeckLists → GetAllDeckCardsFromDeckBuilderDeckCode 的演算法(含吃下一行的怪癖)。"""
    code = file_text[file_text.index("//"):]
    lines = re.split(r"\r\n|\r|\n", code)
    if lines and lines[-1] == "":
        lines.pop()                                  # C# ReadLine 不會回傳結尾的空字串
    out = []
    i = 0

    def read_line():
        nonlocal i
        if i < len(lines):
            v = lines[i]
            i += 1
            return v
        return None

    while True:
        line = read_line()
        if line is None:
            break
        if line == "":
            continue
        if line[0].isdigit():
            sp = line.index(" ")
            try:
                count = int(line[:sp].strip())
            except ValueError:
                count = 0
            for _ in range(4):
                line = line.rstrip()
                last = line.rfind(" ")
                cid = line[last + 1:]
                card = db.find(cid)
                if card is not None:
                    out.extend([card] * count)
                    break
                nxt = read_line()
                line += "/" + (nxt if nxt is not None else "")
    return out


# ------------------------------------------------------------------ 主程式
def main():
    ap = argparse.ArgumentParser(description="把牌表做成 DCGO 牌組檔")
    ap.add_argument("input", help="牌表檔案路徑;用 - 代表從標準輸入讀")
    ap.add_argument("--name", required=True, help="牌組名稱(遊戲只保留英數字與空格)")
    ap.add_argument("--game-root", required=True, help="含 Game 資料夾的那層(其下的 Assets/Decks 會放牌組檔)")
    ap.add_argument("--index", default=os.path.join(HERE, "card_index.json"), help="卡片索引(預設與本程式同資料夾)")
    ap.add_argument("--key-card", type=int, default=-1, help="牌組圖示的卡片編號 CardIndex;-1 = 由遊戲自動挑(預設)")
    ap.add_argument("--dry-run", action="store_true", help="只檢查,不寫檔")
    ap.add_argument("--check-banlist", action="store_true", help="連線取得 dcgo.online 禁卡表,預測載入時是否被修剪")
    ap.add_argument("--allow-missing", action="store_true", help="允許有找不到的卡號(會被遊戲略過,不建議)")
    a = ap.parse_args()

    text = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8").read()
    db = Cards(a.index)
    items, ignored = parse_input(text)
    if ignored:
        print("忽略的項目(非卡號):", ignored)
    if not items:
        sys.exit("牌表裡沒有讀到任何卡號")

    resolved, missing, over = [], [], []
    for tok, n in items:
        c = db.find(tok)
        if c is None:
            missing.append((tok, n))
            continue
        if n > c["MaxCountInDeck"]:
            over.append((tok, n, c["MaxCountInDeck"]))
        resolved.append((c, n))
    eggs = [(c, n) for c, n in resolved if "DigiEgg" in c["cardKind"]]
    main_cards = [(c, n) for c, n in resolved if "DigiEgg" not in c["cardKind"]]
    n_egg, n_main = sum(n for _, n in eggs), sum(n for _, n in main_cards)

    print(f"\n{'卡號':11s}{'張數':>4s}  {'種類':8s}{'Lv':>3s}  {'稀有':4s} 遊戲取用的版本 / 英文卡名")
    for c, n in eggs + main_cards:
        print(f"{c['CardID']:11s}{n:4d}  {'/'.join(c['cardKind']):8s}{c['Level']:3d}  {c['rarity']:4s} {c['CardSpriteName']}  {c['CardName_ENG']}")
    print(f"\n數碼蛋 {n_egg} 張、主牌組 {n_main} 張(合計 {n_egg + n_main})")

    problems = []
    if missing:
        problems.append(f"遊戲資料庫找不到 {len(missing)} 種卡號、共 {sum(n for _, n in missing)} 張(載入時會被默默略過): "
                        + ", ".join(f"{t}×{n}" for t, n in missing))
    if over:
        problems.append("超過張數上限: " + ", ".join(f"{t} 放 {n} > 上限 {m}" for t, n, m in over))
    if n_main != 50 or n_egg > 5:
        problems.append(f"牌組規格不符(需主牌組 50 張、數碼蛋 ≤5 張;目前 {n_main} / {n_egg}),遊戲會顯示「無法使用」")

    if a.check_banlist:
        try:
            ban = json.loads(urllib.request.urlopen(BANLIST_URL, timeout=20).read().decode("utf-8"))
            cnt = collections.Counter()
            for c, n in resolved:
                cnt[c["CardID"]] += n
            for r in ban.get("Restrictions", []):
                if cnt.get(r["id"], 0) > r["limit"]:
                    problems.append(f"禁卡表:{r['id']} 上限 {r['limit']},你放 {cnt[r['id']]},載入時會被砍")
            for p in ban.get("BannedPair", []):
                if cnt.get(p["id"]) and any(cnt.get(x) for x in p["pairs"]):
                    problems.append(f"禁卡表:{p['id']} 不能與 {p['pairs']} 同時出現,載入時會被砍")
            print("已對照線上禁卡表。")
        except Exception as e:
            print("(無法取得線上禁卡表:", e, ")")

    if problems:
        print("\n⚠ 需要注意:")
        for p in problems:
            print("  -", p)
        if missing and not a.allow_missing:
            sys.exit("\n因為有找不到的卡號,未寫入檔案(若仍要寫入請加 --allow-missing)。")

    name = validate_name(a.name).strip()
    if name != a.name:
        print(f"牌組名稱只保留英數字與空格:「{a.name}」→「{name}」")
    if not name:
        sys.exit("牌組名稱清空後是空的,請改用英數字")

    # 找不到的卡:附在檔尾(避免遊戲載入器『吃掉下一行』而弄錯相鄰卡片的張數)
    entries = eggs + main_cards
    file_text = build_file_text(name, a.key_card, 0, entries)
    for tok, n in missing:
        file_text += f"{n} {tok}   {tok} \n"

    decks_dir = os.path.join(a.game_root, "Assets", "Decks")
    if not os.path.isdir(decks_dir):
        sys.exit(f"找不到牌組資料夾: {decks_dir}")
    existing = {os.path.splitext(f)[0].split("_")[-1] for f in os.listdir(decks_dir)}
    deck_id = new_deck_id(existing)
    path = os.path.join(decks_dir, f"{name}_{deck_id}.txt")

    # 以載入器演算法模擬,預期結果 = 找得到的卡
    expected = collections.Counter()
    for c, n in entries:
        expected[c["CardSpriteName"]] += n
    got = collections.Counter(c["CardSpriteName"] for c in simulate_load(file_text, db))
    if got != expected:
        sys.exit(f"模擬載入結果與預期不符,停止。\n預期 {dict(expected)}\n實際 {dict(got)}")
    print(f"模擬遊戲載入:取得 {sum(got.values())} 張(蛋 {n_egg} + 主牌組 {n_main}),與預期完全一致 ✓")

    if a.dry_run:
        print(f"(乾跑)會寫入: {path}")
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(file_text)
    back = open(path, encoding="utf-8").read()
    got2 = collections.Counter(c["CardSpriteName"] for c in simulate_load(back, db))
    assert got2 == expected, "寫入後重新讀回的結果不符"
    print(f"\n已寫入: {path}\n(重新讀回檔案並模擬載入:結果一致 ✓)\n提醒:遊戲只在啟動時讀取牌組檔,請重開遊戲。")


if __name__ == "__main__":
    main()
