請先閱讀 CLAUDE.md 了解完整 context，然後依以下順序執行：

## Step 1: 確認環境
- 確認 data/orders.csv 存在且可讀取
- 安裝所需套件：pandas, numpy, matplotlib, seaborn, scipy, jupyter, nbformat
- 讀取 data 做 basic sanity check（row count, column names, null check）

## Step 2: 依序建立 5 個 Jupyter Notebooks

### 2a: notebooks/1a_system_anomaly.ipynb
- 目標：找出系統異常訂單
- 方法：每個 device 計算 total_duration 的 median 和 IQR，標記超過 Q3 + 3*IQR 的訂單為 outlier
- 排除 file_count 影響：用 per_file_duration_avg 而非 total_duration 來偵測
- 分析異常訂單的 phase breakdown（是 queue stuck? device timeout? db lock?）
- 圖表：
  - 每 device 的 duration 分佈 boxplot（highlight outliers）
  - 異常訂單的 phase breakdown stacked bar
  - 異常訂單時間軸 scatter plot
- Export PNG 到 reports/

### 2b: notebooks/1b_user_anomaly.ipynb
- 目標：找出 user 行為異常
- 方法：同一 device 在 30 分鐘視窗內的訂單數量，標記 >= 3 筆為 burst
- 分析 burst 訂單 vs 非 burst 的 duration 差異
- 分析 file_count 異常大的訂單（> P99）
- 圖表：
  - Device contention heatmap（device × time window）
  - Burst vs non-burst duration comparison violin plot
  - File count distribution with anomaly threshold
- Export PNG 到 reports/

### 2c: notebooks/2_bottleneck_breakdown.ipynb
- 目標：正常訂單的瓶頸在哪
- 先排除 Layer 1a + 1b 標記的異常訂單
- 將訂單按 file_count 分 5 組：<50, 50-300, 300-1000, 1000-2000, 2000+
- 每組計算四段佔比：queue, db, device, inner_processing
- 注意：db/device/inner 的 order-level 耗時 ≈ avg × file_count / 4 (parallelism)
- 圖表：
  - 各 file_count 組的 phase proportion stacked bar（百分比）
  - 各 file_count 組的 phase absolute time stacked bar
  - Duration vs file_count scatter with trend line
  - 各 phase 的 P50 / P95 / P99 per group
- Export PNG 到 reports/

### 2d: notebooks/3_slow_device_drilldown.ipynb
- 目標：找出慢機台
- 使用正常訂單（排除異常），聚合每 device 的 device_duration_avg 中位數
- 標記 top 10 慢的 device
- 按 loc_1, loc_2, system_name, device_mode_name 做切面分析
- 圖表：
  - Device performance ranking bar chart（highlight top 10 slow）
  - Slow devices 的 loc_1 / system_name 分佈
  - Device performance by location heatmap
  - Slow vs fast device 的 per_file_duration comparison
- Export PNG 到 reports/

### 2e: notebooks/0_summary_dashboard.ipynb
- 匯總所有發現
- Key metrics: 總訂單數、異常比例、主要瓶頸、慢機台清單
- 從其他 notebook 載入 export 的 PNG 做整合呈現
- 產出 executive summary 文字段落（中文）

## Step 3: 執行所有 notebooks
- 用 nbformat + nbconvert 或 jupyter execute 依序跑完
- 確認 reports/ 下有完整的 PNG 輸出

## 注意事項
- 圖表 style 統一用 seaborn whitegrid
- figsize 至少 (12, 6)，dpi=150
- 圖表標題英文，notebook 內的 markdown 說明用中文
- 每個 notebook 開頭都要 import 和讀取 data，保持獨立可執行
