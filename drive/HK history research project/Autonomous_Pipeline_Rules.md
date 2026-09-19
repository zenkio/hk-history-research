- # 全自動 Agent 執行與判定規則 (Autonomous Pipeline Rules) 

- 本文件定義 AI Agent 在舊 Notebook 無人值守運行時的自動判定、檔案寫入與 Git 自動提交 規範。 

- ## 1. 分流自入 (Data Routing Matrix) 

- 當 AI Agent 在 `04_Ingestion_Queue/` 讀取到新 Raw Data 時，必須嚴格執行以下規則： 

- **Rule A ：高信心度史實 (`[ 證據等級 : 高 ]`)** 

- ** 觸發條件 ** ：來自官方檔案館解密文件、正式國際條約文本。 * ** 自動動作 ** ：直接更新 `01_Timeline/` 對應年代檔案，並在 `02_Entities/` 自動建立或連 結相關人物、條約或地標的 `[[Wikilinks]]`。 

- **Rule B ：爭議史實 / 多方觀點 (`[ 視角 : 多重 ]`)** 

- ** 觸發條件 ** ：同一事件存在英方、清廷 /北京或本土民的不同解。 

- ** 自動動作 ** ：不得覆蓋既存史實，必須以「平行區塊 (Parallel Block)」追加至 `03_Angles/` 對應視角檔案，並標註來源。 

- **Rule C ：低信心度 / 未證實傳聞 (`[ 證據等級 : 低]`)** 

- ** 觸發條件 ** ：社群論壇貼文、未附史料來源之網絡傳言。 

- ** 自動動作 ** ： 100% 隔至 `04_Ingestion_Queue/Unverified/`，自 動 加上 `[待查核]` 標籤， 

- ** 絕對不得 **入 `01_Timeline/`。 

- **Rule D ：事實史料不符 / 偽造疑點 (`[ 史料不符 ]`)** 

- ** 觸發條件 ** ：內容與已知官方檔案或多方權威史料嚴重矛盾。 * ** 自動動作 ** ：標註疑點與反證來源，寫入 `03_Angles/Debunked_Claims.md`，但不直接 除原始。 

## 2. Git 自動提交與部署規範 (Auto-Commit Specification) 

1. **Commit Message 格式** ： 

- `auto(ingestion): synced [YYYY-MM-DD] history data` 

- `auto(timeline): updated 1842 Nanking Treaty FOIA angle` 

2. ** 自動 Push** ： 

- 分析與標籤完成後，自動執行 `git add .` -> `git commit` -> `git push origin main`。 

- 完全無需人類手動審核或按 Approve。 

