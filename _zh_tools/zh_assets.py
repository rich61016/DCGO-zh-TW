# -*- coding: utf-8 -*-
"""建置與驗證共用:路徑設定、依名稱找物件(不寫死物件編號,遊戲改版後也能找到)。"""
import glob
import os
import struct
import sys

import UnityPy

S = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(S)
DEST_ROOT = os.environ.get("ZH_DEST", ROOT)                       # 要寫入中文化結果的遊戲根目錄(含 Game/)
ORIG_ROOT = os.environ.get("ZH_ORIG", os.path.join(S, "pristine"))  # 官方原檔(相對 Game/ 的路徑結構)
DEST = os.path.join(DEST_ROOT, "Game", "DCGO_Data")

LOCALIZED = ["sharedassets0.assets", "resources.assets", "level0", "level1", "sharedassets1.assets",
             "sharedassets2.assets", "il2cpp_data/Metadata/global-metadata.dat"]   # 相對 DCGO_Data/
CARD_TEXT = os.path.join(S, "cards", "card_text_zh.json")        # zh_cards.py 產生的卡片文字(繁中)

FONT_NAME = "LiberationSans"                          # 內容換成 PingFang TC 的 Font(後備字型的來源)
FALLBACK_NAME = "LiberationSans SDF - Fallback"       # 動態後備 TMP_FontAsset
TMP_SETTINGS_NAME = "TMP Settings"


def orig(rel):
    """官方原檔的路徑:中文化會改動的檔案一律取 pristine;其餘檔案未被改動,直接讀遊戲資料夾。"""
    p = os.path.join(ORIG_ROOT, "DCGO_Data", rel)
    if rel in LOCALIZED:
        if not os.path.exists(p):
            raise FileNotFoundError(f"找不到官方原檔 {p}(請先執行 zh_update.py 下載)")
        return p
    return p if os.path.exists(p) else os.path.join(DEST, rel)


def load_file(path):
    env = UnityPy.load(path)
    return list(env.files.values())[0]


def script_map():
    f = load_file(orig("globalgamemanagers.assets"))
    return {pid: o.read().m_ClassName for pid, o in f.objects.items() if o.type.name == "MonoScript"}


def mb_name(raw):
    """MonoBehaviour 的 m_Name(位於 m_GameObject、m_Enabled、m_Script 之後)"""
    if len(raw) < 32:
        return None
    nl = struct.unpack_from("<i", raw, 28)[0]
    if not 0 <= nl <= 512 or 32 + nl > len(raw):
        return None
    try:
        return raw[32:32 + nl].decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_mb(f, name):
    hits = [pid for pid, o in f.objects.items() if o.type.name == "MonoBehaviour" and mb_name(o.get_raw_data()) == name]
    if len(hits) != 1:
        raise RuntimeError(f"找不到唯一的 MonoBehaviour「{name}」(找到 {len(hits)} 個)")
    return hits[0]


def find_named(f, type_name, name):
    hits = []
    for pid, o in f.objects.items():
        if o.type.name != type_name:
            continue
        try:
            nm = o.peek_name()
        except Exception:
            nm = o.read_typetree().get("m_Name")
        if nm == name:
            hits.append(pid)
    if len(hits) != 1:
        raise RuntimeError(f"找不到唯一的 {type_name}「{name}」(找到 {len(hits)} 個)")
    return hits[0]


def ext_names(f):
    out = []
    for e in (f.externals or []):
        nm = getattr(e, "name", None) or getattr(e, "path", None) or str(e)
        out.append(os.path.basename(str(nm)))
    return out


def pingfang_path():
    """系統的 PingFang.ttc(macOS 更新後路徑可能改變,所以用搜尋的)。"""
    cands = glob.glob("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*.asset/AssetData/PingFang.ttc")
    cands += glob.glob("/System/Library/Fonts/PingFang.ttc") + glob.glob("/Library/Fonts/PingFang.ttc")
    if not cands:
        raise FileNotFoundError("找不到系統字型 PingFang.ttc")
    return sorted(cands, key=os.path.getmtime)[-1]


# ---------------------------------------------------------------- 中文字型(跨平台)
# 一律使用「使用者自己電腦上的系統字型」,在建置時抽出內嵌,不隨工具散布:
#   macOS   → 蘋方-繁 PingFang TC Regular
#   Windows → 微軟正黑體 Microsoft JhengHei Regular
# 也可用環境變數 ZH_FONT 指定其他字型檔(.ttf/.otf/.ttc),ZH_FONT_FACE 指定 .ttc 裡的字型家族名稱。
REGULAR = {"Regular", "Normal", "Book", "標準", "常規", "Medium"}


def name_records(fb):
    """回傳 {nameID: set(所有語言的名稱)}(ttf_util.font_names 只取第一筆,這裡全取)。"""
    import ttf_util as T
    t = T._tables(fb)
    out = {}
    if "name" not in t:
        return out
    off, _ = t["name"]
    fmt, count, str_off = struct.unpack_from(">HHH", fb, off)
    for i in range(count):
        pid, eid, lid, nid, length, o = struct.unpack_from(">6H", fb, off + 6 + i * 12)
        raw = fb[off + str_off + o: off + str_off + o + length]
        try:
            s = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("mac_roman")
        except Exception:
            continue
        out.setdefault(nid, set()).add(s.strip())
    return out


def face_count(path):
    with open(path, "rb") as fh:
        head = fh.read(12)
    return struct.unpack_from(">I", head, 8)[0] if head[:4] == b"ttcf" else 1


def pick_face(path, families, postscript=None):
    """從字型檔(單一字型或 .ttc)挑出指定家族的 Regular 字型面,回傳獨立的字型位元組。"""
    import ttc_extract as TX
    with open(path, "rb") as fh:
        is_ttc = fh.read(4) == b"ttcf"
    n = face_count(path)
    faces = []
    for i in range(n):
        if is_ttc:
            fb = TX.extract_face(path, i)
        else:
            with open(path, "rb") as fh:
                fb = fh.read()
        nm = name_records(fb)
        faces.append((fb, nm))
        if postscript and postscript in nm.get(6, set()):
            return fb
    for fb, nm in faces:
        if nm.get(1, set()) & set(families) and (nm.get(2, set()) & REGULAR or not nm.get(2)):
            return fb
    for fb, nm in faces:
        if nm.get(1, set()) & set(families):
            return fb
    if n == 1 and not families:
        return faces[0][0]
    raise RuntimeError(f"{path} 裡找不到字型家族 {families}")


def cjk_font():
    """回傳 (字型位元組, 家族名稱)。"""
    override = os.environ.get("ZH_FONT")
    if override:
        fam = os.environ.get("ZH_FONT_FACE")
        fb = pick_face(override, [fam] if fam else [])
        family = fam or sorted(name_records(fb).get(1, {"Custom"}))[0]
        return fb, family
    if sys.platform == "darwin":
        return pick_face(pingfang_path(), ["PingFang TC"], postscript="PingFangTC-Regular"), "PingFang TC"
    if os.name == "nt":
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for fn in ("msjh.ttc", "msjh.ttf"):
            p = os.path.join(fonts, fn)
            if os.path.exists(p):
                return pick_face(p, ["Microsoft JhengHei", "微軟正黑體"]), "Microsoft JhengHei"
        raise FileNotFoundError("找不到微軟正黑體(C:\\Windows\\Fonts\\msjh.ttc)。可用環境變數 ZH_FONT 指定其他繁體中文字型檔。")
    raise RuntimeError("不支援的作業系統;請用環境變數 ZH_FONT 指定繁體中文字型檔")


def pingfang_tc_regular():
    """(舊名稱,保留相容)"""
    return pick_face(pingfang_path(), ["PingFang TC"], postscript="PingFangTC-Regular")
