# -*- coding: utf-8 -*-
"""C# 原始碼分析:找出每個字串常值出現在哪個呼叫的第幾個參數,判斷它是「只用來顯示」還是會被程式拿去比對。

與第二版翻譯時使用的分類規則相同(提示 prompt / 效果名稱 name / 效果說明 desc / 時機詞 tag / 其他 skip:* 與 unknown:*)。
只有全部出現處都屬於顯示用途(prompt/name/desc/tag)的字串才可以翻譯。

用法(命令列):
  python zh_source.py <Assets/Scripts 資料夾> <輸出 json>
"""
import collections
import json
import os
import re
import sys

# ---------------------------------------------------------------- 呼叫端分類表(與第二版相同)
PROMPT = set()
for _cal in ("SetUpCustomMessage",):
    for _i in range(6):
        PROMPT.add((_cal, _i))
# Assembly/DigiXros/Jogress 條件的 selectMessage 會被 CardSource.HasText 當作卡片文字搜尋,不可翻譯,故不列入。
PROMPT |= {("SetUpCustomMessage_ShowCard", 0), ("SetUpCustomBackButtonMessage", 0),
           ("SetUp", "message"), ("SetUp", "Message"), ("SetUp", "Message_Enemy"),
           ("SelectionElement<bool>", "message"), ("SelectionElement<int>", "message"),
           ("SelectionElement<bool>", 0), ("SelectionElement<int>", 0),
           ("SimplifiedSelectCardConditionClass", "message"), ("SelectCardConditionClass", "message"),
           ("new", "message"),
           ("SetIntSelection", "selectPlayerMessage"), ("SetIntSelection", "notSelectPlayerMessage"),
           ("SetBoolSelection", "selectPlayerMessage"), ("SetBoolSelection", "notSelectPlayerMessage"),
           ("BurstDigivolutionCondition", "selectTamerMessage"), ("BurstDigivolutionCondition", "selectDigimonMessage"),
           ("OpenSelectCardPanel", "Message"), ("OpenSelectCardPanel", "NotSelectButtonMessage"), ("OpenSelectCardPanel", "EndSelectButtonMessage"),
           ("ShowCardEffect", 1), ("ShowCardEffect2", 1),
           ("OpenCommandText", 0), ("SetUpActiveYesNoObject", 2),
           ("customPermanentMessageArrayTemplate", "customText"),
           ("SelectTrashDigivolutionCards", "selectString"), ("DetachSelfEffect", "conditionString"),
           }
NAME = {("SetUpICardEffect", 0), ("SetEffectName", 0)}
DESC = {("SetEffectDiscription", 0), ("SetUpActivateClass", 4), ("AddDetailClass", 1), ("AddDetailClass", 2),
        ("StaticAddDetailClass", 2), ("PlayMindLinkTamerFromDigivolutionCards", 2)}
_CLASS_FACTORY = re.compile(r"^(When|Start|End|On|Counter|Security)\w*Class$")
_GAIN_NAME4 = re.compile(r"^(Gain|CanNot|Cant)\w*$")
TAG = set()
for _cal in ("SharedEffectDescription", "SharedEffectDiscription", "EffectDiscriptionShared", "EffectDescriptionShared",
             "SharedEffectDescription1", "EffectDescription", "EffectDiscription", "FirstEffectDiscription",
             "SecondEffectDiscription", "PlayDigimonEffectDescription", "MinusDPEffectDescription", "DPReductionEffectDescription",
             "effectDescription", "AllTurnsEffectDescription"):
    TAG.add((_cal, 0))
COMPARE_CALLEES = {"Contains", "EqualsTraits", "ContainsCardName", "EqualsCardName", "ContainsTraits", "HasText", "Replace",
                   "ContainsKey", "Find", "StartsWith", "EndsWith", "IndexOf", "LastIndexOf", "Equals", "Exists", "Some", "Where",
                   "TryGetValue", "Remove", "Split", "CardLimitCount", "EqualsCardNameDigiXros", "Join", "AllIndexesOf", "Count",
                   "Any", "All", "FindIndex", "Combine", "Compare", "CompareTo", "CompareTag", "Trim", "TrimStart", "TrimEnd", "Insert",
                   "CanActivateSelfOnDeletionWithContainingCardName", "CanActivateSelfOnDeletionWithContainingTrait",
                   "BannedPair", "if()", "while()", "switch()", "ContainsTraitsJustBefore"}
IDENT_CALLEES = {"SetHashString", "StringToHash", "SetInteger", "SetFloat", "SetBool", "GetInteger", "GetFloat", "GetString", "SetString",
                 "HasKey", "RPC", "LoadScene", "LoadSceneAsync", "UnloadSceneAsync", "GetSceneByName", "NameToLayer", "Header",
                 "CreateAssetMenu", "AddComponentMenu", "Tooltip", "Obsolete", "GetStreamingAssetPath", "OpenURL", "WriteAllText",
                 "WriteAllBytes", "StreamWriter", "GameObject", "JoinRoom", "CreateRoom", "GetSprite", "GetDeckCode", "Invoke",
                 "GetType", "InvalidOperationException", "ArgumentException", "Format", "Append", "StartLoading", "SetPlayText",
                 "ActivateClassesForSharedEffects", "SetFace", "ToString", "Label", "Box", "Add", "Move"}
DEBUG_CALLEES = {"Log", "LogError", "LogWarning", "Assert", "WriteLine", "Write"}
NAME_RE = re.compile(r"(?i)effect_?name|effectname")
DESC_RE = re.compile(r"(?i)descri?ption|discri?ption")
MSG_RE = re.compile(r"(?i)message|msg")
KEYWORDS = {"if", "while", "switch", "for", "foreach", "catch", "using", "lock", "return", "typeof", "nameof", "sizeof",
            "default", "checked", "unchecked", "when", "fixed", "base", "this", "await", "throw", "in", "is", "as", "out", "ref"}


# 組裝 / 數碼合體 / 合步進化的條件文字(selectMessage)會被 CardSource.HasText 當成卡片文字搜尋 → 不可翻譯
HASTEXT_CALLEES = re.compile(r"^(Assembly|DigiXros|Jogress)\w*(Condition|ConditionElement)$")


def occ_kind(o):
    cal = o.get("callee")
    key = (cal, o["named"] if o.get("named") else o.get("idx"))
    if cal and HASTEXT_CALLEES.match(cal):
        return "skip:hastext", cal
    pre_tail = o.get("pre", "").rstrip()
    if re.search(r"\.\s*[sS]electMessage\s*=\s*\$?@?$", pre_tail):
        return "skip:hastext", "selectMessage="
    if cal:
        nm = o.get("named")
        if key in PROMPT:
            return "prompt", "sink"
        if key in NAME:
            return "name", "sink"
        if key in DESC:
            return "desc", "sink"
        if _CLASS_FACTORY.match(cal or "") and key[1] == 1:
            return "name", "sink:classfactory"
        if _CLASS_FACTORY.match(cal or "") and key[1] == 3:
            return "desc", "sink:classfactory"
        if _GAIN_NAME4.match(cal or "") and key[1] == 4 and not o.get("named"):
            return "name", "sink:gain#4"
        if key in TAG:
            return "tag", "sink"
        if cal in DEBUG_CALLEES:
            return "skip:debug", cal
        if cal in COMPARE_CALLEES:
            return "skip:compare", cal
        if cal in IDENT_CALLEES:
            return "skip:ident", cal
        if nm:
            if NAME_RE.search(nm):
                return "name", f"named:{nm}"
            if DESC_RE.search(nm):
                return "desc", f"named:{nm}"
            if MSG_RE.search(nm):
                return "prompt", f"named:{nm}"
            if nm in ("hashValue", "hashstring", "hashString", "trait", "cardName", "name"):
                return "skip:ident", f"named:{nm}"
        return "unknown:call", f"{cal}#{nm if nm else o.get('idx')}"
    pre = o["pre"].rstrip()
    m = re.search(r"(return|=>|==|!=|=|\?|:|\+|case|\{|,)\s*\$?@?$", pre)
    tail = m.group(1) if m else ""
    func = o.get("func", "")
    if tail in ("return", "=>"):
        if DESC_RE.search(func):
            return "desc", f"func:{func}"
        if NAME_RE.search(func):
            return "name", f"func:{func}"
        return "unknown:ret", func
    if tail == "=":
        mv = re.search(r"([A-Za-z_]\w*)\s*$", pre[:len(pre) - 1].rstrip())
        var = mv.group(1) if mv else ""
        if DESC_RE.search(var):
            return "desc", f"var:{var}"
        if NAME_RE.search(var):
            return "name", f"var:{var}"
        if MSG_RE.search(var):
            return "prompt", f"var:{var}"
        return "unknown:assign", var
    if tail in ("==", "!=", "case"):
        return "skip:compare", tail
    if "hashtable" in pre.lower()[-22:] and pre.endswith("["):
        return "skip:ident", "hashtable"
    if tail == "+":
        return "unknown:concat", ""
    return "unknown:other", tail


# ---------------------------------------------------------------- 掃描器
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
            if n == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6] or ""):
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


def read_string(src, i):
    """i 指向字串開頭(" 或 $ 或 @)。回傳 (end, text, interp, holes) 或 None。"""
    n = len(src)
    interp = verb = False
    if src.startswith('$@"', i) or src.startswith('@$"', i):
        interp = verb = True; k = i + 3
    elif src.startswith('$"', i):
        interp = True; k = i + 2
    elif src.startswith('@"', i):
        verb = True; k = i + 2
    elif src[i] == '"':
        k = i + 1
    else:
        return None
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
    text = raw if verb else decode_escapes(raw)
    if interp and holes == 0:
        text = text.replace("{{", "{").replace("}}", "}")
    return j + 1, text, interp, holes


def callee_before(src, i):
    """i 是 '(' 的位置,回傳呼叫名稱(含泛型參數,如 SelectionElement<bool>)。"""
    j = i - 1
    while j >= 0 and src[j].isspace():
        j -= 1
    gen = ""
    if j >= 0 and src[j] == ">":
        depth = 0
        k = j
        while k >= 0:
            if src[k] == ">":
                depth += 1
            elif src[k] == "<":
                depth -= 1
                if depth == 0:
                    break
            elif src[k] in ";{}()":
                return None
            k -= 1
        gen = re.sub(r"\s+", "", src[k:j + 1])
        j = k - 1
        while j >= 0 and src[j].isspace():
            j -= 1
    e = j + 1
    while j >= 0 and (src[j].isalnum() or src[j] == "_"):
        j -= 1
    name = src[j + 1:e]
    if not name or name[0].isdigit():
        return None
    if name in ("if", "while", "switch"):
        return name + "()"
    if name in KEYWORDS:
        return None
    return name + gen


def scan(src):
    """回傳出現處清單:dict(text, interp, holes, callee, idx, named, pre, post, func, line, start)"""
    n = len(src)
    occ = []
    stack = []   # frame: [opener, callee, idx, named, argstart, func]
    i = 0
    line = 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "#":
            ls = src.rfind("\n", 0, i) + 1
            if not src[ls:i].strip():
                j = src.find("\n", i)
                i = n if j < 0 else j
                continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        if c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                if src[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        if c == '"' or (c in "$@" and (src.startswith('$"', i) or src.startswith('@"', i) or src.startswith('$@"', i) or src.startswith('@$"', i))):
            r = read_string(src, i)
            end, text, interp, holes = r
            # 最內層的呼叫(中間若隔著 { } 區塊,視為不是直接參數)
            callee = idx = named = None
            func = ""
            for fr in reversed(stack):
                if fr[0] == "{":
                    break
                if fr[0] == "(":
                    callee, idx, named = fr[1], fr[2], fr[3]
                    break
            for fr in reversed(stack):
                if fr[0] == "{" and fr[5]:
                    func = fr[5]
                    break
            pre = src[max(0, i - 240):i]
            if pre.rstrip().endswith("=>"):
                m = re.search(r"([A-Za-z_]\w*)\s*\([^()]*\)\s*=>\s*$", pre)
                if m:
                    func = m.group(1)
            occ.append(dict(text=text.replace("\r\n", "\n"), interp=interp, holes=holes, callee=callee, idx=idx, named=named,
                            pre=pre, post=src[end:end + 100], func=func, line=line, start=i))
            line += src.count("\n", i, end)
            i = end
            continue
        if c == "(":
            stack.append(["(", callee_before(src, i), 0, None, i + 1, ""])
        elif c == "[":
            stack.append(["[", None, 0, None, i + 1, ""])
        elif c == "{":
            # 方法本體:'{' 前是 ')',且 ')' 對應的 '(' 前是非關鍵字的識別字
            fn = ""
            j = i - 1
            while j >= 0 and src[j].isspace():
                j -= 1
            if j >= 0 and src[j] == ")":
                depth = 0
                k = j
                while k >= 0:
                    if src[k] == ")":
                        depth += 1
                    elif src[k] == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    k -= 1
                nm = callee_before(src, k) if k >= 0 else None
                if nm and not nm.endswith("()"):
                    fn = re.sub(r"<.*$", "", nm)
            stack.append(["{", None, 0, None, i + 1, fn])
        elif c in ")]}":
            want = {")": "(", "]": "[", "}": "{"}[c]
            while stack and stack[-1][0] != want:
                stack.pop()
            if stack:
                stack.pop()
        elif c == ",":
            if stack and stack[-1][0] in "([":
                stack[-1][2] += 1
                stack[-1][3] = None
                stack[-1][4] = i + 1
        elif c == ":":
            if stack and stack[-1][0] == "(" and not (i + 1 < n and src[i + 1] == ":"):
                seg = src[stack[-1][4]:i]
                m = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*", seg)
                if m:
                    stack[-1][3] = m.group(1)
        i += 1
    return occ


def analyze(scripts_dir, rel_filter=None):
    """回傳 occurrences(全部)與 units(依字串彙總的種類)"""
    occs = []
    for dp, dn, fn in os.walk(scripts_dir):
        for f in fn:
            if not f.endswith(".cs"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, scripts_dir)
            if rel_filter and rel not in rel_filter:
                continue
            src = open(p, "rb").read().decode("utf-8", "replace")
            for o in scan(src):
                o["file"] = rel
                k, why = occ_kind(o)
                o["kind"], o["why"] = k, why
                del o["start"]
                occs.append(o)
    return occs


def units_of(occs):
    per = collections.defaultdict(lambda: {"kinds": collections.Counter(), "occ": 0, "interp": 0, "concat": 0, "ex": []})
    for o in occs:
        u = per[o["text"]]
        u["kinds"][o["kind"]] += 1
        u["occ"] += 1
        if o["interp"]:
            u["interp"] += 1
        if re.search(r"\+\s*\$?@?$", o["pre"]) or re.match(r"\s*\+", o["post"]):
            u["concat"] += 1
        if len(u["ex"]) < 3:
            u["ex"].append(f"{o['file']}:{o['line']} {o['callee']}#{o['named'] or o['idx']}")
    return {t: dict(kinds=dict(u["kinds"]), occ=u["occ"], interp=u["interp"], concat=u["concat"], ex=u["ex"]) for t, u in per.items()}


def is_display(kinds):
    ks = set(kinds)
    return bool(ks) and ks <= {"desc", "name", "prompt", "tag"}


if __name__ == "__main__":
    occs = analyze(sys.argv[1])
    json.dump(units_of(occs), open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
    c = collections.Counter()
    for o in occs:
        c[o["kind"]] += 1
    print(len(occs), "occurrences", c.most_common())
