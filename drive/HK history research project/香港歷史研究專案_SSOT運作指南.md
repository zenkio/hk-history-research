# 香港歷史研究專案： Single Source of Truth (SSOT) 運作指南 

- 本文件為「香港歷史研究與影片創作專案」的 ** 單一事實來源（ Single Source of Truth, SSOT） ** 系統運作與技術架構指南。本專案旨在建立一個能持續擴充、多維度比對、客觀中立且零成本 （ $0 Budget） 運 行的香港 歷 史 數據庫 。 

## 1. 專案願景與核心原則 (Core Principles) 

1. 客觀中立與多視角呈現（ **Multi-Angle Neutrality** ）： 

   - 歷史事件往往有多重解讀。我們作為歷史記錄者不作道德判斷，而是平行列出不同 角（如：殖民地政府、清廷/中央、在地原住民/ 庶民、國際第三方）。 

   - 若有事實不符（如缺乏史料支持的都市傳說或假新聞），標註其疑點與反證來源 ， 除非有明 確偽 造 證據 ，否 則 避免 100% 否定其存在 價 值。 

2. 零預算與自由開源技術（ **$0 Budget Architecture** ）： 

   - 充分利用免費開源工具、 GitHub 無限 Private Repo 度、Obsidian 本地雙向連結， 以及各免 AI CLI / Agent （ Gemini CLI, Claude Code, Codex 等）。 

3. 持續同步與自動化增量擷取（ **Continuous Ingestion & Sync** ）： 

   - 拒絕一次性資料擷取（ One-time fetch）。建立可持 續運 行的流水 線 （Ingestion Pipeline）， 長 期定 時 吸收解密 檔 案、社群 歷 史 貼 文 與學術 文 獻 。 

## 2. 系統技術架構 (System Architecture) 

- [ 數據來源 Data Sources] 

- ├── 1. 官方解密檔案 (UK National Archives, HK PRO, 中 國 史志) 

- ├── 2. 學術數據庫 (HKU / CUHK Digital Archives, 論文 ) 

- └── 3. 社群與自媒體 (FB 歷史社群 , YouTube, 口述歷史 ) 

│ 

- (GitHub Actions / 定時 Python 腳本 ) 

[04_Ingestion_Queue/ 待處理區 ] 

│ 

- ( 舊 Notebook 24/7 AI Agent: Gemini CLI / Claude Code / Codex) 

- [ 事實查核 & 多 視 角交叉比 對 (Triangulation Engine)] 

│ 

▼ (Git Commit / Pull Request) 

[GitHub Repo (Main Branch) + Obsidian Local Vault] 

├── 01_Timeline/  ( 按年代分類的 SSOT 時間軸 ) 

├── 02_Entities/  (人物、、地之向) 

└── 03_Angles/    ( 各方觀點與論述匯整 ) 

工具鏈選型 (Tool Stack) 

- 版本控制與核心數據庫 ： GitHub (Private Repository) 

- 本地研究與視覺化圖譜 **IDE** ： Obsidian（直接開啟 Git Repo 資料夾作為 Vault，利用 Markdown [[Wikilinks]] 建立網狀關係） 

- **AI Agent** 執行環境 ： 舊 Notebook / 本地 Terminal （運行 Gemini CLI、Claude Code、 Codex） 

- 自動化流水線 ： GitHub Actions（定時執行 RSS / Scraper 腳本，將 Raw Data 自動提交 至 04_Ingestion_Queue/ ） 

## 3. GitHub Repository 目錄結構 (Folder Structure) 

hk-history-ssot/ 

├── .github/ 

│   └── workflows/          # GitHub Actions 定時自動化擷取腳本 ├── 00_Meta/ 

- │   ├── SSOT_Operational_Guide.md  # 本運作指南 

- │   ├── Sources_Registry.md        # 數據源監控清單 (UK Archives, FB Groups 等) 

- │   └── Multi_Angle_Guide.md       # 多 視 角 標籤與 事 實 查核 規範 ├── 01_Timeline/            # 按年代與專題劃分的 SSOT 時間軸 (.md) 

- │   ├── Pre_1841_Early_Dynasties.md 

- │   ├── 1842_Nanking_Treaty.md 

- │   ├── 1898_New_Territories_Lease.md 

- │   ├── 1941_1945_Japanese_Occupation.md 

- │   ├── 1950_1970_Industrialization.md 

- │   ├── 1984_Sino_British_Joint_Declaration.md 

- │   ├── 1997_Handover.md 

- │   ├── 2003_SARS_and_Article_23.md 

- │   ├── 2014_Umbrella_Movement.md 

- │   └── 2019_2020_Anti_ELAB_NSL.md 

- ├── 02_Entities/            # 雙 向 連結網絡 (wikilinks: [[Entity]]) 

- │   ├── People/             # 歷史人物 (例: [[ 楊慕琦 ]], [[ 鄧志大 ]]) 

- │   ├── Treaties_Laws/      # 條約與 法律 (例: [[ 南京條約 ]], [[ 基本法 ]]) 

- │   └── Places_Landmarks/   # 地 點與 建 築 (例: [[ 屯門官富場 ]], [[ 宋王臺 ]]) 

- ├── 03_Angles/              # 各方觀點彙整與分析 

- │   ├── Colonial_UK_Perspective.md 

- │   ├── Beijing_Official_Perspective.md 

- │   ├── Local_Civic_Perspective.md 

- │   └── International_Scholar_Perspective.md 

- └── 04_Ingestion_Queue/     # AI Agent 待處理 Raw Data 與爬蟲暫存區 

## 4. 多視角標記與事實查核規範 (Tagging & Fact-Checking Standard) 

為了確保客觀中立，所有傳入的史料必須經過以下標籤化處理： 

視角標籤 (Perspective Tags) 

   - [視 角 : 英方 / 殖民地政府 ] (Colonial / UK FOIA) 

   - [視 角 : 北京 / 清廷官方 ] (Beijing / Qing Official) 

   - [視 角 : 本土 / 庶民 / 原住民 ] (Local Citizen / Indigenous Clans) 

   - [視 角 : 第三方 /國際學 者 ] (International Academia) 

- 證據等級評定 (Evidence Confidence Level) 

   - [證據 等 級: 高 ] ：有官方原始 檔 案（如英 國國 家 檔 案 館 、清 宮檔 案）、正式 締結 之 國際條約 副本支持。 

   - [證據 等 級: 中 ] ：有 報 章 雜誌 、 當 事人日 記 、口述 歷 史或多方交叉佐 證 。 

   - ● [證據 等 級: 低 / 待查核 ] ：社群 論壇傳聞 、未 經證實 的民 間傳說 。 ● [ 史料不符 / 疑 點] ： 與 已知官方 檔 案或多方文 獻嚴 重矛盾，附上 記錄與 反 證說 明。 

## 5. Multi-Agent 協作與運作流程 (Agent Workflow) 

1. **Step 1:** 自動數據擷取 **(Ingestion)** 

   - GitHub Actions 或 Python 腳本抓取 RSS/FB/ 檔案館新聞，存入 04_Ingestion_Queue/raw_YYYYMMDD_topic.md。 

2. **Step 2: Agent** 分析與提煉 **(Analysis & Fact-Checking)** 

   - 在舊 Notebook 上觸發 Gemini CLI 或 Claude Code 執行命令： 

claude "Read files in 04_Ingestion_Queue/, cross-reference with 01_Timeline/ and 02_Entities/, apply Multi-Angle tags, and generate a Git commit proposal." 

3. **Step 3:** 人類審核與 **Merge (Human-in-the-loop Verification)** 

   - 檢查 Agent 生成的 Pull Request， 確認標籤與證據 等 級無誤 後 Merge 入 main 分 支。 

4. **Step 4: Obsidian** 本地圖譜同步 **(Visualization)** 

   - 開啟 Obsidian，透 過雙 向 圖譜 查看新引入的事件 與 人物 關聯 ，作 為 影片 腳 本大 綱 之素材 庫 。 

