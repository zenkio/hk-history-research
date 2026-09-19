這是為你的 GitHub Repository 準備的 README.md ，內容專為其他 AI Bot（如 Claude Code、Gemini CLI、Codex ）設計。任何 AI Bot 只要取份文件，就能瞬掌握整案的背景、 SSOT 規則、目錄結構以及無人值守的全自動運作流程。 

你可以直接複製以下內容並儲存為專案根目錄的 README.md： 

## Markdown 

# 香港歷史研究專案 (HK History Research Project) — SSOT Repo 

## > **🤖 FOR AI BOTS & AGENTS:** 

> If you are an AI Agent (Claude Code, Gemini CLI, Codex, or GitHub Actions) running on this repository, **read this document carefully before executing any tasks**. This document defines the Single Source of Truth (SSOT), system architecture, multi-perspective tagging standards, and autonomous execution rules. 

## 1. Project Overview & Vision ( 專案願景 ) 

This project aims to build a comprehensive, continuous, multi-perspective, and neutral **Single Source of Truth (SSOT)** database for Hong Kong history. 

## ### Core Principles 

1. **Multi-Angle Neutrality**: History is multifaceted. We act as historical reporters—we do not judge, but rather document parallel perspectives (e.g., UK Colonial, Beijing/Qing Official, Local Civic/Indigenous, International Academia). 

2. **Fact-Checking & Debunking**: If a claim lacks evidence or contradicts official records, tag its confidence level and document counter-evidence. Avoid absolute denial unless explicit forgery is proven. 

3. **$0 Budget Architecture**: Built using open-source tools, GitHub Private Repositories, Obsidian local vaults, and free AI CLI tiers. 

4. **Autonomous Ingestion**: Operates as a 24/7 background pipeline without requiring human intervention for routine data ingestion, categorization, and git commits. 

## ## 2. Directory Structure (目) 

```text 

hk-history-ssot/ 

├── README.md                       # This file (Agent Context & Onboarding Guide) ├── .github/ 

- │   └── workflows/                  # GitHub Actions for automated scraping 

├── 00_Meta/                        # Core Guidelines & Documentation 

- │   ├── SSOT_Operational_Guide.md   # Overall system architecture guide 

- │   ├── Sources_Registry.md         # Monitored data sources (Archives, FB, YT) 

- │   └── Autonomous_Pipeline_Rules.md# Decision matrix & tagging standards ├── 01_Timeline/                    # Chronological SSOT Timeline (.md) 

- │   ├── Pre_1841_Early_Dynasties.md 

- │   ├── 1842_Nanking_Treaty.md 

- │   ├── 1898_New_Territories_Lease.md 

│   ├── 1941_1945_Japanese_Occupation.md │   ├── 1950_1970_Industrialization.md │   ├── 1984_Sino_British_Joint_Declaration.md │   ├── 1997_Handover.md │   ├── 2003_SARS_and_Article_23.md 

│   ├── 2014_Umbrella_Movement.md 

│   └── 2019_2020_Anti_ELAB_NSL.md ├── 02_Entities/                    # Networked Database ([[Wikilinks]]) 

│   ├── People/                     # Historical figures (e.g., [[Mark Young]]) 

│   ├── Treaties_Laws/              # Laws & Treaties (e.g., [[Basic Law]]) 

│   └── Places_Landmarks/           # Locations (e.g., [[Sung Wong Toi]]) ├── 03_Angles/                      # Perspective-Specific Analyses 

│   ├── Colonial_UK_Perspective.md │   ├── Beijing_Official_Perspective.md 

│   ├── Local_Civic_Perspective.md │   └── Debunked_Claims.md ├── 04_Ingestion_Queue/             # Raw Scraped Data (Pending Processing) 

│   └── Unverified/                 # Low-confidence rumors quarantined here └── scripts/                        # Automation & Scraper Scripts ├── fetch_sources.py            # RSS / Web scraper script └── autonomous_runner.sh        # Background execution script 

# 3. Bot Execution Protocol & Routing Matrix (AI Agent 處理邏輯 ) 

When processing raw text files in 04_Ingestion_Queue/, AI Agents MUST strictly follow the routing rules defined in 00_Meta/Autonomous_Pipeline_Rules.md: 

|Evidence<br>Level|Trigger Criteria|Automated Action|
|---|---|---|
|[證據等級:<br>高]|Declassified official<br>archives (UK National<br>Archives, HK PRO),<br>official treaties.|Update 01_Timeline/ directly, create/link<br>02_Entities/ with [[Wikilinks]].|
|[視角:多重]|Conflicting<br>interpretations among<br>UK, Beijing, or Local<br>sources.|Append as a Parallel Block under<br>03_Angles/. Do NOT overwrite existing<br>timeline facts.|
|[證據等級:<br>低]|Social media posts,<br>forum rumors,<br>unsourced claims.|Quarantine to<br>04_Ingestion_Queue/Unverified/. Tag with<br>[待查核]. NEVER write directly to|



|||01_Timeline/.|
|---|---|---|
|[史料不符]|Contradicts proven<br>official records or<br>physical evidence.|Document counter-evidence in<br>03_Angles/Debunked_Claims.md.|



# 4. Git Commit & Automation Rules ( 自動提交規範 ) 

AI Agents running in background mode are authorized to commit and push directly to main without human approval, adhering to the following commit message standards: 

- Daily Ingestion: auto(ingestion): synced [YYYY-MM-DD] history data 

- 

- Timeline Updates: auto(timeline): updated [Event Name] with FOIA perspectives 

- 

- Entity Linking: auto(entity): added [[Entity Name]] wikilinks 

- 

# 5. Quickstart Prompt for AI Agents (Agent 啟動指令 ) 

If you are an AI CLI tool (e.g., Gemini CLI or Claude Code) triggered on a background machine, run the following command sequence: 

Bash 

# 1. Sync latest repo 

git pull origin main 

# 2. Run Python scraper (if available) 

python3 scripts/fetch_sources.py 

# 3. Read rules and process ingestion queue 

gemini run "Read 00_Meta/Autonomous_Pipeline_Rules.md and process all raw files in 04_Ingestion_Queue/. Update 01_Timeline/, 02_Entities/, and 03_Angles/ accordingly." 

# 4. Commit and push changes git add . 

git commit -m "auto(pipeline): background history processing [$(date +'%Y-%m-%d')]" git push origin main 

<ElicitationsGroup> 

If you're ready, I can help you draft the `scripts/fetch_sources.py` or `scripts/autonomous_runner.sh` script to complete the automation setup for your local repo! </ElicitationsGroup> 

