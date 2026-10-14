# DCGO 繁體中文化（DCGO-zh-TW）

把 [DCGO](https://www.dcgo.online)（數碼寶貝卡片遊戲模擬器）的**介面與對戰文字**翻成繁體中文（台灣用語）的工具與翻譯表，**Windows** 與 **macOS**（用 Cyder／Wine 執行）都可以使用。遊戲改版時，可以自動下載官方檔案並重新套用中文化。

- 介面：選單、設定、牌組編輯、對戰畫面
- 對戰文字約 13,800 句：選擇提示、效果名稱、效果說明、對戰紀錄、指令按鈕
- 時機標籤與關鍵字：`[登場時]` `[進化時]` `[每回合1次]`、《阻擋者》《速攻》《貫通》…
- 效果文字裡的卡名、特徵以「」標示，對照見 [名詞對照表.txt](名詞對照表.txt)

> 目前對應的遊戲版本：**1.19.0**

## 這個儲存庫不包含什麼

- **遊戲本體**：第一次執行時，由工具從 DCGO 官方更新伺服器（與官方啟動器相同的來源）下載，每個檔案都會驗證雜湊。
- **卡圖**：遊戲會自動從官方指定的來源下載缺少的卡圖。
- **字型**：中文字使用你電腦內建的系統字型：Windows 用「微軟正黑體」，macOS 用「蘋方-繁」。建置時直接從**你自己的電腦**取用，本儲存庫不含任何字型檔。

## 需求

**Windows**
- Windows 10／11（64 位元）
- [Python](https://www.python.org/downloads/) 3.9 以上（安裝時勾選「Add python.exe to PATH」）
- 系統內建的「微軟正黑體」

**macOS**（在 Apple 晶片、macOS 26 上測試）
- Cyder 或其他可執行 Windows 程式的 Wine 環境（工具會尋找 `~/Desktop/Cyder.app`、`/Applications/Cyder.app`）
- `/usr/bin/python3`（安裝 Xcode 或 Command Line Tools 即有）

**兩者都需要網路**：第一次執行會從 pypi.org 安裝 UnityPy（約 30 MB，只裝在 `_zh_tools` 裡），並下載完整遊戲（約 700 MB）。

## 使用方式

1. 下載本儲存庫（`git clone` 或下載 ZIP），放到你想安裝遊戲的位置。
2. 雙擊啟動檔：
   - **Windows**：`啟動DCGO（自動更新）.bat`
   - **macOS**：`啟動DCGO（自動更新）.command`
3. 第一次執行會依序：建立 Python 環境 → 從官方伺服器下載遊戲 → 套用中文化並驗證 → 啟動遊戲。
4. 之後每次都雙擊同一個檔案：有新版本就只下載有變動的檔案，重新套用中文化後啟動；沒有新版本或沒有網路時直接啟動。
5. 不要使用官方啟動器 `DCGO_Launcher.exe`，它會把中文化的檔案「修復」回英文。

第一次開啟時系統可能會擋：Windows 出現「Windows 已保護您的電腦」時，按「其他資訊」→「仍要執行」；macOS 則對檔案按右鍵 →「打開」。

Windows 上若遊戲打不開、出現缺少 `VCRUNTIME140.dll` 之類的訊息，請安裝 Microsoft 的「Visual C++ 可轉散發套件（x64）」。

其他指令（在 `_zh_tools` 資料夾內執行；Windows 把 `.venv/bin/python` 換成 `.venv-win\Scripts\python.exe`）：

```bash
.venv/bin/python zh_update.py --check      # 只檢查有沒有新版本
.venv/bin/python zh_update.py --localize   # 不更新，只重新套用中文化
.venv/bin/python zh_update.py --english    # 改回官方英文原檔（中文化有問題時的緊急做法）
```

想改用其他繁體中文字型時，設定環境變數 `ZH_FONT`（字型檔路徑）與 `ZH_FONT_FACE`（`.ttc` 裡的字型家族名稱）後執行 `--localize`。

## 已知限制

- 卡片名稱、卡片詳細資料面板的效果文字來自遊戲的卡片資料庫，只有英文／日文（由遊戲設定的「語言」決定）。
- 組合技（數碼合體、組裝、合步進化）的條件描述刻意保留英文：遊戲規則會拿這些英文搜尋卡片文字，翻譯會讓判斷出錯。
- 新版本新增的卡片文字一開始是英文。更新器會把清單存成 `_zh_tools/new_strings_<版本>.json`，補翻後執行 `--localize` 即可套用。
- 卡名與特徵的中文是從簡體中文官方卡面辨識後轉成繁體，可能與台灣官方譯名不同。
- Windows 版已用 TrueType 字型在 macOS 上模擬建置並通過驗證，但尚未在實際的 Windows 電腦上測試過。

## 運作方式

遊戲是 Unity IL2CPP 程式。中文化會改寫 6 個檔案：介面場景與字型設定（用 UnityPy），以及 `global-metadata.dat` 的字串常值表。

遊戲規則程式會用英文字樣判斷效果（例如效果說明以 `[On Play]` 開頭才算登場時效果）。所以翻譯時，規則程式裡用來比對的字串常值也同步換成相同的中文。只有「所有出現處都只用來顯示」的字串才會被翻譯，這由 `zh_source.py` 分析 DCGO 原始碼判定。每次建置後，`verify_build.py` 會獨立檢查以下項目：

- 官方檔案的雜湊
- 物件結構
- 字型設定
- 字串表的完整性
- 格式字串的安全性

### 主要檔案

| 檔案 | 用途 |
|---|---|
| `啟動DCGO（自動更新）.bat` / `.command` | Windows / macOS 啟動檔 |
| `_zh_tools/zh_update.py` | 自動更新器：查官方版本、下載、套用、重建中文化、驗證、啟動 |
| `_zh_tools/build_zh.py` / `verify_build.py` | 建置中文化 / 獨立驗證 |
| `_zh_tools/zh_tw.py` | 介面翻譯 |
| `_zh_tools/zh_v2_map.json` | 對戰文字翻譯（英文原字串 → 中文） |
| `_zh_tools/zh_source.py` | C# 原始碼分析：判斷字串是否只用於顯示 |
| `_zh_tools/zh_merge_new.py` | 新版本新字串的譯文驗證與合併 |
| `_zh_tools/zh_glossary.py` | 時機標籤、關鍵字、卡名對照 |
| `_zh_tools/make_deck.py` | 把 digimonmeta.com 等匯出的牌表做成遊戲牌組檔 |

## 聲明

本專案為非官方的粉絲作品，與 Bandai Namco、DCGO 開發團隊無關。數碼寶貝相關名稱、卡片文字與圖像的權利屬於原權利人。微軟正黑體（Microsoft）與蘋方（Apple）都只在使用者自己的電腦上於建置時取用，不隨本專案散布。
