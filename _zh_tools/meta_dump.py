"""IL2CPP global-metadata.dat (v29-31) 唯讀解析器:倒出字串常值表。"""
import json
import struct
import sys

SECTIONS = [
    "stringLiteral", "stringLiteralData", "string", "events", "properties", "methods",
    "parameterDefaultValues", "fieldDefaultValues", "fieldAndParameterDefaultValueData",
    "fieldMarshaledSizes", "parameters", "fields", "genericParameters",
    "genericParameterConstraints", "genericContainers", "nestedTypes", "interfaces",
    "vtableMethods", "interfaceOffsets", "typeDefinitions", "images", "assemblies",
    "fieldRefs", "referencedAssemblies", "attributeData", "attributeDataRange",
    "unresolvedIndirectCallParameterTypes", "unresolvedIndirectCallParameterRanges",
    "windowsRuntimeTypeNames", "windowsRuntimeStrings", "exportedTypeDefinitions",
]


def parse_header(buf):
    sanity, version = struct.unpack_from("<Ii", buf, 0)
    assert sanity == 0xFAB11BAF, hex(sanity)
    sec = {}
    for i, name in enumerate(SECTIONS):
        off, size = struct.unpack_from("<ii", buf, 8 + i * 8)
        sec[name] = (off, size)
    return version, sec


def load(path):
    buf = open(path, "rb").read()
    version, sec = parse_header(buf)
    return buf, version, sec


def literals(buf, sec):
    t_off, t_size = sec["stringLiteral"]
    d_off, d_size = sec["stringLiteralData"]
    n = t_size // 8
    out = []
    for i in range(n):
        length, data_index = struct.unpack_from("<Ii", buf, t_off + i * 8)
        raw = buf[d_off + data_index: d_off + data_index + length]
        out.append((i, length, data_index, raw))
    return out


if __name__ == "__main__":
    path = sys.argv[1]
    outp = sys.argv[2]
    buf, version, sec = load(path)
    print("version", version, "filesize", len(buf))
    prev_end = 0
    for name in SECTIONS:
        off, size = sec[name]
        print(f"  {name:42s} off={off:9d} size={size:9d} end={off+size:9d}")
    lits = literals(buf, sec)
    print("string literals:", len(lits))
    bad = 0
    with open(outp, "w", encoding="utf-8") as f:
        for i, length, di, raw in lits:
            try:
                s = raw.decode("utf-8")
            except UnicodeDecodeError:
                s = raw.decode("utf-8", "replace")
                bad += 1
            f.write(json.dumps({"i": i, "len": length, "di": di, "s": s}, ensure_ascii=False) + "\n")
    print("non-utf8 literals:", bad)
