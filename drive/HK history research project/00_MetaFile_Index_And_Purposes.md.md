# # 案索引、建 (File Index & Purpose Registry) 

> **🤖 FOR ALL AI BOTS & AGENTS:** 

> Before creating a new file or modifying an existing one, consult this directory. DO NOT create duplicate files. Follow the designated update rules for each directory. 

## 1. 檔案與目錄職責清單 (Directory & File Registry) 

- ### 🤖 `00_Meta/` — 案元 (Guidelines & Registry) * **`README.md`** ( 根目錄 ) 

- **用途** ：專案入口文件，供所有 Agent 與 人 類開發 者快速了解架 構 、SSOT 原自化流程。 

- **修改** ：僅在架構、新增目錄或工作流（ Workflow）改更新。 

- **`00_Meta/SSOT_Operational_Guide.md`** 

- **用途** ：專案技術架構指南，記錄工具鏈選型、 GitHub + Obsidian + Agent 流水 線細節 。 

- **`00_Meta/Sources_Registry.md`** 

- **用途** ：監控的數據源清單（英國檔案館、 PRO、中大/港大、FB 史社群等）。 

- ** 修改規則 ** ：當發現新的可信數據源或社群專頁時追加。 

- **`00_Meta/Autonomous_Pipeline_Rules.md`** 

- **用途** ：定義 AI Agent 24/7 自 動 判定、 證據 分 級 （高/中/低）、角 Auto-Commit 規則。 

- **`00_Meta/File_Index_And_Purposes.md`** ( 本文件 ) * **用途** ：定義每個檔案的目標、責任邊界以及「何時更新 / 何新建案」的。 

### 🤖 `01_Timeline/` — SSOT 核心歷史時間軸 (Ground Truth Timeline) * **用途** ：按照年代劃分的客觀歷史時間軸 Markdown 檔（如 `1842_Nanking_Treaty.md`, `1941_1945_Japanese_Occupation.md` ）。 * ** 更新條件 ** ：僅當收到 **`[ 證據等級 : 高 ]`** （官方解密檔案、條約原文）的新史實時直接更 新。 

- **禁作** ：禁止將未未經查核的網路傳聞寫入此目錄。 

### 🤖 `02_Entities/` — 雙向連結網絡 (Wikilinks Database) 

- ** 子目錄 ** ： `People/` ( 人物 ), `Treaties_Laws/` ( 條約法律 ), `Places_Landmarks/` (地建)。 * **用途** ：存放獨立實體頁面，利用 `[[Wikilinks]]` 供 Obsidian 建立 關聯圖譜 。 * ** 新建條件 ** ：當時間軸中頻繁出現某個關鍵人物（例： [[ 楊慕琦 ]] ）、法案或地標時，在此 目錄為其建立獨立 `.md` 檔案。 

### 🤖 `03_Angles/` — 多方視角與爭議檔案 (Multi-Perspective & Debunking) * ** 檔案 ** ： `Colonial_UK_Perspective.md`, `Beijing_Official_Perspective.md`, `Local_Civic_Perspective.md`, `Debunked_Claims.md`。 

* **用途** ：平行記錄不同立場對同一歷史事件的解讀，以及被證實為虛假 / 缺乏史料支持的都 市。 

* ** 更新條件 ** ：當同一事件出現跨立場的相異觀點時，追加至對應視角檔案的平行區塊 （ Parallel Block ）。 

### 🤖 `04_Ingestion_Queue/` — 爬原始存 (Raw Ingestion Queue) * **用途** ：自動化腳本抓取到的原始文字、 RSS Feed 暫 存 處 。 * **`04_Ingestion_Queue/Unverified/`** ：存放 **`[ 證據等級 : 低 ]`** 的社群傳聞或未查核數據， 隔至此等待一步佐。 

- ### 🤖 `scripts/` — 自 動 化 腳 本 與 流水 線 (Automation) * **`fetch_sources.py`** ：自動爬取 RSS / 數據 源之 腳 本。 * **`autonomous_runner.sh`** ：舊 Notebook 背景 24/7 自 動運 行的 Cron 流水 線腳 本。 

## 2. Gemini Notebook (NotebookLM) 零幻覺整合指南 

### 什使用 Gemini Notebook？ 

Gemini Notebook （ NotebookLM ）具備 **「Source-Grounded （基於來源）」 ** 的特性，能 100% 避免 AI 生成幻覺，並提供原始文獻引述（ Citation ）。 

### 工作流整合 (Workflow Integration) 

1. ** 史料匯入 ** ：將 `01_Timeline/` 中的核心 Markdown 或下載的官方解密 PDF ，拖入 Web 版 NotebookLM。 2. ** 腳本與深層研究 ** ：在撰寫影片腳本或查核複雜爭議史實時，透過 NotebookLM 進行提問， 保每一句旁白均有原始文支持。 3. **背景 Agent 的「零幻覺」約束 ** ：背景運行的 Agent （ Gemini CLI / Claude Code ）在處 理數據時，必須嚴格以本地 `01_Timeline/` 作 為 唯一事 實來 源， 嚴 禁自行外推未提及之史 實 。 

2. ** 腳本與深層研究 ** ：在撰寫影片腳本或查核複雜爭議史實時，透過 NotebookLM 進行提問， 保每一句旁白均有原始文支持。 

## 3. 何時更新舊檔 vs. 何時建立新檔？ (Decision Matrix) 

- | 情境 (Scenario) | 處理動作 (Action) | 目標檔案 / 目錄 (Target) | 

| :--- | :--- | :--- | 

- | ** 發現官方檔案館的新解密文件 ** | 直接更新時間軸，並建立 Wikilinks | `01_Timeline/` + `02_Entities/` | | ** 發現社群 / 論壇對某一事件的不同說法 ** | 追加至對應視角檔案，不蓋寫時間軸 | `03_Angles/` | 

| ** 發現完全未經證實的民間傳聞 / 都市傳說 ** | 隔離至暫存區，加 `[ 待查核 ]` 🤖🤖 | `04_Ingestion_Queue/Unverified/` | | ** 發現已被史料證偽的假訊息 ** | 寫入反證記錄，作為影片闢謠素材 | 

- `03_Angles/Debunked_Claims.md` | 

- | ** 發現新的歷史數據源 /FB 專頁 / 網站 ** | 追加至數據源清單 | 

- `00_Meta/Sources_Registry.md` | 

