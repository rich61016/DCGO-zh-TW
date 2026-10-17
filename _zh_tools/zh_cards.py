# -*- coding: utf-8 -*-
"""卡片中文化:用官方簡體中文卡表(digimoncard.cn)把卡圖與卡片文字換成中文。

卡圖(遊戲資料夾 Assets/Textures/Card/<卡圖名>.webp)
  - 日文卡圖、遊戲自動下載的英文卡圖:官方簡中有「同一張插畫」的版本就換成中文(比對卡片上方的插畫區域,
    避開中央的 SAMPLE/樣品圖浮水印與下方的文字框)。
  - 異圖、勘誤版找不到同一張插畫時,改用同卡號的中文普通版;之後官方簡中補上同一張插畫,會自動換成正確的異圖。
  - 被換掉的原圖備份在 _zh_tools/cards/backup/,可用 --restore 全部還原。
卡片文字
  - 卡名、形態/屬性/特徵、效果、進化源效果、安防效果:官方簡中文字轉成繁體(OpenCC s2tw,與對戰文字的用詞一致),
    存成 cards/card_text_zh.json,由 build_zh.py 寫進卡片資料庫(sharedassets2.assets)的「日文」欄位。
    遊戲規則只讀英文欄位(已用原始碼確認),遊戲語言設定維持「日文」就會顯示中文。

用法:
  python zh_cards.py              檢查官方簡中卡表(超過 1 天才重抓),更新卡圖與卡片文字(啟動檔使用)
  python zh_cards.py --all        連「還沒下載過」的卡圖也補上中文版(沒有卡圖包時使用,下載量大)
  python zh_cards.py --refresh    強制重抓官方簡中卡表
  python zh_cards.py --dry-run    只比對、把結果寫到 cards/match_report.json,不改任何卡圖
  python zh_cards.py --restore    把換過的卡圖全部還原成原圖
  python zh_cards.py --images-only / --text-only
"""
import collections
import concurrent.futures
import datetime
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import warnings

# 官方 PNG 多半是含透明色的調色盤圖,Pillow 轉檔時會出提醒(不影響結果),不要讓它塞滿啟動檔的視窗
warnings.filterwarnings("ignore", message="Palette images with Transparency")

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

CARD_DIR = os.path.join(ROOT, "Assets", "Textures", "Card")
WORK = os.path.join(TOOLS, "cards")
SC_LIST = os.path.join(WORK, "sc_cards.json")          # 官方簡中卡表(快取)
IMG_STATE = os.path.join(WORK, "images.json")          # 換過哪些卡圖、來源、比對分數
TEXT_OUT = os.path.join(WORK, "card_text_zh.json")     # 卡片文字(繁中),build_zh.py 讀這個
REPORT = os.path.join(WORK, "match_report.json")       # 最近一次比對的明細
PNG_CACHE = os.path.join(WORK, "sc_png")               # 下載中的官方圖(完成後刪除)
BACKUP = os.path.join(WORK, "backup")                  # 被換掉的原圖

API = "https://dtcgweb-api.digimoncard.cn/gamecard/gamecardmanager/weblist"
HEADERS = {"User-Agent": "Mozilla/5.0 (DCGO-zh-TW)"}
MAX_AGE_H = 24                                         # 官方卡表超過這麼久才重抓

# 插畫比對:整張卡縮成 60×84 灰階,取上方插畫區(x 3–57、y 7–37),允許 ±2 像素位移,用正規化相關係數。
# 門檻依 2026-10-17 的人工抽查決定:不同插畫最高約 0.37;同一張插畫(含不同邊框、金框、印章版)最低約 0.49。
NW, NH = 60, 84
RX0, RY0, RX1, RY1 = 3, 7, 57, 37
SHIFT = 2
ACCEPT = 0.55          # 最高分達到這個值:同一張插畫
WEAK, WEAK_MARGIN = 0.45, 0.20   # 0.45–0.55:要比第二名高出 0.20 以上才接受
TIE = 0.03             # 前幾名差距在此之內(同一張插畫的不同版本):改用整張卡比對,挑邊框/印章最像的

KIND_ZH = {"Digimon": "数码宝贝", "Tamer": "驯兽师", "Option": "选项", "DigiEgg": "数码蛋"}
BASE_RE = re.compile(r"^([A-Z]+\d*-\d+)")


def say(msg=""):
    print(msg, flush=True)


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-zh"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def http_get(url, timeout=60, tries=3, limit=20 << 20):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read(limit + 1)
            if len(data) > limit:
                raise RuntimeError("檔案過大")
            return data
        except Exception as ex:
            last = ex
            time.sleep(1 + 2 * i)
    raise last


def base_of(model):
    m = BASE_RE.match((model or "").strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------- 官方簡中卡表
def fetch_sc(force=False):
    """回傳 (卡表快取, 是否剛重抓)。抓不到就用上次的快取;都沒有回傳 None。"""
    cache = load_json(SC_LIST, None)
    if cache and not force:
        try:
            age = datetime.datetime.now() - datetime.datetime.fromisoformat(cache["fetched_at"])
            if age < datetime.timedelta(hours=MAX_AGE_H):
                return cache, False
        except Exception:
            pass
    try:
        cards, page = [], 1
        while True:
            d = json.loads(http_get(f"{API}?page={page}&limit=1000&state=0").decode("utf-8"))
            if d.get("code") != 0:
                raise RuntimeError(d.get("msg") or "伺服器回傳錯誤")
            p = d["page"]
            lst = p.get("list") or []
            cards += lst
            if page >= int(p.get("totalPage") or 1) or not lst:
                break
            page += 1
            time.sleep(0.5)
        prev = len(cache["cards"]) if cache else 0
        if len(cards) < 1000 or len(cards) < prev * 0.9:
            raise RuntimeError(f"資料筆數異常({len(cards)} 筆)")
        cache = {"fetched_at": now_iso(), "count": len(cards), "cards": cards}
        save_json(SC_LIST, cache)
        return cache, True
    except Exception as ex:
        say(f"  無法取得官方簡中卡表({ex})" + (",改用上次抓到的資料。" if cache else "。"))
        return cache, False


def sc_by_base(sc_cards):
    out = collections.defaultdict(list)
    seen = set()
    for e in sc_cards:
        b = base_of(e.get("model"))
        if b and e.get("imageCover") and e["imageCover"] not in seen:
            seen.add(e["imageCover"])
            out[b].append(e)
    return out


def pick_normal(cid, entries):
    """同卡號的「普通版」:卡號完全相同的一般卡 → 其他一般卡 → 任一張;同等級取最新。"""
    def key(e):
        m = (e.get("model") or "").strip()
        return (m != cid or e.get("parallCard") != "1", e.get("parallCard") != "1", len(m))
    if not entries:
        return None
    newest_first = sorted(entries, key=lambda e: e.get("updateTime") or "", reverse=True)
    return sorted(newest_first, key=key)[0]          # sorted 是穩定排序:同等級時保留「最新」在前


# ---------------------------------------------------------------------------- 遊戲的卡片清單
def game_cards():
    import carddb
    import zh_assets as A
    seed_pristine()
    cards, bad = carddb.load_cards(None, sa2_path=A.orig("sharedassets2.assets"),
                                   ggm_path=A.orig("globalgamemanagers.assets"))
    if bad:
        raise RuntimeError(f"卡片資料庫有 {len(bad)} 筆無法解析")
    return cards


def seed_pristine():
    """卡片資料庫的官方原檔放進 pristine/(遊戲資料夾裡的檔案若與官方雜湊相同就直接複製,不必下載)。"""
    import zh_update as U
    U.seed_pristine(U.load_state())


# ---------------------------------------------------------------------------- 卡圖:狀態與分類
def card_path(sprite):
    return os.path.join(CARD_DIR, sprite + ".webp")


def backup_path(sprite):
    return os.path.join(BACKUP, sprite + ".webp")


def sha1hex(data):
    return hashlib.sha1(data).hexdigest()


def pack_languages():
    """卡圖包附的清單:卡圖名 → 語言(zh-CN / ja)。同卡普通圖補白的位置,語言跟著被借用的普通圖。"""
    lang, borrowed = {}, {}
    for fn in ("manifest.json", "alternate-manifest.json", "repair-manifest.json"):
        for e in load_json(os.path.join(ROOT, fn), []) or []:
            i = e.get("id")
            if not i:
                continue
            if e.get("language"):
                lang[i] = e["language"]
            elif e.get("status") == "same-card-base-fallback" and e.get("replacement"):
                borrowed[i] = e["replacement"]
    for i, rep in borrowed.items():
        lang[i] = lang.get(rep, "?")
    return lang


def load_state():
    st = load_json(IMG_STATE, None) or {}
    st.setdefault("version", 1)
    st.setdefault("items", {})
    st.setdefault("known", [])
    st.setdefault("pending", [])
    return st


def same_file(path, rec):
    try:
        if os.path.getsize(path) != rec.get("size"):
            return False
        if abs(os.path.getmtime(path) - rec.get("mtime", 0)) < 2:
            return True
        with open(path, "rb") as f:
            if sha1hex(f.read()) == rec.get("sha1"):
                rec["mtime"] = os.path.getmtime(path)
                return True
    except OSError:
        pass
    return False


def sprite_kind(sprite, cid):
    if sprite == cid:
        return "base"
    if sprite == cid + "-Errata":
        return "errata"
    return "alt"


def collect_targets(sprites, st, lang, include_missing):
    """回傳 [(卡圖名, 卡號, 來由)]。來由:local=本機是日文/英文圖、missing=缺圖、recheck=已用普通版代替的異圖。"""
    items = st["items"]
    out = []
    for s, cid in sorted(sprites.items()):
        p = card_path(s)
        rec = items.get(s)
        if os.path.exists(p):
            if rec and rec.get("installed"):
                if same_file(p, rec):
                    if rec.get("kind") == "fallback" and os.path.exists(backup_path(s)):
                        out.append((s, cid, "recheck"))
                    continue
                # 換上的中文圖被別的程式改掉了(例如遊戲判定無法讀取而重新下載):重試,最多兩次
                rec["overwritten"] = rec.get("overwritten", 0) + 1
                rec["installed"] = False
                if rec["overwritten"] > 2:
                    continue
            elif lang.get(s) == "zh-CN":
                continue
            out.append((s, cid, "local"))
        elif include_missing or s in st["pending"]:
            out.append((s, cid, "missing"))
    return out


# ---------------------------------------------------------------------------- 卡圖:插畫比對
def _open_rgb(path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    return im.convert("RGB")


def _gray_px(path):
    from PIL import Image
    try:
        box = Image.Resampling.BOX
    except AttributeError:
        box = Image.BOX
    g = _open_rgb(path).convert("L").resize((NW, NH), box)
    return list(g.tobytes())


def _vec(px, x0, y0, x1, y1):
    v = [px[y * NW + x] for y in range(y0, y1) for x in range(x0, x1)]
    m = sum(v) / len(v)
    v = [a - m for a in v]
    n = math.sqrt(sum(a * a for a in v)) or 1.0
    return [a / n for a in v]


def ref_vec(path):
    return _vec(_gray_px(path), RX0, RY0, RX1, RY1)


def cand_vecs(path):
    px = _gray_px(path)
    return [_vec(px, RX0 + dx, RY0 + dy, RX1 + dx, RY1 + dy)
            for dy in range(-SHIFT, SHIFT + 1) for dx in range(-SHIFT, SHIFT + 1)]


def ncc_best(rv, cvs):
    return max(sum(a * b for a, b in zip(rv, cv)) for cv in cvs)


def png_cache_path(url):
    return os.path.join(PNG_CACHE, hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ".png")


def download_all(urls, workers=6):
    """下載官方圖到暫存資料夾;回傳 {url: 路徑或 None}。"""
    from PIL import Image
    os.makedirs(PNG_CACHE, exist_ok=True)
    out = {}
    todo = []
    for u in urls:
        p = png_cache_path(u)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            out[u] = p
        else:
            todo.append(u)

    def one(u):
        p = png_cache_path(u)
        data = http_get(u, timeout=60)
        im = Image.open(io.BytesIO(data))
        im.verify()
        write_atomic(p, data)
        return p

    if todo:
        say(f"  下載官方簡中卡圖 {len(todo)} 張…")
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(one, u): u for u in todo}
            for fu in concurrent.futures.as_completed(futs):
                u = futs[fu]
                try:
                    out[u] = fu.result()
                except Exception as e:
                    out[u] = None
                    say(f"\n    下載失敗:{u}({e})")
                done += 1
                if done % 20 == 0 or done == len(todo):
                    print(f"\r    {done} / {len(todo)}", end="", flush=True)
        print(flush=True)
    return out


def url_key(u):
    """同一張官方圖可能出現在不同網域(source.windoent.com / *.myqcloud.com),以路徑辨識。"""
    return urllib.parse.urlparse(u).path.lower()


def local_sources(st):
    """本機已經有的官方簡中圖(卡圖包與先前換上的):官方網址 → 本機檔案。比對時直接用,不必重新下載。"""
    out = {}
    for fn in ("manifest.json", "alternate-manifest.json", "repair-manifest.json"):
        for e in load_json(os.path.join(ROOT, fn), []) or []:
            if e.get("language") == "zh-CN" and e.get("source") and e.get("id"):
                p = card_path(e["id"])
                if os.path.exists(p):
                    out[url_key(e["source"])] = p
    for s, rec in st["items"].items():
        if rec.get("installed") and rec.get("source") and os.path.exists(card_path(s)):
            out[url_key(rec["source"])] = card_path(s)
    return out


def to_webp(png_path):
    """官方圖 → 遊戲用的 WebP(RGB、有損 quality 90,與卡圖包相同的格式),並確認可以解碼。
    本來就是 WebP 的(卡圖包裡已轉好的官方圖)直接沿用,不再重新壓縮。"""
    from PIL import Image
    with open(png_path, "rb") as fh:
        head = fh.read(12)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        with open(png_path, "rb") as fh:
            data = fh.read()
        Image.open(io.BytesIO(data)).load()
        return data
    im = _open_rgb(png_path)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=90, method=4)
    data = buf.getvalue()
    if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise RuntimeError("WebP 格式不正確")
    chk = Image.open(io.BytesIO(data))
    chk.load()
    if chk.size != im.size:
        raise RuntimeError("WebP 解碼結果尺寸不符")
    return data


def run_images(sc_cards, gcards, include_missing=False, dry=False):
    st = load_state()
    lang = pack_languages()
    sprites = {}
    for c in gcards:
        sprites.setdefault(c["CardSpriteName"], c["CardID"])
    # 新版本新增的卡:即使還沒下載過也要補(第一次執行只記錄目前的清單)
    if st["known"]:
        new = sorted(set(sprites) - set(st["known"]))
        st["pending"] = sorted(set(st["pending"]) | set(new))
    st["known"] = sorted(sprites)
    st["pending"] = [s for s in st["pending"] if s in sprites]

    by_base = sc_by_base(sc_cards)
    targets = collect_targets(sprites, st, lang, include_missing)
    # 規劃:每個目標要比對哪些官方圖
    plan = []
    for s, cid, why in targets:
        ents = by_base.get(cid, [])
        rec = st["items"].get(s, {})
        if why == "recheck":
            ents = [e for e in ents if str(e["id"]) not in set(rec.get("compared", []))]
            if not ents:
                continue
            ref = backup_path(s)
        elif why == "local":
            ref = card_path(s)
        else:
            ref = None
        if not ents:
            plan.append((s, cid, why, ref, []))
            continue
        plan.append((s, cid, why, ref, ents))
    urls = set()
    for s, cid, why, ref, ents in plan:
        if ref:
            urls |= {e["imageCover"] for e in ents}
        elif ents:
            urls.add(pick_normal(cid, ents)["imageCover"])
    say(f"卡圖:需要處理 {len(plan)} 張(日文/英文 {sum(1 for p in plan if p[2] == 'local')}、"
        f"缺圖 {sum(1 for p in plan if p[2] == 'missing')}、異圖重新比對 {sum(1 for p in plan if p[2] == 'recheck')})")
    have = local_sources(st)
    files = {u: have[url_key(u)] for u in urls if url_key(u) in have}
    if files:
        say(f"  候選官方圖 {len(urls)} 張,其中 {len(files)} 張本機已有,不必下載")
    todo = sorted(u for u in urls if u not in files)
    files.update(download_all(todo) if todo else {})

    report = []
    stats = collections.Counter()
    cvec_cache = {}

    def cvs_of(url):
        if url not in cvec_cache:
            cvec_cache[url] = cand_vecs(files[url])
        return cvec_cache[url]

    groups = collections.defaultdict(list)
    for item in plan:
        groups[item[1]].append(item)
    for cid in sorted(groups):
        cvec_cache.clear()
        for s, _, why, ref, ents in groups[cid]:
            rec = st["items"].get(s, {})
            usable = [e for e in ents if files.get(e["imageCover"])]
            if not usable:
                stats["官方簡中還沒有"] += 1
                report.append({"sprite": s, "why": why, "decision": "none", "candidates": len(ents)})
                continue
            choice, score, kind, scores = None, None, None, []
            if ref and os.path.exists(ref):
                try:
                    rv = ref_vec(ref)
                except Exception as ex:
                    rv = None
                    say(f"  無法讀取原圖 {s}({ex}),改用普通版")
                if rv:
                    scores = sorted(((ncc_best(rv, cvs_of(e["imageCover"])), e) for e in usable),
                                    key=lambda t: -t[0])
                    best_s, best_e = scores[0]
                    second = scores[1][0] if len(scores) > 1 else None
                    if best_s >= ACCEPT or (best_s >= WEAK and (second is None or best_s - second >= WEAK_MARGIN)):
                        tied = [(sc, e) for sc, e in scores if sc >= best_s - TIE]
                        if len(tied) > 1:
                            # 同一張插畫有好幾個版本(一般/金框/WINNER 印章…):整張卡再比一次,挑最像的
                            whole = _vec(_gray_px(ref), 0, 0, NW, NH)
                            best_s, best_e = max(tied, key=lambda t: sum(a * b for a, b in zip(
                                whole, _vec(_gray_px(files[t[1]["imageCover"]]), 0, 0, NW, NH))))
                        choice, score, kind = best_e, best_s, "art"
            if choice is None:
                if why == "recheck":
                    stats["異圖仍沒有相符的中文版"] += 1
                    rec.setdefault("compared", [])
                    rec["compared"] = sorted(set(rec["compared"]) | {str(e["id"]) for e in usable})
                    continue
                normal = pick_normal(cid, usable)
                if normal is None:
                    stats["官方簡中還沒有"] += 1
                    continue
                choice = normal
                kind = "normal" if sprite_kind(s, cid) == "base" else "fallback"
                if scores:
                    score = next((sc for sc, e in scores if e is normal), None)
            stats[{"art": "插畫相符", "normal": "普通版", "fallback": "沒有同一張插畫,用中文普通版"}[kind]] += 1
            report.append({"sprite": s, "why": why, "decision": kind, "score": round(score, 4) if score is not None else None,
                           "sc": choice["model"], "url": choice["imageCover"],
                           "scores": [[round(sc, 4), e["model"], e["imageCover"]] for sc, e in scores[:4]]})
            if dry:
                continue
            try:
                data = to_webp(files[choice["imageCover"]])
            except Exception as ex:
                stats["轉檔失敗"] += 1
                say(f"  轉檔失敗 {s}({ex})")
                continue
            dst = card_path(s)
            if os.path.exists(dst) and not os.path.exists(backup_path(s)) and why != "recheck":
                os.makedirs(BACKUP, exist_ok=True)
                shutil.copy2(dst, backup_path(s))
            write_atomic(dst, data)
            st["items"][s] = {
                "installed": True, "kind": kind, "score": round(score, 4) if score is not None else None,
                "sc_id": choice["id"], "model": choice["model"], "source": choice["imageCover"],
                "size": len(data), "mtime": os.path.getmtime(dst), "sha1": sha1hex(data),
                "backup": os.path.exists(backup_path(s)), "at": now_iso(),
                "compared": sorted({str(e["id"]) for e in usable} | set(rec.get("compared", []))),
            }
            if s in st["pending"]:
                st["pending"].remove(s)
    save_json(REPORT, {"at": now_iso(), "dry_run": dry, "stats": dict(stats), "items": report}, indent=1)
    if not dry:
        save_json(IMG_STATE, st, indent=1)
        shutil.rmtree(PNG_CACHE, ignore_errors=True)
    for k, v in stats.most_common():
        say(f"  {k}: {v}")
    return stats


def restore_images():
    st = load_state()
    n = 0
    for s, rec in st["items"].items():
        if not rec.get("installed"):
            continue
        dst, b = card_path(s), backup_path(s)
        if os.path.exists(b):
            with open(b, "rb") as f:
                write_atomic(dst, f.read())
        elif os.path.exists(dst):
            os.remove(dst)                      # 原本沒有這張圖:刪掉,遊戲需要時會自己下載
        rec["installed"] = False
        n += 1
    save_json(IMG_STATE, st, indent=1)
    say(f"已還原 {n} 張卡圖。")


# ---------------------------------------------------------------------------- 卡片文字
def clean_sc_text(s):
    if not s or str(s).strip() in ("-", "None"):
        return ""
    s = str(s).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"(?<![A-Za-z])enter(?![A-Za-z])[ \t]*\n?", "\n", s)     # 官方資料用 enter 表示換行
    lines = [l.strip() for l in s.split("\n")]
    return "\n".join(l for l in lines if l)


def make_tc():
    import opencc
    cc = opencc.OpenCC("s2tw")

    def tc(s):
        t = cc.convert(s)
        t = t.replace("回閤", "回合")                                       # OpenCC 把「本回合中」誤轉成「本回閤中」
        t = re.sub(r"(\d)只", r"\1隻", t).replace("的只數", "的隻數")       # 量詞:1只數碼寶貝 → 1隻
        t = t.replace("卡組", "牌組").replace("《迴避》", "《回避》").replace("《昇天》", "《升天》")   # 與對戰文字的用詞一致
        t = t.replace("鏈接", "連結").replace("我放的回合", "我方的回合")             # 用詞一致;官方資料的錯字
        t = t.replace("≪", "《").replace("≫", "》").replace("‼", "!!")             # 字型沒有這幾個符號
        t = re.sub(r"“([^“”\n]{1,40}?)[”“]", r"「\1」", t)                 # “名稱” → 「名稱」
        return t
    return tc


def split_traits(s):
    s = clean_sc_text(s).replace("\n", "/")
    return [p.strip() for p in re.split(r"[/／]", s) if p.strip() and p.strip() != "-"] if s else []


def _num(s):
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else None


def validate(card, e):
    """確認官方簡中這筆資料就是這張卡(卡別、等級、DP、費用);回傳不符的項目。"""
    bad = []
    kind = card["cardKind"][0] if card["cardKind"] else None
    if kind in KIND_ZH and e.get("belongsType") and e["belongsType"] != KIND_ZH[kind]:
        bad.append("卡別")
    if kind in ("Digimon", "DigiEgg") and _num(e.get("cardLevel")) is not None and _num(e["cardLevel"]) != card["Level"]:
        bad.append("等級")
    if kind == "Digimon" and _num(e.get("dp")) is not None and _num(e["dp"]) != card["DP"]:
        bad.append("DP")
    if kind != "DigiEgg" and _num(e.get("entryConsumeValue")) is not None and _num(e["entryConsumeValue"]) != card["PlayCost"]:
        bad.append("費用")
    return bad


def build_text(sc_cache, gcards):
    tc = make_tc()
    by_base = sc_by_base(sc_cache["cards"])
    import zh_glossary
    try:
        gloss = zh_glossary.names()
    except Exception:
        gloss = {}
    out_cards, rejected, stat_diff = {}, {}, {}
    votes = {k: collections.defaultdict(collections.Counter) for k in ("form", "attribute", "type")}
    name_diff = []
    seen = set()
    for c in gcards:
        cid = c["CardID"]
        if cid in seen:
            continue
        seen.add(cid)
        ents = by_base.get(cid, [])
        if not ents:
            continue
        e = pick_normal(cid, ents)
        bad = validate(c, e)
        if bad:
            others = [x for x in ents if not validate(c, x)]
            if others:
                e, bad = pick_normal(cid, others), []
        if "卡別" in bad:
            rejected[cid] = f"{e.get('model')}:{'/'.join(bad)}不符"
            continue
        if bad:
            # 卡號、卡別相同,只有等級/DP/費用不同(兩邊資料其中一方有誤或勘誤):仍是同一張卡,記錄下來
            stat_diff[cid] = f"{e.get('model')}:{'/'.join(bad)}不同"
        rec = {
            "sc": e.get("model"),
            "name": tc(clean_sc_text(e.get("name"))),
            "effect": tc(clean_sc_text(e.get("effect"))),
            "inherited": tc(clean_sc_text(e.get("envolutionEffect"))),
            "security": tc(clean_sc_text(e.get("safeEffect"))),
        }
        for fld, key in (("Form", "form"), ("Attribute", "attribute"), ("Type", "type")):
            zh = [tc(x) for x in split_traits(e.get(key))]
            rec[key] = zh
            eng = c[f"{fld}_ENG"]
            if zh and len(zh) == len(eng):
                for a, b in zip(eng, zh):
                    votes[key][a][b] += 1
        out_cards[cid] = rec
        g = gloss.get(c["CardName_ENG"]) if isinstance(gloss, dict) else None
        if g and rec["name"] and g != rec["name"]:
            name_diff.append([c["CardName_ENG"], g, rec["name"]])
    traits = {k: {eng: cnt.most_common(1)[0][0] for eng, cnt in v.items()} for k, v in votes.items()}
    data = {"version": 1, "generated_at": now_iso(), "sc_fetched_at": sc_cache.get("fetched_at"),
            "cards": out_cards, "traits": traits, "rejected": rejected, "stat_diff": stat_diff}
    return data, name_diff


def run_text(sc_cache, gcards):
    try:
        import opencc  # noqa: F401
    except Exception:
        say("卡片文字:沒有安裝簡繁轉換套件 OpenCC,這次略過(請用啟動檔重新執行,會自動安裝)。")
        return None
    data, name_diff = build_text(sc_cache, gcards)
    old = load_json(TEXT_OUT, None)
    same = old is not None and {k: v for k, v in old.items() if k != "generated_at"} == \
        {k: v for k, v in data.items() if k != "generated_at"}
    if not same:
        save_json(TEXT_OUT, data)
    ids = {c["CardID"] for c in gcards}
    say(f"卡片文字:{len(ids)} 個卡號中,官方簡中有 {len(data['cards'])} 個"
        + (f"(另有 {len(data['rejected'])} 個資料不符而略過)" if data["rejected"] else "")
        + ("" if same else ",已更新"))
    if name_diff:
        save_json(os.path.join(WORK, "name_diff.json"), name_diff, indent=1)
    return data


# ---------------------------------------------------------------------------- 主程式
def run(include_missing=False, force=False, dry=False, images=True, text=True):
    sc_cache, fresh = fetch_sc(force)
    if not sc_cache:
        say("卡片中文化:沒有官方簡中卡表的資料,略過。")
        return False
    say(f"官方簡中卡表:{sc_cache['count']} 筆(取得時間 {sc_cache['fetched_at'].replace('T', ' ')})")
    gcards = game_cards()
    if images and os.path.isdir(os.path.dirname(CARD_DIR)):
        run_images(sc_cache["cards"], gcards, include_missing=include_missing, dry=dry)
    if text and not dry:
        run_text(sc_cache, gcards)
    return True


def main():
    a = sys.argv[1:]
    if "--restore" in a:
        restore_images()
        return 0
    ok = run(include_missing="--all" in a, force="--refresh" in a, dry="--dry-run" in a,
             images="--text-only" not in a, text="--images-only" not in a)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
