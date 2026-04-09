# Chart Guide — Key Charts per Step

每個步驟產出多張圖表，以下標註 **Key Chart**（最重要、優先看的）。

## 生產邏輯

```
data/orders.csv
  → Step 0 (健檢)
  → Step 1 (EDA + contention) → data/user_anomaly_flags.csv
  → Step 2 (系統異常)          → data/system_anomaly_flags.csv
  → Step 3 (瓶頸拆解，排除異常後)
  → Step 4 (慢機台，排除異常後)
  → Step 5 (Dashboard，整合全部)
  → Step 6 (Capacity Sizing)
```

每個 step 產出圖表到 `reports/` + 文字摘要到 `reports/stepN_summary.txt`。

## 怎麼看表格

| 欄位 | 意義 |
|------|------|
| **Chart** | 檔名，在 `reports/` 目錄下 |
| **Key?** | ⭐ = 最重要、優先看的圖。沒標的是補充性質 |
| **說明** | 這張圖在看什麼 |
| **生產邏輯** | 資料來源、計算方式、依賴哪些欄位或前置步驟 |

---

## Step 1 — EDA + Contention

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step1_bin_statistics.png`** | ⭐ | 按 order 的 file_count 分 bin 統計總表 | `pd.cut(file_count, FILE_COUNT_BINS)` groupby → orders/orders%/unique devices/devices%/file_count median+mean/total_dur median+P95+std/device_dur median+P95/db_dur median/queue_dur median。Total row 只顯示 counts/pct，export CSV + table image |
| **`step1_user_wait_time.png`** | ⭐ | 使用者實際等待時間分佈 | `total_file_duration_minutes` histogram + `total_duration_seconds` histogram + file_count scatter |
| **`step1_duration_trend.png`** | ⭐ | 每日 P50/P95/P99 趨勢 + 下方數值表 | `total_duration_seconds` groupby date → quantile(0.5/0.95/0.99)，轉分鐘。上方折線+volume bar，下方每日 P50/P95/P99/Volume table。`TREND_LAST_N_DAYS` 控制顯示天數 |
| **`step1_phase_distributions.png`** | ⭐ | 四段耗時分佈（共用 x-axis，一眼看出瓶頸 phase） | `queue/device/db/inner_duration_avg_seconds` 各自 histogram，共用 x-axis 上限（4 欄 P99×1.5 取最大值） |
| `step1_usage_heatmap.png` | | loc × time 熱力圖 | `loc_2` × `hour`/`dow`/`date` groupby count heatmap |
| `step1_table_loc*.png` | | loc × time 數字表 | 同上，render 成 table image |
| `step1_contention_count.png` | | contention 偵測分佈 | 同 device 在 [t, t+WINDOW] 內的 order count histogram |
| `step1_uplift.png` | | contention uplift 驗證 | per-device: contention orders 的 `device_duration_avg` median ÷ non-contention median |

---

## Step 2 — System Anomaly

依賴：`data/user_anomaly_flags.csv`（Step 1 產出）

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step2_anomaly_by_segment.png`** | ⭐ | 異常按維度分佈 | `anomaly_type` groupby `loc_1`/`system_name`/`threshold_source` + timeline scatter by type |
| **`step2_anomaly_trend.png`** | ⭐ | 每日異常率趨勢 | `is_system_anomaly` groupby date → mean |
| `step2_system_anomaly.png` | | 異常類型 + timeline | `anomaly_type` explode value_counts + timeline scatter |
| `step2_device_anomaly_rate.png` | | per-device 異常率 | `is_system_anomaly` groupby `device_id` → mean, top 20 |

---

## Step 3 — Bottleneck Breakdown

依賴：`data/user_anomaly_flags.csv` + `data/system_anomaly_flags.csv`
資料範圍：排除 system anomaly + user contention。目的：看**系統正常運作時**的瓶頸在哪。一次性 spike（device timeout 500s、DB lock 1200s）會扭曲 phase proportion，需排除。

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step3_phase_breakdown.png`** | ⭐ | phase 佔比 — 瓶頸在哪？ | `est_phase = phase_avg × file_count / PARALLELISM`，groupby `fc_group` stacked bar |
| **`step3_tail_analysis.png`** | ⭐ | P95+ 慢訂單為什麼慢？(2×2) | **左上 File Count**：tail(橘) vs normal(藍) density — 橘色明顯偏右=file 多是慢的主因，重疊=不是主因。**右上 Device Duration**：同理 — 偏右=device 慢是主因。兩張一起看：判斷慢訂單是「file 太多」還是「device 太慢」或兩者皆有。**左下 Tail Rate by loc_1**：各 location 的 tail 佔比，灰虛線=預期 5%，超過=該 location 產生更多慢訂單。**右下 Top 10 Models**：哪些 device model 貢獻最多 tail orders |
| `step3_model_validation.png` | | phase model 驗證 | `est_total` vs `total_duration_seconds` scatter + R² |
| `step3_duration_vs_filecount.png` | | duration vs file_count | scatter + polyfit trend line |
| `step3_sla_compliance.png` | | SLA 達成率 | 按 `SLA_RULES` 每條計算 `total_duration > threshold` 的 violation rate |
| `step3_sla_by_location.png` | | SLA violation by loc | 同上，groupby `loc_1` |

---

## Step 4 — Slow Device

依賴：`data/user_anomaly_flags.csv`（僅排除 user contention）
資料範圍：全部訂單，僅排除 user contention。目的：看每台 device 的**完整表現**。Step 2 標為 anomaly 的訂單可能是 slow device 的正常高值，排除會壓低 median 導致漏掉 slow device。

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step4_device_ranking.png`** | ⭐ | device 排名 — 慢機台 | `device_duration_avg` groupby `device_id` → median，sort desc，gap detection 或 fallback P99 |
| `step4_device_utilization.png` | | 忙碌度 vs 效能 | loc×hour heatmap: avg `device_duration`；scatter: daily orders/device vs avg device_dur |
| `step4_facet_analysis.png` | | 切面分析 | `device_duration_avg` groupby `loc_1`/`loc_2`/`system_name`/`device_mode_name` → median bar |
| **`step4_usage_vs_performance.png`** | ⭐ | 使用量 × 效能 scatter | X=device 訂單數(=user 使用量), Y=device_dur median, 紅=slow device。四象限：右上=又常用又慢→Priority fix，左上=低使用量+慢→影響小，右下=常用+快→OK |
| **`step4_usage_cross_analysis.png`** | ⭐ | 使用量 × 效能交叉分析表 | 按 usage(High/Low) × speed(Fast/Slow) 四象限統計 devices 數、total orders、duration median、priority 等級。紅底=Priority（又常用又慢）|
| `step4_slow_device_breakdown.png` | | 慢機台 phase breakdown | 慢機台 orders 的 `est_queue/db/device/inner` stacked barh |

---

## Step 5 — Dashboard

依賴：同 Step 3 + Step 4 邏輯

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`dashboard.png`** | ⭐ | 6-panel 綜合 dashboard | duration dist / pie / phase bar / fc group bar / top devices / timeline |

---

## Step 6 — Capacity Sizing

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step6_concurrency.png`** | ⭐ | concurrent orders — 資源規劃依據 | Little's Law: `orders/hr × avg_duration / 3600`，用 avg dur 和 P95 dur 兩種估算 |
| **`step6_hourly_capacity.png`** | ⭐ | 每小時 avg/peak/burst/buffer | 全系統 (含 null loc_2) groupby hour → avg/max + burst/buffer 水平線 |
| `step6_current_capacity.png` | | loc × hour heatmap | `loc_2` × `hour` groupby count → avg/peak pivot heatmap |
| `step6_burst_scenarios.png` | | burst 場景比較 | 每個 loc_2 輪流 ×BURST_MULTIPLIER + 其他 loc peak + null peak，stacked bar |
