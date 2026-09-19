# 專案可用免費 AI Bot 與憑證配置指南 (Free Bot Ecosystem) 

- 本文件列出全新專用 Google 帳號可免費使用的 AI 機器人與 API 資源，供背景自動化流水線 及 Master Agent 選用。 

## 1. 免費 AI Bot / CLI 工具選項 (Free Bot Options) 

| 工具名稱 (Tool) | 費用 / 配額 (Quota) | 授權方式 (Auth Method) | 推薦用途 (Recommended Role) | | :--- | :--- | :--- | :--- | 

- | **Gemini CLI** (`@google/gemini-cli`) | **100% 免費 **<br>( 每天約 1,000 次請求， 60 req/min) | 透過新 Gmail 執行 `npx @google/gemini-cli auth` 或 API Key | **Master Agent (首 選 )** ：負責整個 Repo 的自動化分析、事實查核、 Markdown 整理與 Auto-Commit | | **Google AI Studio API Key** | **100% 免費 **<br>(Gemini 1.5 Pro / Flash 免費額度 ) | 登入 [aistudio.google.com](https://aistudio.google.com) 建立免費 API Key | 提供給 Python 腳本 （如 `fetch_sources.py` ）進行結構化資料提煉與 JSON 轉換 | 

| **Groq Cloud API** | **100% 免費 **<br>( 提供 Llama-3, Mixtral 極速推理 ) | 用新 Gmail 註冊 [console.groq.com](https://console.groq.com) | 輔助 Agent ：負責快速分類 raw data、去除重 複內容 | 

| **OpenAI / Codex API** | 免費試用額度 / 需綁定 Key | 入 `OPENAI_API_KEY` | 備用 Agent ：處理複雜邏輯或平行觀點比較 | 

> ** 註 ** ：不需要訂閱 Claude Code (Anthropic 付費方案 ) 。利用 **Gemini CLI** 作為 Master Agent ，搭配新 Gmail 帳號的免費配額即可完全滿足 24/7 自動化需求。 

## 2. 舊 Notebook (WSL) 一鍵初始化指令 (Master Bot Quickstart) 

Master Bot 登入 WSL 後，可直接複製並執行以下 Shell 指令完成 Repo 初始化： 

```bash # 1. 配置 Git 使用 Bot 專屬身份 git config --global user.name "HK History Research Bot" git config --global user.email "hk.history.ssot.bot@gmail.com" 

# 2. 安裝與認證 Gemini CLI (Master Agent) sudo npm install -g @google/gemini-cli gemini auth   # 瀏覽器彈出時選擇登入全新的專用 Gmail 

# # 3. 複製並建立核心目錄結構 

mkdir -p 00_Meta 01_Timeline 02_Entities/People 02_Entities/Treaties_Laws 02_Entities/Places_Landmarks 03_Angles 04_Ingestion_Queue/Unverified scripts 

# 4. 初始化 Commit 並 Push 至 GitHub git add . 

git commit -m "feat(ssot): initialized SSOT repository by Master Bot" git push origin main 

