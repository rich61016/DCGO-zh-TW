# -*- coding: utf-8 -*-
"""DCGO 繁中化版的自動更新器。

做的事(依序):
  1. 向官方更新伺服器(與官方啟動器相同:https://dcgo.online/PATCH)查詢最新版本與檔案清單。
  2. 逐一比對本機檔案的 SHA-1;有變動的檔案才下載(下載後驗證大小與雜湊)。
     中文化會改動的 6 個檔案,比對的是 _zh_tools/pristine/ 裡保存的「官方原檔」。
  3. 套用:一般檔案直接替換(舊檔先備份到 _zh_tools/backup/);中文化相關的官方原檔放進 pristine/。
  4. 重新套用中文化(build_zh.py),再用 verify_build.py 獨立驗證;驗證失敗就改放官方原檔(英文但可正常遊玩)。
  5. (--launch)啟動遊戲:macOS 用 Cyder;Windows 直接執行 Game\\DCGO.exe。

用法:
  python zh_update.py              檢查並更新到最新版,然後重新套用中文化
  python zh_update.py --check      只檢查有沒有新版本,不下載
  python zh_update.py --localize   不檢查更新,只重新套用中文化(例如翻譯表更新後)
  python zh_update.py --launch     完成後啟動遊戲(「啟動DCGO（自動更新）」.command / .bat 用的就是這個)
  python zh_update.py --version X  指定要同步到的版本(預設:伺服器上的最新版)
  python zh_update.py --english    緊急用:改放官方原檔(英文版),不改其他東西
"""
import base64
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)                       # 含 Game 資料夾的遊戲根目錄
GAME = os.path.join(ROOT, "Game")
REMOTE = "https://dcgo.online/PATCH"
PRISTINE = os.path.join(TOOLS, "pristine")          # 中文化會改動之檔案的官方原檔(目前安裝版本)
DOWNLOADS = os.path.join(TOOLS, "downloads")
BACKUP = os.path.join(TOOLS, "backup")
STATE = os.path.join(TOOLS, "zh_state.json")
PY = sys.executable
IS_WIN = os.name == "nt"

# 中文化會改寫的檔案(相對於 Game/)。其餘檔案必須與官方逐位元組相同。
LOCALIZED = [
    "DCGO_Data/sharedassets0.assets",
    "DCGO_Data/resources.assets",
    "DCGO_Data/level0",
    "DCGO_Data/level1",
    "DCGO_Data/sharedassets1.assets",
    "DCGO_Data/il2cpp_data/Metadata/global-metadata.dat",
]


def say(msg=""):
    print(msg, flush=True)


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


def sha1b64(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode().rstrip("=")


def P(base, rel):
    """官方清單的路徑用 / 分隔,轉成本機路徑。"""
    return os.path.join(base, *rel.split("/"))


CURL = shutil.which("curl")


def curl_json(url):
    if not CURL:
        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except Exception as ex:
            raise RuntimeError(f"無法連線到更新伺服器:{url}({ex})")
    out = subprocess.run([CURL, "-fsSL", "--retry", "3", "--retry-delay", "2", "--max-time", "60", url],
                         capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"無法連線到更新伺服器:{url}(curl 代碼 {out.returncode})")
    return json.loads(out.stdout.decode("utf-8-sig"))


def urllib_file(url, part, size):
    """沒有 curl 時的下載(支援續傳)。"""
    import urllib.request
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        mode = "ab" if have and r.status == 206 else "wb"
        done = have if mode == "ab" else 0
        with open(part, mode) as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                print(f"\r    {done / 1e6:7.1f} / {size / 1e6:.1f} MB", end="", flush=True)
    print()


def curl_file(url, dest, size):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    for attempt in range(1, 4):
        if not CURL:
            try:
                urllib_file(url, part, size)
                rc = 0
            except Exception as ex:
                say(f"    {ex}")
                rc = 1
        else:
            rc = subprocess.run([CURL, "-fL", "--retry", "3", "--retry-delay", "2", "-C", "-", "--progress-bar",
                                 "-o", part, url]).returncode
        if rc == 0 and os.path.exists(part) and os.path.getsize(part) == size:
            os.replace(part, dest)
            return
        if rc == 33 or (os.path.exists(part) and os.path.getsize(part) > size):   # 續傳失敗或檔案過大:重新下載
            try:
                os.remove(part)
            except FileNotFoundError:
                pass
        say(f"    下載不完整,重試({attempt}/3)…")
        time.sleep(2)
    raise RuntimeError(f"下載失敗:{url}")


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def game_running():
    if IS_WIN:
        # tasklist 的訊息會依系統語言輸出(中文版是 Big5),只解讀 ASCII 的程式名稱欄位
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DCGO.exe", "/FO", "CSV", "/NH"], capture_output=True)
        out = r.stdout.decode("ascii", "replace")
        return [l for l in out.splitlines() if l.lower().startswith('"dcgo.exe"')]
    r = subprocess.run(["pgrep", "-f", os.path.join(GAME, "DCGO.exe")], capture_output=True, text=True)
    return [p for p in r.stdout.split() if p.strip()]


def latest_version():
    idx = curl_json(f"{REMOTE}/Builds/builds_index.json")
    vs = idx.get("AvailableBuilds") or []
    if not vs:
        raise RuntimeError("伺服器的版本清單是空的")
    return max(vs, key=vtuple)


def plan_sync(version):
    """回傳 (定義, 需要下載的項目清單)。"""
    bd = curl_json(f"{REMOTE}/Builds/build_{version}.json")
    need = []
    for e in bd["Entries"]:
        rel = e["RelativePath"]
        p = P(PRISTINE, rel) if rel in LOCALIZED else P(GAME, rel)
        ok = os.path.exists(p) and os.path.getsize(p) == e["Size"] and sha1b64(p) == e["Hash"]
        if not ok:
            need.append(e)
    return bd, need


def download(version, need):
    total = sum(e["Size"] for e in need)
    say(f"需要下載 {len(need)} 個檔案,共 {total / 1e6:.1f} MB")
    base = os.path.join(DOWNLOADS, version)
    for i, e in enumerate(need, 1):
        rel = e["RelativePath"]
        dest = P(base, rel)
        if os.path.exists(dest) and os.path.getsize(dest) == e["Size"] and sha1b64(dest) == e["Hash"]:
            say(f"  [{i}/{len(need)}] {rel}(已下載過,略過)")
            continue
        say(f"  [{i}/{len(need)}] {rel}  {e['Size'] / 1e6:.1f} MB")
        url = f"{REMOTE}/Builds/{version}/Game/{rel}"
        curl_file(url, dest, e["Size"])
        if sha1b64(dest) != e["Hash"]:
            os.remove(dest)
            raise RuntimeError(f"檔案雜湊不符(可能下載損毀):{rel}")
    return base


def apply_files(version, need, base, old_version):
    """把下載好的檔案放到正確位置。一般檔案:舊檔備份後替換;中文化相關:放進 pristine。"""
    bdir = os.path.join(BACKUP, old_version or "unknown")
    for e in need:
        rel = e["RelativePath"]
        src = P(base, rel)
        if rel in LOCALIZED:
            dst = P(PRISTINE, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
            continue
        dst = P(GAME, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            b = P(bdir, rel)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(dst, b)
        os.replace(src, dst)


def literal_set(path):
    sys.path.insert(0, TOOLS)
    import meta_dump as md
    buf, _, sec = md.load(path)
    out = set()
    for _, _, _, raw in md.literals(buf, sec):
        try:
            out.add(raw.decode("utf-8"))
        except UnicodeDecodeError:
            pass
    return out


def report_new_strings(old_meta, version):
    """比較新舊官方 metadata,把新版本新增、且尚未翻譯的字串寫到 new_strings_<版本>.json(請 Claude 補翻時使用)。"""
    new_meta = P(PRISTINE, "DCGO_Data/il2cpp_data/Metadata/global-metadata.dat")
    if not (old_meta and os.path.exists(old_meta) and os.path.exists(new_meta)):
        return
    sys.path.insert(0, TOOLS)
    import zh_all
    old, new = literal_set(old_meta), literal_set(new_meta)
    added = sorted(s for s in new - old if s not in zh_all.ALL and re.search(r"[A-Za-z]{2,}.*\s", s))
    if added:
        out = os.path.join(TOOLS, f"new_strings_{version}.json")
        json.dump(added, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        say(f"\n這個版本新增了 {len(added)} 句尚未翻譯的程式文字(多半是新卡的對戰文字),目前會顯示英文。")
        say(f"清單已存到 {os.path.relpath(out, ROOT)};需要的話請 Claude 補翻。")


def prune_backups(keep):
    """只保留最近一次更新前的備份(以及第一次的中文化備份),避免越積越大。"""
    if not os.path.isdir(BACKUP):
        return
    for d in os.listdir(BACKUP):
        if d not in keep and not d.endswith("中文化"):
            shutil.rmtree(os.path.join(BACKUP, d), ignore_errors=True)


def install_pristine_into_game():
    """把官方原檔放回遊戲資料夾(英文,但與官方版本一致、可正常遊玩)。"""
    for rel in LOCALIZED:
        src = P(PRISTINE, rel)
        if os.path.exists(src):
            dst = P(GAME, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp-zh"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)


def sync_emergency_original():
    """遊戲資料夾裡的 global-metadata.dat.原版 是給使用者緊急還原用的,必須與目前版本的官方原檔一致。"""
    src = P(PRISTINE, "DCGO_Data/il2cpp_data/Metadata/global-metadata.dat")
    dst = P(GAME, "DCGO_Data/il2cpp_data/Metadata/global-metadata.dat.原版")
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp-zh"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)


def localize():
    """重建中文化並獨立驗證。成功回 True。"""
    env = dict(os.environ, ZH_ORIG=PRISTINE, ZH_DEST=ROOT)
    say("\n=== 重新套用中文化 ===")
    r = subprocess.run([PY, os.path.join(TOOLS, "build_zh.py")], env=env)
    if r.returncode != 0:
        say("✗ 中文化建置失敗")
        return False
    say("\n=== 獨立驗證 ===")
    r = subprocess.run([PY, os.path.join(TOOLS, "verify_build.py")], env=env)
    if r.returncode != 0:
        say("✗ 驗證沒有通過")
        return False
    return True


def find_cyder():
    for app in [os.path.expanduser("~/Desktop/Cyder.app"), "/Applications/Cyder.app", os.path.expanduser("~/Applications/Cyder.app")]:
        sh = os.path.join(app, "Contents/Resources/ogom-scripts/cyder_launcher.sh")
        eng = sorted(glob.glob(os.path.join(app, "Contents/Resources/engine-wine-*.tar.xz")))
        if os.path.exists(sh) and eng:
            return sh, eng[-1]
    return None, None


def launch():
    if game_running():
        say("遊戲已經在執行中。")
        return
    exe = os.path.join(GAME, "DCGO.exe")
    if IS_WIN:
        # Windows:遊戲本來就是 Windows 程式,直接執行(與這個視窗分離,關掉視窗不影響遊戲)
        subprocess.Popen([exe], cwd=GAME, close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
        say("已啟動遊戲。")
        return
    sh, eng = find_cyder()
    if sh:
        log = os.path.join(TOOLS, "cyder-launch.log")
        subprocess.Popen(["/bin/bash", sh, "--engine-src", eng, "--launch-exe", exe],
                         stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True, cwd=ROOT)
        say("已用 Cyder 啟動遊戲。")
    else:
        say("找不到 Cyder.app,請用平常的方式開啟 Game/DCGO.exe。")


def main():
    args = sys.argv[1:]
    st = load_state()
    if "--english" in args:
        if game_running():
            say("✗ 遊戲正在執行,請先關閉遊戲。")
            return 2
        install_pristine_into_game()
        st["localized_ok"] = False
        save_state(st)
        say("已改放官方原檔(英文版)。之後執行「python zh_update.py --localize」即可再套用中文化。")
        return 0
    if "--localize" in args:
        if game_running():
            say("✗ 遊戲正在執行,請先關閉遊戲再重新套用中文化。")
            return 2
        ok = localize()
        if not ok:
            install_pristine_into_game()
            say("已改放官方原檔(英文版),遊戲仍可正常遊玩。請把上面的訊息告訴 Claude。")
        st["localized_ok"] = ok
        st["localized_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        save_state(st)
        if "--launch" in args:
            launch()
        return 0 if ok else 1

    try:
        target = args[args.index("--version") + 1] if "--version" in args else latest_version()
    except Exception as ex:
        say(f"無法檢查更新({ex})。")
        if "--launch" in args:
            say("先以目前版本啟動遊戲。")
            launch()
        return 1
    cur = st.get("version")
    say(f"目前版本:{cur or '未知'}    伺服器最新版本:{target}")
    if "--check" in args:
        return 0
    bd, need = plan_sync(target)
    pristine_ok = all(os.path.exists(P(PRISTINE, rel)) for rel in LOCALIZED)
    if not need and cur == target and st.get("localized_ok") and pristine_ok:
        say("已經是最新版本,不需要更新。")
        if "--launch" in args:
            launch()
        return 0
    if game_running():
        say("✗ 遊戲正在執行。請先關閉遊戲,再執行更新。")
        return 2
    old_meta = None
    if need:
        base = download(target, need)
        say("\n下載完成,全部檔案的雜湊都正確。開始套用…")
        pm = P(PRISTINE, "DCGO_Data/il2cpp_data/Metadata/global-metadata.dat")
        if os.path.exists(pm):
            old_meta = pm + ".prev"
            shutil.copyfile(pm, old_meta)
        prune_backups({cur or "unknown"})
        apply_files(target, need, base, cur)
        shutil.rmtree(os.path.join(DOWNLOADS, target), ignore_errors=True)
    st["version"] = target
    st["files"] = {e["RelativePath"]: e["Hash"] for e in bd["Entries"]}
    sync_emergency_original()
    st["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_state(st)
    # 官方檔案已就緒,接著重建中文化
    ok = localize()
    if not ok:
        install_pristine_into_game()
        say("\n已改放官方原檔(英文版),遊戲仍可正常遊玩。中文化需要調整,請把上面的訊息告訴 Claude。")
    st["localized_ok"] = ok
    st["localized_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_state(st)
    if old_meta:
        try:
            report_new_strings(old_meta, target)
        finally:
            os.remove(old_meta)
    say(f"\n完成:遊戲已是 {target}" + ("(繁體中文)。" if ok else "(英文,中文化待修正)。"))
    if "--launch" in args:
        launch()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
