#!/bin/bash
# 雙擊執行:檢查 DCGO 官方更新 → 有新版就下載有變動的檔案並重新套用繁體中文化 → 用 Cyder 啟動遊戲。
# 更新來源與官方啟動器相同(https://dcgo.online/PATCH),每個檔案下載後都會驗證雜湊。
cd "$(dirname "$0")/_zh_tools" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "第一次使用:建立中文化工具需要的 Python 環境(會從 pypi.org 下載約 30 MB)…"
  /usr/bin/python3 -m venv .venv && ./.venv/bin/python -m pip install -q "UnityPy==1.25.4" || {
    echo "建立 Python 環境失敗,請把上面的訊息告訴 Claude。"
    read -n 1 -s -r -p "按任意鍵關閉…"
    exit 1
  }
fi

./.venv/bin/python zh_update.py --launch
status=$?
echo
if [ $status -ne 0 ]; then
  echo "更新過程有問題(見上方訊息)。遊戲仍可用目前的版本遊玩。"
  read -n 1 -s -r -p "按任意鍵關閉…"
else
  echo "完成,這個視窗可以關閉。"
fi
