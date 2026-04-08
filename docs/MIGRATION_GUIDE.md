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
2. 編輯 **`config/params.py`** — 所有參數集中在此，改一次全部 notebook 生效：
   - `DATA_PATH`：資料路徑
   - `DATETIME_FORMAT`：`order_created_at` 的時間格式
   - `PARALLELISM`：向開發團隊確認
   - 其他參數可先用預設值，按步驟調整
3. 確認已安裝：`pandas numpy matplotlib seaborn jupyter`

---

## Step 0 — 資料健檢

1. 開啟 `notebooks/step0_data_sanity.ipynb`
2. **Run All Cells**（參數從 `config/params.py` 自動載入）

### 檢查重點

| 項目 | 看什麼 | 通過條件 | 不通過代表什麼 |
|------|--------|---------|---------------|
| Schema 驗證 | 欄位是否與 schema.yaml 一致 | 全部存在 | 資料欄位不匹配 |
| order_id | 重複數量 | = 0 | 資料有 dup，需先 dedup |
| null 欄位 | 各欄位 null 比例 | device_mode_name, loc_2 可有 null，其他 = 0 | 資料不完整，確認 ETL |
| 負數 duration | 各 duration 欄位 < 0 的筆數 | = 0 | 資料異常，確認來源 |
| 時間範圍 | min ~ max date | 涵蓋你預期的分析區間 | 資料可能被截斷 |
| 總筆數 | N | 夠多（建議 > 5,000） | 太少統計不穩定 |

### 記下（後續步驟要用）

- `file_count` 的 P25 / P50 / P75 / P95 / P99 → 調整 `FILE_COUNT_BINS`
- `queue_duration` 的 P95 / P99 / max → 判斷 queue stuck 閾值
- `device_duration_avg` 的 P50 / P95 → 調整 `MIN_DEVICE_THRESHOLD`

### 產出

| 檔案 | 說明 |
|------|------|
| `reports/step0_summary.txt` | 資料健檢報告（含 percentiles） |

---

## Step 1 — EDA + User Contention 偵測

1. 開啟 `notebooks/step1_eda_contention.ipynb`
2. 如需調整參數，編輯 `config/params.py`：
   - `CONTENTION_WINDOW_MINUTES`（預設 30）
   - `CONTENTION_MIN_ORDERS`（預設 3）
   - `TOP_N_MODELS`（預設 15）
3. **Run All Cells**

### 檢查重點

**Part A — EDA 圖表**

| 圖表（報表檔案） | 看什麼 | 正常 | 異常（需注意） |
|------|--------|------|---------------|
| Phase Distributions (`step1_phase_distributions.png`) | 四段耗時的形狀 | Queue 集中在低值，Device 是最寬的分佈 | Queue 有長尾 → 可能有 queue stuck；Device 呈雙峰 → 可能有慢機台 |
| User Wait Time (`step1_user_wait_time.png`) | total_file_duration 和 total_duration 分佈 | 右偏分佈 | P95 遠大於 P50 → 長尾問題嚴重 |
| Duration Trend (`step1_duration_trend.png`) | 每日 P50/P95/P99 折線 | 穩定或下降 | 持續上升 → 系統在劣化 |
| Device Model (`step1_device_model_order_dist.png`) | 各型號訂單數 | 幾個主要型號佔多數 | 了解設備組成 |
| Usage Heatmap (`step1_usage_heatmap.png`) | loc × hour / day / date | 工作時間訂單較多 | 某 loc 在特定時段爆量 |
| Usage Tables (`step1_table_loc*.png`) | 精確的 loc × date/hour 數字 | 均勻分佈 | 某格異常高 |

**Part B — Contention 偵測**

| 輸出（報表檔案） | 看什麼 | 正常 | 需調參 |
|------|--------|------|--------|
| Contention Count (`step1_contention_count.png`) | X 軸是同 device 窗口內 order 數 | 絕大多數 = 1 | 全部 = 1 → 沒 contention，或 window 太小 |
| Contention 佔比 | `Contention orders: N (X%)` | 0.5% - 5% | > 10% → 提高 min_orders；< 0.1% → 可能不存在 |

**Part C — Uplift Validation（最重要）**

| 輸出（報表檔案） | 看什麼 | 意義 |
|------|--------|------|
| Uplift Histogram (`step1_uplift.png`) | contention vs normal 的 device_duration 倍率 | 1.0 = 無影響；> 1.3 = 有影響 |
| Verdict（✅/⚠️/ℹ️） | Notebook 自動判定 | 照判定走 |

**如果 uplift ≈ 1.0，調參數重試**（在 `config/params.py` 修改）：
- 縮小 `CONTENTION_WINDOW_MINUTES`：30 → 15 → 10 → 5
- 提高 `CONTENTION_MIN_ORDERS`：3 → 5
- 如果怎麼調都 ≈ 1.0 → 此系統沒有 contention 問題，直接進 Step 2

### 產出

| 檔案 | 說明 |
|------|------|
| `data/user_anomaly_flags.csv` | 每筆 order 的 contention 標記 |
| `reports/step1_summary.txt` | EDA + contention 結果摘要 |
| `reports/step1_usage_tables.txt` | loc × date/hour 精確數字 |
| `reports/step1_*.png` | 10 張圖表 |

---

## Step 2 — System Anomaly 偵測

1. 開啟 `notebooks/step2_system_anomaly.ipynb`
2. 如需調整參數，編輯 `config/params.py`：
   - `IQR_MULTIPLIER`（預設 3）
   - `QUEUE_STUCK_PERCENTILE`（預設 99.0）
   - `MIN_ORDERS_PER_DEVICE`（預設 20）
   - `MIN_ORDERS_PER_MODEL`（預設 30）
   - `MIN_DEVICE_THRESHOLD`（預設 20s）— device 閾值下限，避免 IQR≈0 時過度靈敏
   - `MIN_DB_THRESHOLD`（預設 5s）— db 閾值下限
3. **Run All Cells**

### 偵測方式：三層 Hierarchical Threshold

```
該 device 訂單 ≥ MIN_ORDERS_PER_DEVICE?
  ├─ Yes → per-device IQR（最精準）
  └─ No → 該 model 訂單 ≥ MIN_ORDERS_PER_MODEL?
           ├─ Yes → per-model IQR（同型號參考）
           └─ No  → global P99（兜底）

所有閾值都有下限保護：
  device 閾值 = max(IQR算出的值, MIN_DEVICE_THRESHOLD)
  db 閾值 = max(IQR算出的值, MIN_DB_THRESHOLD)
```

### 異常類型標記

每筆訂單會被標記 `anomaly_type`：

| Label | 含義 | 觸發條件 |
|-------|------|---------|
| `normal` | 正常 | 未觸發任何閾值 |
| `user_contention` | User 行為 | Step 1 標記的 contention |
| `device_timeout` | Device 異常 | device_duration > 閾值 |
| `db_lock` | DB 異常 | db_duration > 閾值 |
| `queue_stuck` | Queue 異常 | queue_duration > P{percentile} |
| 多重（如 `device_timeout, db_lock`） | 多重異常 | 同時觸發多個條件 |

### 檢查重點

| 輸出（報表檔案） | 看什麼 | 通過 | 需調整 |
|------|--------|------|--------|
| Threshold assignment | per-device / per-model / global 各幾台 | 三層都有 | 全部 global → MIN_ORDERS 太高 |
| System anomalies 佔比 | `System anomalies: N (X%)` | 1% - 5% | > 10% → 提高 IQR_MULTIPLIER；< 1% → 降低 |
| Type breakdown | 各類異常筆數 | 3 種都有 | 某類過多 → 可能 MIN_*_THRESHOLD 太低 |
| Label distribution | normal > 90% | normal > 90% | < 80% → 閾值太寬鬆 |
| Anomaly by segment (`step2_anomaly_by_segment.png`) | 按 loc/system/threshold/timeline 分佈 | 分散 | 集中某 loc → 局部問題 |
| Anomaly trend (`step2_anomaly_trend.png`) | 每日異常率 | 穩定 | 持續上升 → 系統劣化 |
| Per-device rate (`step2_device_anomaly_rate.png`) | 哪些 device 異常率最高 | 分散 | 少數極高 → 壞機台 |
| Anomaly type chart (`step2_system_anomaly.png`) | 類型分佈 + timeline | — | — |

**抽查**：Notebook 印出 20 筆異常 + 20 筆正常訂單。目標：異常 20 筆中 ≥15 筆確認合理。

**調參循環**（在 `config/params.py` 修改）：
```
IQR_MULTIPLIER: 2 → 2.5 → 3 → 4 → 5    ← 更多異常    更少異常 →
MIN_DEVICE_THRESHOLD: 10 → 15 → 20 → 30  ← 更多 device_timeout  更少 →
MIN_DB_THRESHOLD: 2 → 5 → 10             ← 更多 db_lock  更少 →
```

### 產出

| 檔案 | 說明 |
|------|------|
| `data/system_anomaly_flags.csv` | order_id + is_system_anomaly + anomaly_type |
| `reports/step2_summary.txt` | 異常偵測結果摘要 |
| `reports/step2_*.png` | 4 張圖表 |

---

## Step 3 — 正常訂單瓶頸拆解

1. 開啟 `notebooks/step3_bottleneck.ipynb`
2. 如需調整參數，編輯 `config/params.py`：
   - `PARALLELISM`（向開發團隊確認）
   - `FILE_COUNT_BINS`（預設 `[0, 100, 1000, 2000, 100000]`，依 Step 0 的 percentiles 調整）
   - `FILE_COUNT_LABELS`（與 bins 配套）
   - `SLA_RULES`（SLA 目標定義）
3. **Run All Cells**

### 檢查重點

| 輸出（報表檔案） | 看什麼 | 通過 | 需調整 |
|------|--------|------|--------|
| Orders per group | 每組筆數 | 每組 ≥ 200 | 太少 → 合併相鄰組（改 bins） |
| Model Validation (`step3_model_validation.png`) | 散點沿 y=x 分佈 + R² | R² > 0.9 | < 0.9 → PARALLELISM 不對 |
| Ratio by group | 各組 est/actual 比值 | 0.7 - 1.3 | 最小組偏低是正常的（固定開銷） |
| Phase Proportion (`step3_phase_breakdown.png`) | 各組 4 phase 佔比 | Device 佔最大 | Queue 佔很大 → 回 Step 2 |
| Duration vs File Count (`step3_duration_vs_filecount.png`) | 散點 + trend line | 正斜率 | 極端離群點 → 未排除的異常 |
| SLA Compliance (`step3_sla_compliance.png`) | 每條 SLA rule 的 violation rate | < 5% | > 5% → 需關注 |
| SLA by location (`step3_sla_by_location.png`) | 各 loc 的 violation rate | 均勻 | 某 loc 偏高 → 局部問題 |
| Tail Analysis (`step3_tail_analysis.png`) | P95+ 訂單特徵 | — | — |

**Phase Proportion 解讀（最重要的結論）**：
- Device 佔最大 → 優化方向：device command 效率、device 硬體/firmware
- DB 佔很大 → 優化方向：DB index、read replica、caching
- Queue 佔很大（不應該）→ 可能 Step 2 沒排乾淨，或 consumer 不夠
- Inner 佔很大 → 優化方向：file check 演算法

**SLA 規則**：在 `config/params.py` 的 `SLA_RULES` 定義，格式：`(max_file_count, max_duration_seconds, label)`

**Tail Order 分析**：

| 看什麼 | 意義 |
|--------|------|
| Tail file_count 是否偏大 | 是 → 慢訂單因 file 多（預期） |
| Tail device_dur 是否偏大 | 是 → 慢訂單 device 也慢（慢機台） |
| Tail rate by location | 某 loc > 5% → 該地點效能差 |
| Top models in tail | 集中特定 model → 該型號效能差 |

### 產出

| 檔案 | 說明 |
|------|------|
| `reports/step3_summary.txt` | 瓶頸分析 + SLA + Tail 結果 |
| `reports/step3_*.png` | 5 張圖表 |

---

## Step 4 — 慢機台下鑽

1. 開啟 `notebooks/step4_slow_device.ipynb`
2. 如需調整參數，編輯 `config/params.py`：
   - `GAP_MIN_RATIO`（預設 2.0）
3. **Run All Cells**

### 檢查重點

| 輸出（報表檔案） | 看什麼 | 正常 | 需注意 |
|------|--------|------|--------|
| Gap detection result | `Method: gap detection` 或 `fallback` | gap ratio ≥ 2.0 | `fallback` → 分佈連續，無明顯斷層 |
| Slow devices 數量 | `Slow devices: N` | 0-20 台 | 0 = 好事；> 50 → 閾值太低 |
| Device Ranking (`step4_device_ranking.png`) | 紅=慢，藍=正常 | 紅藍斷層明顯 | 連續 → gap detection 不適用 |
| 慢機台 order count | 每台 `n=` | ≥ 20 | < 10 → noise |
| Facet Analysis (`step4_facet_analysis.png`) | loc/system/model 差異 | max/min ≈ 1.0 | > 1.5 → location/system level 問題 |
| Phase Breakdown (`step4_slow_device_breakdown.png`) | 慢機台上各 phase 佔比 | Device 主導 | DB 也高 → 同 location DB 有問題 |
| Utilization (`step4_device_utilization.png`) | loc×hour heatmap + busyness scatter | 無相關 | 正相關 → 忙碌時 device 變慢 |

**交付**：將慢機台清單交設備團隊確認

### 產出

| 檔案 | 說明 |
|------|------|
| `reports/step4_summary.txt` | 慢機台清單 + facet 結論 |
| `reports/step4_*.png` | 4 張圖表 |

---

## Step 5 — Summary Dashboard

1. 開啟 `notebooks/step5_dashboard.ipynb`
2. **Run All Cells**（參數從 `config/params.py` 自動載入）

### 檢查重點

| 輸出 | 看什麼 | 驗證方式 |
|------|--------|---------|
| Executive Summary | 總訂單、異常數、正常數 | 與 Step 1+2 數字一致 |
| Label 分佈 | 每種 anomaly_type 的佔比 | 與 Step 2 summary 一致 |
| Pie chart | Normal / System / User | 加總 = 100% |
| Phase Proportion bar | 4 phase 佔比 | 與 Step 3 一致 |
| Top Devices | 慢機台數量 | 與 Step 4 一致 |
| `reports/dashboard.png` | 6-panel 圖 | 可用於報告 |

### 產出

| 檔案 | 說明 |
|------|------|
| `reports/step5_summary.txt` | Executive Summary 文字版 |
| `reports/dashboard.png` | 6-panel 綜合 dashboard |

---

## 參數速查表

所有參數都在 `config/params.py`，改一次全部 notebook 生效。

| 參數 | 預設值 | 效果 |
|------|--------|------|
| `DATA_PATH` | `'../data/orders.csv'` | 資料路徑 |
| `DATETIME_FORMAT` | `'%Y-%m-%d %H:%M:%S.%f'` | 時間格式 |
| `PARALLELISM` | 4 | 並行 thread 數（問開發團隊） |
| `CONTENTION_WINDOW_MINUTES` | 30 | 縮小 → 更嚴格 |
| `CONTENTION_MIN_ORDERS` | 3 | 提高 → 更嚴格 |
| `TOP_N_MODELS` | 15 | model 表格前幾名 |
| `IQR_MULTIPLIER` | 3 | 提高 → 更少異常 |
| `QUEUE_STUCK_PERCENTILE` | 99.0 | 提高 → 更嚴格 |
| `MIN_ORDERS_PER_DEVICE` | 20 | device 訂單 ≥ 此值才用 per-device IQR |
| `MIN_ORDERS_PER_MODEL` | 30 | model 訂單 ≥ 此值才用 per-model IQR |
| `MIN_DEVICE_THRESHOLD` | 20 | device 閾值下限（秒），防止 IQR≈0 過度靈敏 |
| `MIN_DB_THRESHOLD` | 5 | db 閾值下限（秒） |
| `FILE_COUNT_BINS` | `[0,100,1000,2000,100000]` | 依 Step 0 percentiles 調整 |
| `FILE_COUNT_LABELS` | `['<100','100-1000',...]` | 與 bins 配套 |
| `GAP_MIN_RATIO` | 2.0 | 提高 → 更少慢機台 |
| `SLA_RULES` | 見 params.py | `[(max_fc, max_dur, label), ...]` |

---

## 全部產出清單

| Step | 報表檔案 | 說明 |
|------|---------|------|
| 0 | `step0_summary.txt` | 資料健檢 |
| 1 | `step1_phase_distributions.png` | 四段耗時分佈 |
| 1 | `step1_user_wait_time.png` | 使用者等待時間 |
| 1 | `step1_duration_trend.png` | 每日 P50/P95 趨勢 |
| 1 | `step1_device_model_order_dist.png` | 設備型號訂單分佈 |
| 1 | `step1_usage_heatmap.png` | loc × time 熱力圖 |
| 1 | `step1_table_loc2_hour.png` | loc × hour 數字表 |
| 1 | `step1_table_loc2_date.png` | loc × date 數字表 |
| 1 | `step1_table_loc1_date.png` | loc_1 × date 數字表 |
| 1 | `step1_contention_count.png` | contention 分佈 |
| 1 | `step1_uplift.png` | contention uplift 驗證 |
| 1 | `step1_summary.txt` | EDA 摘要 |
| 1 | `step1_usage_tables.txt` | loc × time 數字（文字版） |
| 2 | `step2_system_anomaly.png` | 異常類型 + timeline |
| 2 | `step2_anomaly_by_segment.png` | 異常按 loc/system/threshold 分佈 |
| 2 | `step2_anomaly_trend.png` | 每日異常率趨勢 |
| 2 | `step2_device_anomaly_rate.png` | per-device 異常率 top 20 |
| 2 | `step2_summary.txt` | 異常偵測摘要 |
| 3 | `step3_model_validation.png` | phase model 驗證 |
| 3 | `step3_phase_breakdown.png` | phase 佔比 stacked bar |
| 3 | `step3_duration_vs_filecount.png` | duration vs file_count scatter |
| 3 | `step3_sla_compliance.png` | SLA 達成率表 |
| 3 | `step3_sla_by_location.png` | SLA violation by location |
| 3 | `step3_tail_analysis.png` | P95+ tail order 特徵 |
| 3 | `step3_summary.txt` | 瓶頸分析摘要 |
| 4 | `step4_device_ranking.png` | device 排名（紅=慢） |
| 4 | `step4_facet_analysis.png` | loc/system/model 切面 |
| 4 | `step4_slow_device_breakdown.png` | 慢機台 phase breakdown |
| 4 | `step4_device_utilization.png` | 忙碌度 vs 效能 |
| 4 | `step4_summary.txt` | 慢機台清單 |
| 5 | `dashboard.png` | 6-panel 綜合 dashboard |
| 5 | `step5_summary.txt` | Executive Summary |

---

## 常見陷阱

| 陷阱 | 症狀 | 解法 |
|------|------|------|
| PARALLELISM 不對 | Model R² 很低 | 問開發團隊 |
| 資料時間太短 | 某些 device < 10 筆 | 要求更長時間的資料 |
| order_id 重複 | Step 0 報錯 | 先 dedup |
| 排程性 batch | 固定時間大量訂單被標 contention | 用 hour-of-day filter 排除 |
| Contention 但 device 沒變慢 | uplift ≈ 1.0 | 跳過 contention 偵測 |
| 所有 device 都差不多慢 | Step 4 找不到 gap | 不是 device 問題，看 Step 3 phase |
| db_lock 過多 | > 5% 訂單被標 db_lock | 提高 MIN_DB_THRESHOLD |
| device_timeout 過多 | > 5% 被標 | 提高 MIN_DEVICE_THRESHOLD |

---

## 檔案結構

```
perf-profiling/
├── config/
│   ├── schema.yaml                    # 欄位定義
│   └── params.py                      # ← 所有參數（改這裡）
├── data/
│   ├── orders.csv                     # ← 放真實資料
│   ├── user_anomaly_flags.csv         # Step 1 產出
│   └── system_anomaly_flags.csv       # Step 2 產出
├── notebooks/
│   ├── step0_data_sanity.ipynb
│   ├── step1_eda_contention.ipynb
│   ├── step2_system_anomaly.ipynb
│   ├── step3_bottleneck.ipynb
│   ├── step4_slow_device.ipynb
│   └── step5_dashboard.ipynb
├── reports/                           # 圖表 + 文字摘要（notebook 產生）
├── samples/                           # 合成資料範例（供對照）
└── docs/
    └── MIGRATION_GUIDE.md             # 本文件
```
