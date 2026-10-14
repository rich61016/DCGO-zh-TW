"""極簡 C# 字串字面值抽取器:回傳每個字串的位置、內容(已解碼)與其所在的程式碼脈絡。

處理:// 與 /* */ 註解、"..." 與 @"..." 與 $"..." 與 $@"..."、字元常值。
插值字串 $"..{x}.." 會轉成格式樣式 "..{0}.."(依洞的順序編號),並標記 interp=True。
"""
import re

ESC = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", '"': '"', "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def decode_escapes(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in ESC:
                out.append(ESC[n]); i += 2; continue
            if n == "u" and i + 5 < len(s) + 0 and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6] or ""):
                out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
            if n == "U" and re.fullmatch(r"[0-9a-fA-F]{8}", s[i + 2:i + 10] or ""):
                out.append(chr(int(s[i + 2:i + 10], 16))); i += 10; continue
            if n == "x":
                m = re.match(r"[0-9a-fA-F]{1,4}", s[i + 2:])
                if m:
                    out.append(chr(int(m.group(0), 16))); i += 2 + len(m.group(0)); continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return "".join(out)


def lex_strings(src):
    """產生 (start, end, text, interp, verbatim) ,start/end 為原始碼中的索引。"""
    i, n = 0, len(src)
    res = []
    while i < n:
        c = src[i]
        # 前置處理指令(#region/#endregion/#if...)整行略過:#region 的說明文字常含單引號(如 Tamer's),
        # 若不略過會被當成字元常值,導致之後所有字串錯位。
        if c == "#":
            ls = src.rfind("\n", 0, i) + 1
            if not src[ls:i].strip():
                j = src.find("\n", i)
                i = n if j < 0 else j
                continue
        # 註解
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        # 字元常值
        if c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                if src[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        # 字串前綴
        interp = verb = False
        k = i
        if c == "$" or c == "@":
            if src.startswith('$@"', i) or src.startswith('@$"', i):
                interp = verb = True; k = i + 3
            elif src.startswith('$"', i):
                interp = True; k = i + 2
            elif src.startswith('@"', i):
                verb = True; k = i + 2
            else:
                i += 1
                continue
        elif c == '"':
            k = i + 1
        else:
            i += 1
            continue
        # 讀取字串本體
        buf = []
        holes = 0
        j = k
        while j < n:
            ch = src[j]
            if verb and ch == '"':
                if j + 1 < n and src[j + 1] == '"':
                    buf.append('"'); j += 2; continue
                break
            if not verb and ch == '"':
                break
            if not verb and ch == "\\":
                buf.append(src[j:j + 2]); j += 2; continue
            if interp and ch == "{":
                if j + 1 < n and src[j + 1] == "{":
                    buf.append("{{"); j += 2; continue
                # 跳過洞內表達式(處理巢狀括號與字串)
                depth = 1; j += 1
                while j < n and depth:
                    cj = src[j]
                    if cj == '"':
                        j += 1
                        while j < n and src[j] != '"':
                            if src[j] == "\\":
                                j += 1
                            j += 1
                    elif cj == "{":
                        depth += 1
                    elif cj == "}":
                        depth -= 1
                    j += 1
                buf.append("{%d}" % holes)
                holes += 1
                continue
            if interp and ch == "}" and j + 1 < n and src[j + 1] == "}":
                buf.append("}}"); j += 2; continue
            buf.append(ch); j += 1
        raw = "".join(buf)
        if verb:
            text = raw
        else:
            text = decode_escapes(raw)
        if interp:
            text = text.replace("{{", "{").replace("}}", "}") if holes == 0 else text
        res.append((i, j + 1, text, interp, verb))
        i = j + 1
    return res


def line_of(src, idx, _cache={}):
    key = id(src)
    if key not in _cache:
        _cache.clear()
        _cache[key] = [m.start() for m in re.finditer("\n", src)]
    import bisect
    return bisect.bisect_right(_cache[key], idx) + 1


if __name__ == "__main__":
    import sys
    s = open(sys.argv[1], encoding="utf-8-sig", errors="replace").read()
    for st, en, t, ip, vb in lex_strings(s):
        print(line_of(s, st), "I" if ip else " ", repr(t)[:110])
