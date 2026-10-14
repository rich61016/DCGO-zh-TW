"""共用:從 Unity 序列化檔中抽取/改寫 UI 文字(不依賴型別樹,依固定版面位移)。

版面(Unity 2021.3 / UGUI 1.0 / TMP 3.0.6,此遊戲實測):
  TextMeshProUGUI: m_OnCullStateChanged.calls 計數在 +84(須為 0),m_text 字串在 +88
  UnityEngine.UI.Text: 計數在 +84(須為 0),m_Text 字串在 +144
  LocalizeTMPro: +32 起 4 個 PPtr(48B)、+80 兩個 int(字級 ENG/JPN),+88 起 _text_ENG、_text_JPN
"""
import os
import struct

import UnityPy


def pad4(n):
    return (n + 3) & ~3


def read_str(raw, off):
    n = struct.unpack_from("<i", raw, off)[0]
    if n < 0 or off + 4 + n > len(raw):
        raise ValueError("bad string length")
    s = raw[off + 4: off + 4 + n].decode("utf-8")
    return s, off + 4 + pad4(n)


def pack_str(s):
    b = s.encode("utf-8")
    return struct.pack("<i", len(b)) + b + b"\x00" * (pad4(len(b)) - len(b))


class Project:
    """載入整個 DCGO_Data 並提供取得腳本類別、GameObject 路徑等輔助。"""

    def __init__(self, data_dir):
        self.env = UnityPy.load(data_dir)
        self.files = {os.path.basename(k): v for k, v in self.env.files.items()}
        gm = self.files["globalgamemanagers.assets"]
        self.scripts = {}
        for o in gm.objects.values():
            if o.type.name == "MonoScript":
                d = o.read()
                self.scripts[o.path_id] = d.m_ClassName
        self._cls_cache = {}

    def cls_of(self, o):
        raw = o.get_raw_data()
        fid, pid = struct.unpack_from("<iq", raw, 16)
        return self.scripts.get(pid, f"?{pid}")

    # ----- GameObject / Transform 解析 -----
    @staticmethod
    def parse_go(raw):
        n = struct.unpack_from("<i", raw, 0)[0]
        comps = []
        off = 4
        for _ in range(n):
            fid, pid = struct.unpack_from("<iq", raw, off)
            comps.append((fid, pid))
            off += 12
        layer = struct.unpack_from("<I", raw, off)[0]
        off += 4
        name, off = read_str(raw, off)
        return comps, layer, name

    @staticmethod
    def parse_transform_father(raw):
        # m_GameObject(12) + rot(16) + pos(12) + scale(12) = 52
        cnt = struct.unpack_from("<i", raw, 52)[0]
        off = 56 + 12 * cnt
        fid, pid = struct.unpack_from("<iq", raw, off)
        return pid

    def build_paths(self, fname):
        """回傳 {GameObject pid: 'Root/Child/.../Name'},以及 {component pid: GameObject pid}。"""
        f = self.files[fname]
        go_name, go_comps, tr_of_go, father_of_tr, go_of_tr = {}, {}, {}, {}, {}
        for pid, o in f.objects.items():
            t = o.type.name
            if t == "GameObject":
                comps, layer, name = self.parse_go(o.get_raw_data())
                go_name[pid] = name
                go_comps[pid] = comps
            elif t in ("Transform", "RectTransform"):
                raw = o.get_raw_data()
                fid, gopid = struct.unpack_from("<iq", raw, 0)
                tr_of_go[gopid] = pid
                go_of_tr[pid] = gopid
                try:
                    father_of_tr[pid] = self.parse_transform_father(raw)
                except Exception:
                    father_of_tr[pid] = 0
        paths = {}

        def path_of(gopid, depth=0):
            if gopid in paths:
                return paths[gopid]
            nm = go_name.get(gopid, "?")
            tr = tr_of_go.get(gopid)
            fa = father_of_tr.get(tr, 0) if tr else 0
            if fa and fa in go_of_tr and depth < 60:
                p = path_of(go_of_tr[fa], depth + 1) + "/" + nm
            else:
                p = nm
            paths[gopid] = p
            return p

        for g in go_name:
            path_of(g)
        return paths

    # ----- 文字抽取 -----
    def iter_texts(self, fname):
        """產生 dict: kind, pid, go, text(s), 以及改寫所需的位移。"""
        f = self.files[fname]
        for pid, o in f.objects.items():
            if o.type.name != "MonoBehaviour":
                continue
            cn = self.cls_of(o)
            if cn not in ("TextMeshProUGUI", "Text", "LocalizeTMPro", "TextMeshPro"):
                continue
            raw = o.get_raw_data()
            fid, gopid = struct.unpack_from("<iq", raw, 0)
            rec = {"file": fname, "pid": pid, "cls": cn, "go": gopid, "size": len(raw)}
            try:
                if cn == "LocalizeTMPro":
                    eng, off = read_str(raw, 88)
                    jpn, off2 = read_str(raw, off)
                    fs_eng, fs_jpn = struct.unpack_from("<ii", raw, 80)
                    rec.update(eng=eng, jpn=jpn, fs_eng=fs_eng, fs_jpn=fs_jpn,
                               ok=(off2 == len(raw)))
                elif cn in ("TextMeshProUGUI", "TextMeshPro"):
                    calls = struct.unpack_from("<i", raw, 84)[0]
                    if calls != 0:
                        rec.update(text=None, ok=False, why=f"calls={calls}")
                    else:
                        t, _ = read_str(raw, 88)
                        rec.update(text=t, ok=True)
                else:  # Text
                    calls = struct.unpack_from("<i", raw, 84)[0]
                    if calls != 0:
                        rec.update(text=None, ok=False, why=f"calls={calls}")
                    else:
                        t, end = read_str(raw, 144)
                        rec.update(text=t, ok=(end == len(raw)))
            except Exception as e:
                rec.update(text=None, ok=False, why=str(e))
            yield rec
