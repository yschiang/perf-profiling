# Order Performance Profiling Project

## 背景
訂單處理系統 performance profiling。
User 透過 browser 下單，order 進 queue，consumer 撿起後對 device 執行 file check。
部分訂單耗時數小時（正常應 <30 分鐘），需找出瓶頸。

## 系統架構
```
User -> Browser -> Order Created -> Queue -> Consumer picks up
  -> 每筆 order 對一個 device，每個 order 有 4 threads 並行處理
  -> 每個 file 的處理流程:
     1. DB side: 查詢 golden file list
     2. Device side: 對 device 下 device command 取得 file
     3. Inner process: 進行 file check
```

## 資料
- `data/orders.csv` — 30,000 筆合成訂單資料（模擬真實分佈）
- `data/orders_with_labels.csv` — 含隱藏標籤（驗證用）
- `config/schema.yaml` — 完整欄位定義與分析角色

## 三層分析框架

### Layer 1a — 系統異常偵測
同一 device 大部分訂單很快，但少數異常慢（排除 file_count 影響後）。
可能原因：device command timeout、DB lock、queue stuck。
Action: 標記異常訂單，交 SRE 查修。

### Layer 1b — User 行為異常偵測
同一 device 短時間內多筆訂單（contention）、file 數量異常大等。
用 device_id + order_created_at 偵測。
Action: 回饋 user 或制定使用規範。

### Layer 2 — 正常訂單瓶頸拆解
排除 Layer 1 異常後，將 total_duration 拆成四段：
- queue_duration_seconds
- db_duration_avg_seconds × file_count / parallelism
- device_duration_avg_seconds × file_count / parallelism
- inner_processing_duration_avg_seconds × file_count / parallelism

按 file_count 分組（如 <50, 50-300, 300-1000, 1000-2000, 2000+），看哪段佔比最大。

### Layer 3 — 慢機台下鑽
如果 device side 是主要瓶頸，按 device_id 聚合 device_duration，找出最慢的 devices。
按 loc_1, loc_2, system_name, device_mode_name 切面分析。

## 產出要求
1. Python 分析程式放在 `analysis/` 目錄
2. 視覺化報表（HTML 互動圖表，用 plotly）放在 `reports/` 目錄
3. 每個 Layer 產生獨立的分析腳本和報表
4. 最終產出一個 summary dashboard（`reports/dashboard.html`）整合所有發現

## 技術要求
- Python 3.12+
- pandas, numpy, matplotlib, seaborn, scipy
- 報表用 Jupyter Notebook 呈現（程式 + 圖表 + 註解一體）
- 每個 Layer 一個 notebook，圖表同時 export PNG 到 `reports/`
- 所有圖表標題和軸標籤用英文，註解可中英混用
- 圖表 style: seaborn whitegrid, figsize 合理, dpi=150 for export

## 目錄結構
```
perf-profiling/
├── CLAUDE.md              # 本文件
├── config/
│   └── schema.yaml        # 欄位定義
├── data/
│   ├── orders.csv         # 分析用資料（換 real data 時替換此檔）
│   └── orders_with_labels.csv  # 含標籤（驗證用，real data 不需要）
├── notebooks/             # Jupyter Notebooks（待生成）
│   ├── 1a_system_anomaly.ipynb
│   ├── 1b_user_anomaly.ipynb
│   ├── 2_bottleneck_breakdown.ipynb
│   ├── 3_slow_device_drilldown.ipynb
│   └── 0_summary_dashboard.ipynb
├── reports/               # Export 的 PNG 圖表（待生成）
└── scripts/
    └── generate_data.py   # 資料生成腳本
```
