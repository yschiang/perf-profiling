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

---

## Step 1 — EDA + Contention

| Chart | Key? | 說明 |
|-------|------|------|
| **`step1_user_wait_time.png`** | ⭐ | 使用者實際等待時間分佈 + 與 file_count 的關係 |
| **`step1_duration_trend.png`** | ⭐ | 每日 P50/P95/P99 趨勢 — 系統在變好還是變差？ |
| `step1_phase_distributions.png` | | 四段耗時（queue/device/db/inner）分佈 |
| `step1_usage_heatmap.png` | | loc × hour/day/date 熱力圖 |
| `step1_table_loc2_hour.png` | | loc × hour 精確數字表 |
| `step1_table_loc2_date.png` | | loc × date 精確數字表 |
| `step1_table_loc1_date.png` | | loc_1 × date 精確數字表 |
| `step1_contention_count.png` | | contention 偵測分佈 |
| `step1_uplift.png` | | contention uplift 驗證 |

---

## Step 2 — System Anomaly

| Chart | Key? | 說明 |
|-------|------|------|
| **`step2_anomaly_by_segment.png`** | ⭐ | 異常按 loc/system/threshold/timeline 分佈 |
| **`step2_anomaly_trend.png`** | ⭐ | 每日異常率趨勢 — 異常在增加嗎？ |
| `step2_system_anomaly.png` | | 異常類型 + timeline |
| `step2_device_anomaly_rate.png` | | per-device 異常率 top 20 |

---

## Step 3 — Bottleneck Breakdown

| Chart | Key? | 說明 |
|-------|------|------|
| **`step3_phase_breakdown.png`** | ⭐ | 各 file_count 組的 phase 佔比 — 瓶頸在哪？ |
| **`step3_tail_analysis.png`** | ⭐ | P95+ 慢訂單的特徵 — 為什麼慢？ |
| `step3_model_validation.png` | | phase model 驗證（R²） |
| `step3_duration_vs_filecount.png` | | duration vs file_count scatter |
| `step3_sla_compliance.png` | | SLA 達成率表 |
| `step3_sla_by_location.png` | | SLA violation by location |

---

## Step 4 — Slow Device

| Chart | Key? | 說明 |
|-------|------|------|
| **`step4_device_ranking.png`** | ⭐ | device 排名 — 哪些是慢機台？ |
| **`step4_device_utilization.png`** | ⭐ | 忙碌度 vs 效能 — 忙的時候會變慢嗎？ |
| `step4_facet_analysis.png` | | loc/system/model 切面分析 |
| `step4_slow_device_breakdown.png` | | 慢機台的 phase breakdown |

---

## Step 5 — Dashboard

| Chart | Key? | 說明 |
|-------|------|------|
| **`dashboard.png`** | ⭐ | 6-panel 綜合 dashboard — 簡報用 |

---

## Step 6 — Capacity Sizing

| Chart | Key? | 說明 |
|-------|------|------|
| **`step6_concurrency.png`** | ⭐ | 各場景的 concurrent orders — 資源規劃依據 |
| **`step6_hourly_capacity.png`** | ⭐ | 每小時 avg/peak/burst/buffer 對比 |
| `step6_current_capacity.png` | | loc × hour 的 avg/peak heatmap |
| `step6_burst_scenarios.png` | | burst 場景 stacked bar + multiplier |
