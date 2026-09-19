# # 數據源監控與擷取清單 (Sources Registry) 

本文件列出專案持續同步（ Continuous Ingestion）所需控的各史源，涵官方案、及民社群。 

- ## 1. 官方與權威解密檔案 (Official Archives & Records) 

- ** 英國國家檔案館 (The National Archives, Kew, UK)** * ** 重點類別 **：FCO (Foreign and Commonwealth Office) 及 CO (Colonial Office) 解密文 件。 

- ** 監控主題 **：香港前途 談 判、1967 年事件、港府行政告。 

- ** 香港歷史檔案館 (Hong Kong Public Records Office, PRO)** 

- ** 重點類別 **：HKRS (Hong Kong Record Series) 政府公文、政府新聞處 (GIS) 歷史圖片 

。 

- ** 監控主題 **：早期土地批 給 、新界租借公文、 戰 後基建 與 公共房屋 發 展。 * ** 中國國家檔案局 / 廣東省檔案館 ** 

- ** 重點類別 **：清代 軍機處檔 摺、明清 邊 防 與鹽 政 記載 。 

- ## 2. 學術數據庫與 口述 歷 史 (Academic & Oral History) 

- ** 香港大學圖書館數位典藏 (HKU Digital Initiatives)**： 舊報紙數據庫 （如《 華 字日 報 》）、 歷史地圖集。 * ** 香港中文大學歷史系與圖書館 (CUHK Library)**：香港研究 數據庫 、口述 歷 史 訪問紀錄 、 香港地方誌。 

- ## 3. 社群 與 民 間資 料 (Community Sources) 

- **Facebook 社群/ 專頁 **：「香港 舊 照片」、「香港 歷 史研究社」、各地 區歷 史 誌專頁 （民 間舊 照、老街坊口述回 憶 ）。 * **YouTube 歷史頻道與紀錄片 **： 監 控各 頻 道之史料 來 源引用 與 冷 門選題 。 

## 4. 自動化擷取策略 (Ingestion Pipeline Rules) 

1. ** 定時爬取 **：透 過 GitHub Actions / Python 腳本監控 RSS 及更新， 將 Raw Data 自動寫 

- 入 `04_Ingestion_Queue/`。 

2. ** 去重與標籤 **：Agent 自動檢查 URL 或事件，避免重入。 3. ** 來源標註 **：所有 Raw Data 必須自動附帶來源 URL 及初始 證據 等 級 (`[ 證據等級 : 高 / 中 /低]`)。 

