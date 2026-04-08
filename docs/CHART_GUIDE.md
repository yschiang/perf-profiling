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
| **`step1_user_wait_time.png`** | ⭐ | 使用者實際等待時間分佈 | `total_file_duration_minutes` histogram + `total_duration_seconds` histogram + file_count scatter |
| **`step1_duration_trend.png`** | ⭐ | 每日 P50/P95/P99 趨勢 | `total_duration_seconds` groupby date → quantile(0.5/0.95/0.99) |
| `step1_phase_distributions.png` | | 四段耗時分佈 | `queue/device/db/inner_duration_avg_seconds` 各自 histogram |
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

依賴：`data/user_anomaly_flags.csv` + `data/system_anomaly_flags.csv`（排除異常後分析）

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step3_phase_breakdown.png`** | ⭐ | phase 佔比 — 瓶頸在哪？ | `est_phase = phase_avg × file_count / PARALLELISM`，groupby `fc_group` stacked bar |
| **`step3_tail_analysis.png`** | ⭐ | P95+ 慢訂單特徵 | `total_duration > P95` 的訂單 vs 其餘，比較 file_count/device_dur/loc/model |
| `step3_model_validation.png` | | phase model 驗證 | `est_total` vs `total_duration_seconds` scatter + R² |
| `step3_duration_vs_filecount.png` | | duration vs file_count | scatter + polyfit trend line |
| `step3_sla_compliance.png` | | SLA 達成率 | 按 `SLA_RULES` 每條計算 `total_duration > threshold` 的 violation rate |
| `step3_sla_by_location.png` | | SLA violation by loc | 同上，groupby `loc_1` |

---

## Step 4 — Slow Device

依賴：同 Step 3（排除異常後的正常訂單）

| Chart | Key? | 說明 | 生產邏輯 |
|-------|------|------|---------|
| **`step4_device_ranking.png`** | ⭐ | device 排名 — 慢機台 | `device_duration_avg` groupby `device_id` → median，sort desc，gap detection 或 fallback P99 |
| **`step4_device_utilization.png`** | ⭐ | 忙碌度 vs 效能 | loc×hour heatmap: avg `device_duration`；scatter: daily orders/device vs avg device_dur |
| `step4_facet_analysis.png` | | 切面分析 | `device_duration_avg` groupby `loc_1`/`loc_2`/`system_name`/`device_mode_name` → median bar |
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
