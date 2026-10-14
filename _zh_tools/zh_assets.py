# -*- coding: utf-8 -*-
"""建置與驗證共用:路徑設定、依名稱找物件(不寫死物件編號,遊戲改版後也能找到)。"""
import glob
import os
import struct

import UnityPy

S = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(S)
DEST_ROOT = os.environ.get("ZH_DEST", ROOT)                       # 要寫入中文化結果的遊戲根目錄(含 Game/)
ORIG_ROOT = os.environ.get("ZH_ORIG", os.path.join(S, "pristine"))  # 官方原檔(相對 Game/ 的路徑結構)
DEST = os.path.join(DEST_ROOT, "Game", "DCGO_Data")

LOCALIZED = ["sharedassets0.assets", "resources.assets", "level0", "level1", "sharedassets1.assets",
             "il2cpp_data/Metadata/global-metadata.dat"]          # 相對 DCGO_Data/

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


def pingfang_tc_regular():
    """從系統 PingFang.ttc 抽出「PingFang TC Regular」字型面(依字型名稱尋找,不依賴順序)。"""
    import ttc_extract as TX
    import ttf_util as T
    path = pingfang_path()
    with open(path, "rb") as fh:
        head = fh.read(12)
    n = struct.unpack_from(">I", head, 8)[0]
    for i in range(n):
        fb = TX.extract_face(path, i)
        if T.font_names(fb).get(6) == "PingFangTC-Regular":
            return fb
    raise RuntimeError("PingFang.ttc 裡找不到 PingFangTC-Regular")
