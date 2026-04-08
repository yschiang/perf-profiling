# 操作手冊 — Order Performance Profiling

## 系統背景

```
User → Browser → Order Created → Queue → Consumer picks up
  → 每筆 order 對一個 device，有 PARALLELISM 個 threads 並行處理 files
  → 每個 file: DB查詢 → Device device command → Inner file check
```

| Phase | 說明 | 單位 |
|-------|------|------|
| Queue | order 等 consumer 撿起的時間 | per-order，通常 < 60s |
| Device | device command 與設備通訊 | per-file average |
| DB | 查詢 golden file list | per-file average |
| Inner | file check 處理 | per-file average |

**Order-level 估算**：`est_total ≈ queue + (device_avg + db_avg + inner_avg) × file_count / PARALLELISM`

---

## 開始前

1. 將真實資料放到 `data/orders.csv`（欄位需與 `config/schema.yaml` 一致）
2. 編輯 **`config/params.py`** — 共用參數改這一個檔案就好：
   - `DATA_PATH`：資料路徑
   - `DATETIME_FORMAT`：`order_created_at` 的時間格式
   - `PARALLELISM`：向開發團隊確認
   - `FILE_COUNT_BINS` / `FILE_COUNT_LABELS`：可先用預設值，Step 3 再調
   - `GAP_MIN_RATIO`：可先用預設值 2.0
3. 確認已安裝：`pandas numpy matplotlib seaborn jupyter`

---

## Step 0 — 資料健檢

1. 開啟 `notebooks/step0_data_sanity.ipynb`
2. 確認 `DATA_PATH` 指向你的資料
3. **Run All Cells**

### 檢查重點

| 項目 | 看什麼 | 通過條件 | 不通過代表什麼 |
|------|--------|---------|---------------|
| order_id | 重複數量 | = 0 | 資料有 dup，需先 dedup |
| null 欄位 | 各欄位 null 比例 | device_mode_name, loc_2 可有 null，其他 = 0 | 資料不完整，確認 ETL |
| 負數 duration | 各 duration 欄位 < 0 的筆數 | = 0 | 資料異常，確認來源 |
| 時間範圍 | min ~ max date | 涵蓋你預期的分析區間 | 資料可能被截斷 |
| 總筆數 | N | 夠多（建議 > 5,000） | 太少統計不穩定 |

### 記下（後續步驟要用）

- `file_count` 的 P25 / P50 / P75 / P95 / P99 → Step 3 決定分組邊界
- `queue_duration` 的 P95 / P99 / max → Step 2 判斷 queue stuck 閾值是否合理
- `device_duration_avg` 的 P50 / P95 → 心裡有底：device side 正常大概幾秒

---

## Step 1 — EDA + User Contention 偵測

1. 開啟 `notebooks/step1_eda_contention.ipynb`
2. 修改 PARAMS cell：

| 參數 | 建議起始值 | 說明 |
|------|-----------|------|
| `CONTENTION_WINDOW_MINUTES` | 30 | 同 device 多單的時間窗口 |
| `CONTENTION_MIN_ORDERS` | 3 | 窗口內最少幾單算 contention |
| `TOP_N_MODELS` | 15 | Device model 圖表顯示前幾名 |

3. **Run All Cells**

### 檢查重點

**Part A — EDA 圖表**

| 圖表 | 看什麼 | 正常 | 異常（需注意） |
|------|--------|------|---------------|
| Phase Distributions (4 panels) | 四段耗時的形狀 | Queue 集中在低值（< 60s），Device 是最寬的分佈 | Queue 有長尾 → 可能有 queue stuck；Device 呈雙峰 → 可能有慢機台 |
| Device Model (Top N) | 各型號訂單數 | 幾個主要型號佔多數 | 某型號訂單異常多或少 → 了解就好，Step 4 會深入 |
| Usage Heatmap (3 panels) | 使用者行為 pattern | 工作時間（8-18h）訂單較多 | 某 loc_2 在特定時段爆量 → 可能造成 contention |

**Part B — Contention 偵測**

| 輸出 | 看什麼 | 正常 | 需調參 |
|------|--------|------|--------|
| Contention Count Histogram | X 軸是同 device 30min 內的 order 數，Y 是筆數 | 絕大多數 = 1（只有自己），少量 ≥ 3 | 幾乎全部 = 1 → 沒 contention 問題，或 window 太小 |
| Contention 佔比 | `Contention orders: N (X%)` | 0.5% - 5% | > 10% → threshold 太低，提高 min_orders；< 0.1% → 可能不存在 |

**Part C — Uplift Validation（最重要）**

| 輸出 | 看什麼 | 意義 |
|------|--------|------|
| Uplift Histogram | Contention 訂單的 device_duration 相對同 device 正常訂單的倍率 | 分佈集中在 1.0 附近 = 無影響；偏右 (> 1.3) = contention 確實造成劣化 |
| Uplift P50 | 中位數 uplift | > 1.3 → 有效，保留；≈ 1.0 → 無效，調參或跳過 |
| Verdict（✅/⚠️/ℹ️） | Notebook 自動判定 | 照判定走 |

**如果 uplift ≈ 1.0，調參數重試**：
- 縮小 window：30 → 15 → 10 → 5
- 提高 min_orders：3 → 5
- 如果怎麼調都 ≈ 1.0 → 此系統沒有 contention 問題，不需修改 CSV（全為 False），直接進 Step 2

**產出**：`data/user_anomaly_flags.csv`

---

## Step 2 — System Anomaly 偵測

1. 開啟 `notebooks/step2_system_anomaly.ipynb`
2. 修改 PARAMS cell：

| 參數 | 建議起始值 | 說明 |
|------|-----------|------|
| `IQR_MULTIPLIER` | 3 | per-device IQR 倍數。越大越嚴格 |
| `QUEUE_STUCK_PERCENTILE` | 99.0 | queue stuck 取 non-contention 的第幾 percentile |

3. **Run All Cells**

### 偵測方式：三層 Hierarchical Threshold

```
該 device 訂單 ≥ MIN_ORDERS_PER_DEVICE?
  ├─ Yes → per-device IQR（最精準，同一台 device 的 baseline）
  └─ No → 該 model 訂單 ≥ MIN_ORDERS_PER_MODEL?
           ├─ Yes → per-model IQR（同型號 device 效能相近）
           └─ No  → global P99（兜底）
```

少量訂單的 device 不會被無意義的 per-device IQR 誤判。

### 異常類型標記

每筆訂單會被標記 `anomaly_type`：

| Label | 含義 | 觸發條件 |
|-------|------|---------|
| `normal` | 正常 | 未觸發任何閾值 |
| `user_contention` | User 行為 | Step 1 標記的 contention |
| `device_timeout` | Device 異常 | device_duration > 閾值 |
| `db_lock` | DB 異常 | db_duration > 閾值 |
| `queue_stuck` | Queue 異常 | queue_duration > P{percentile} |
| `device_timeout, db_lock` | 多重異常 | 同時觸發多個條件 |

### 檢查重點

| 輸出 | 看什麼 | 通過 | 需調整 |
|------|--------|------|--------|
| Threshold assignment | per-device / per-model / global 各幾台 | 三層都有分配 | 全部 global → MIN_ORDERS 太高 |
| System anomalies 佔比 | `System anomalies: N (X%)` | 1% - 5% | > 10% → 提高 IQR_MULTIPLIER；< 1% → 降低 |
| Type breakdown | queue_stuck / device_timeout / db_lock 各幾筆 | 3 種都有出現 | 只有一種 → 可能正常，但要確認 |
| Label distribution | 全部訂單的 anomaly_type 分佈 | normal > 90% | normal < 80% → 閾值太寬鬆 |
| IQR=0 devices | `IQR=0 (per-device): device=N/M` | < 20% of M | > 20% → IQR 方法不適用 |
| Anomaly by segment | 4-panel: 異常按 loc / system / threshold / timeline 分佈 | 分散 | 集中在某 loc/system → 可能是局部問題 |
| Per-device anomaly rate | 哪些 device 異常率最高 | 分散 | 少數 device 極高 → 可能是壞機台（Step 4 深入）|

**抽查**：Notebook 會印出 20 筆異常 + 20 筆正常的訂單明細。
- 看異常訂單：duration 是否明顯偏高？哪個 phase 造成的？
- 看正常訂單：是否有漏標的（duration 很高但沒被標記）？
- 目標：異常 20 筆中 ≥15 筆確認合理

**調參循環**：
```
IQR_MULTIPLIER: 2 → 2.5 → 3 → 4 → 5
                ← 更多異常    更少異常 →
```

**產出**：`data/system_anomaly_flags.csv`（包含 `order_id`, `is_system_anomaly`, `anomaly_type`）

---

## Step 3 — 正常訂單瓶頸拆解

1. 開啟 `notebooks/step3_bottleneck.ipynb`
2. 修改 PARAMS cell：

| 參數 | 建議起始值 | 說明 |
|------|-----------|------|
| `PARALLELISM` | 4 | 向開發團隊確認 |
| `FILE_COUNT_BINS` | `[0, 50, 300, 1000, 2000, 5000]` | 依 Step 0 的 percentiles 調整 |
| `FILE_COUNT_LABELS` | `['<50', '50-300', ...]` | 與 bins 配套 |

3. **Run All Cells**

### 檢查重點

| 輸出 | 看什麼 | 通過 | 需調整 |
|------|--------|------|--------|
| Orders per group | 每組筆數 | 每組 ≥ 200 | 太少 → 合併相鄰組（改 bins） |
| Model Validation scatter | 散點沿 y=x 紅線分佈 | 緊密貼合 | 散開嚴重 → PARALLELISM 可能不對 |
| Model R² | `Model R²: X.XXX` | > 0.9 | < 0.9 → PARALLELISM 不對，問開發團隊 |
| Ratio by group (bar chart) | 各組的 est/actual 比值 | 都在 0.7-1.3 之間 | 最小組偏低（0.5-0.7）是正常的 = 固定開銷；其他組偏低 → PARALLELISM 偏大 |
| Phase Proportion (%) | 各組的 4 phase 佔比 | Device 佔最大 | Queue 佔很大 → 可能沒正確排除 queue stuck（回 Step 2 調 threshold） |
| Phase Duration (seconds) | 絕對耗時隨 file_count 遞增 | 線性遞增 | 某 phase 不隨 file_count 增加 → 該 phase 是固定開銷 |
| Duration vs File Count | 散點 + trend line | 正斜率，散點沿趨勢線 | 極端離群點 → 可能有未排除的異常（回 Step 2） |

**Phase Proportion 解讀（最重要的結論）**：
- Device 佔最大 → 優化方向：device command 效率、device 硬體/firmware
- DB 佔很大 → 優化方向：DB index、read replica、caching
- Queue 佔很大（不應該）→ 可能 Step 2 沒排乾淨，或 consumer 不夠
- Inner 佔很大 → 優化方向：file check 演算法

**FILE_COUNT_BINS 調整方式**：
- 看 Step 0 的 file_count percentiles
- 邊界選在 round number 且每組 ≥ 200 筆
- 例：如果 P75=500, P95=1500 → `[0, 100, 500, 1500, 3000]`

**SLA 達成率**（新增）：

| 輸出 | 看什麼 | 意義 |
|------|--------|------|
| SLA Compliance table | 每條 SLA rule 的 violation rate | > 5% violation → 該 SLA 目標需要關注 |
| SLA by location | 各 loc 的 violation rate | 某 loc 偏高 → 該地點可能有系統問題 |

SLA 規則在 `config/params.py` 的 `SLA_RULES` 定義，格式：`(max_file_count, max_duration_seconds, label)`

**Tail Order 分析**（新增）：

| 輸出 | 看什麼 | 意義 |
|------|--------|------|
| Tail vs Normal file_count | tail 的 file_count 是否偏大 | 是 → 慢訂單主要是因為 file 多（預期） |
| Tail vs Normal device_dur | tail 的 device_duration 是否偏大 | 是 → 慢訂單的 device 也比較慢（可能是慢機台）|
| Tail rate by location | 各 loc 的 tail 佔比 | 某 loc > 5% → 該地點效能較差 |
| Top models in tail | 哪些 model 貢獻最多 tail | 集中在特定 model → 該型號效能差 |

---

## Step 4 — 慢機台下鑽

1. 開啟 `notebooks/step4_slow_device.ipynb`
2. 修改 PARAMS cell：

| 參數 | 建議起始值 | 說明 |
|------|-----------|------|
| `GAP_MIN_RATIO` | 2.0 | 最大 gap / 下一個值的比值 |
| `PARALLELISM` | 4 | 同 Step 3 |

3. **Run All Cells**

### 檢查重點

| 輸出 | 看什麼 | 正常 | 需注意 |
|------|--------|------|--------|
| Gap detection result | `Method: gap detection (gap=Xs, ratio=Yx)` | ratio ≥ 2.0 且慢機台 median 明顯高 | `Method: fallback` → 沒有明顯 gap，所有 device 差不多 |
| Slow devices 數量 | `Slow devices: N` | 0-20 台 | 0 = 好事；> 20 → GAP_MIN_RATIO 太低 |
| Device Ranking chart | 紅色 = 慢機台，藍色 = 正常 | 紅藍之間有明顯斷層 | 紅藍連續無斷層 → gap detection 可能不適用 |
| 慢機台 order count | 每台的 `n=` 標註 | 每台 ≥ 20 筆 | < 20 → 樣本太少，可能是 noise |
| Facet Analysis (4 panels) | 各切面（loc_1/loc_2/system/model）的 median 差異 | max/min ratio ≈ 1.0 = 無差異 | ratio > 1.5 → 不只是 device 問題，可能是 location 或 system 問題 |
| Slow Device Phase Breakdown | 慢機台上 4 phase 的佔比 | Device（紅色）佔主導 | DB 也很大 → 慢機台可能連 DB 也慢（同 location 的 DB 有問題？）|

**Device 忙碌度 × 效能**（新增）：

| 輸出 | 看什麼 | 意義 |
|------|--------|------|
| Location × Hour heatmap | 各 loc 在各小時的 avg device_duration | 某 loc 在忙碌時段顏色變深 → 負載造成效能下降 |
| Busyness vs Performance scatter | daily orders/device vs avg device_dur | 正相關 → 忙碌確實造成變慢；無相關 → 效能穩定 |

**交付**：將慢機台清單（device_id, median duration, location, system）交設備團隊確認

---

## Step 5 — Summary Dashboard

1. 開啟 `notebooks/step5_dashboard.ipynb`
2. 共用參數已在 `config/params.py`，無需手動同步
3. **Run All Cells**

### 檢查重點

| 輸出 | 看什麼 | 驗證方式 |
|------|--------|---------|
| Executive Summary 文字 | 總訂單、異常數、正常數 | 與 Step 1+2 的數字加總一致 |
| Pie chart | Normal / System / User 比例 | 佔比加總 = 100% |
| Phase Proportion bar | 4 phase 佔比 | 與 Step 3 結論一致 |
| Top Devices | 紅色慢機台數量 | 與 Step 4 一致 |
| Timeline scatter | 紅點分佈 | 與 Step 2 timeline 一致 |
| `reports/dashboard.png` | 檔案存在 | 可用於報告/簡報 |

---

## 參數速查表

| 參數 | 位置 | 效果 |
|------|------|------|
| `CONTENTION_WINDOW_MINUTES` | Step 1 | 縮小 → 更嚴格（更少 contention） |
| `CONTENTION_MIN_ORDERS` | Step 1 | 提高 → 更嚴格 |
| `TOP_N_MODELS` | Step 1 | Device model 圖表顯示前幾名 |
| `IQR_MULTIPLIER` | Step 2 | 提高 → 更嚴格（更少 anomaly） |
| `QUEUE_STUCK_PERCENTILE` | Step 2 | 提高 → 更嚴格 |
| `DATETIME_FORMAT` | `config/params.py` | `order_created_at` 的時間格式 |
| `PARALLELISM` | `config/params.py` | 向開發團隊確認，不要猜 |
| `FILE_COUNT_BINS` | `config/params.py` | 依資料分佈調整（Step 3 決定後改一次） |
| `GAP_MIN_RATIO` | `config/params.py` | 提高 → 更嚴格（更少慢機台） |
| `SLA_RULES` | `config/params.py` | `[(max_fc, max_dur_sec, label), ...]` 定義 SLA 目標 |

---

## 常見陷阱

| 陷阱 | 症狀 | 解法 |
|------|------|------|
| PARALLELISM 不對 | Model R² 很低 | 問開發團隊 |
| 資料時間太短 | 某些 device < 10 筆 | 要求更長時間的資料 |
| order_id 重複 | Step 0 報錯 | 先 dedup |
| 排程性 batch | 固定時間大量訂單被標 contention | 用 hour-of-day filter 排除 |
| Contention 但 device 沒變慢 | uplift ≈ 1.0 | 跳過 Layer 1b |
| 所有 device 都差不多慢 | Step 4 找不到 gap | 不是 device 問題，看 Step 3 的 phase 瓶頸 |

---

## 檔案結構

```
perf-profiling/
├── config/
│   ├── schema.yaml                    # 欄位定義
│   └── params.py                      # ← 共用參數（改這裡）
├── data/
│   ├── orders.csv                     # ← 放真實資料
│   ├── user_anomaly_flags.csv         # Step 1 產出
│   └── system_anomaly_flags.csv       # Step 2 產出
├── notebooks/
│   ├── step0_data_sanity.ipynb        # 資料健檢
│   ├── step1_eda_contention.ipynb     # EDA + contention
│   ├── step2_system_anomaly.ipynb     # 系統異常
│   ├── step3_bottleneck.ipynb         # 瓶頸拆解
│   ├── step4_slow_device.ipynb        # 慢機台
│   └── step5_dashboard.ipynb          # Dashboard
├── reports/                           # 圖表（notebook 產生）
├── samples/                           # 合成資料的分析範例（供對照）
└── docs/
    └── MIGRATION_GUIDE.md             # 本文件
```
