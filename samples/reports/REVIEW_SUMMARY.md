# Design & Code Review Summary

## 總體評估

### V2（修復後）

所有 critical issues 已修復。修復前後對比：

| Layer | Metric | Before | After |
|-------|--------|--------|-------|
| 1b User Burst | Precision | 3.6% | **88.0%** |
| 1b User Burst | Recall | 2.4% | **96.5%** |
| 1b User Burst | F1 | 1.9% | **92.0%** |
| 1a System Anomaly | Precision | 34.9% | **99.6%** |
| 1a System Anomaly | Recall | 100% | **100%** |
| 1a System Anomaly | F1 | 51.7% | **99.8%** |
| 3 Slow Devices | Accuracy | 8/10 (2 FP) | **8/8 PERFECT** |
| 2 Model | R² | (not validated) | **0.999** |

### 修復方法摘要

1. **Layer 1b**: 改用 queue_duration 區間偵測 (80-500s) 取代 temporal contention window
2. **Layer 1a**: 排除 user burst 後計算 per-device IQR×4 + queue stuck > 500s
3. **Layer 3**: Gap detection 取代 nlargest(10)
4. **Layer 2**: 新增 model validation (est_total vs actual scatter + R²)
5. **執行順序**: 1b → 1a → 2 → 3 → 0

---

## V1 Review（修復前，保留供參考）

分析框架（4 Layer）架構合理，但驗證結果顯示 **Layer 1b 幾乎無效、Layer 1a 精確率過低**，
直接影響 Layer 2/3 的排除邏輯。以下按嚴重程度排列。

---

## 🔴 Critical Issues

### C1. Layer 1b 的 contention 偵測幾乎完全失效

| Metric    | Value |
|-----------|-------|
| Precision | 3.6%  |
| Recall    | 2.4%  |
| TP        | 21    |
| FP        | 563   |
| FN        | 859   |

**Root cause**: 使用 ±30 分鐘 sliding window 計算同 device 並行訂單數 ≥3 的方式，
與實際 user_burst 行為模式不匹配（ground truth 共 880 筆 user_burst，只抓到 21 筆）。

**建議**:
- 重新定義 contention：改用同 device 連續訂單間隔 < N 分鐘（rolling gap），而非固定 window
- 或改用 device-level 的 daily order rate z-score
- 需參考 ground truth 的 user_burst 特徵重新設計偵測邏輯

### C2. Layer 1b 的 large file_count 標記有誤

flagged 900 筆中 **861 筆 (95.7%) 是 ground truth normal**。

| Label          | Count |
|----------------|-------|
| normal         | 861   |
| user_burst     | 24    |
| queue_stuck    | 5     |
| db_lock        | 5     |
| device_timeout | 5     |

**Root cause**: 高 file_count 是訂單本身的屬性，不代表 user 行為異常。
Global IQR threshold (>2727) 只是抓了 right-tail，不是 anomaly。

**建議**: 移除 is_large_filecount 作為 user anomaly 的判定條件，
或改為偵測 「同 user/device 短時間內提交超大量 file 的 pattern」。

### C3. Layer 1a 精確率偏低 (34.9%)

| Metric    | Value |
|-----------|-------|
| Precision | 34.9% |
| Recall    | 100%  |
| TP        | 550   |
| FP        | 1026  |
| FN        | 0     |

False Positive 分佈：
- 850 筆實際為 `user_burst` → 被系統異常偵測誤捕
- 176 筆實際為 `normal`

**Root cause**: queue/device/db 的 per-device IQR threshold 同時抓到了 user_burst 造成的
queue 延長。多條件 OR 合併進一步放大了 FP。

**影響**: Layer 2 排除了 2967 筆（實際異常只有 550 + 880 = 1430），多排除約 1537 筆正常/誤判訂單，
佔正常訂單 ~5.4%，對 Layer 2 結論影響中等。

---

## 🟡 Significant Issues

### S1. Layer 3 Top 10 排名包含非慢機台

Ground truth 顯示恰好 **8 台 slow device**（100% slow rate），但 nlargest(10) 補了 2 台
median=3.0s 的正常 device（DEV-0000, DEV-0001）。

```
真正慢機台 (median 12.5-14.0s): DEV-0062, 0006, 0028, 0035, 0057, 0163, 0189, 0070
誤入 Top10 (median 3.0s):       DEV-0000, DEV-0001
```

**Root cause**: 排名用 nlargest(10) 而非 gap detection，median 從 12.5 直接跳到 3.0 的明顯斷層被忽略。

**建議**: 改用 elbow/gap detection（如 median diff > threshold）識別自然分群邊界，
或至少在 top-N 選取後檢查是否存在值域斷層。

### S2. Phase model 在低 file_count 訂單嚴重低估

| file_count | actual mean | est_total mean | gap   |
|------------|-------------|----------------|-------|
| ≤ 20       | 99s         | 61s            | 38.4% |

2554 筆訂單的 est_total < 0.5× actual，全部集中在低 file_count。

**Root cause**: 模型假設 `total ≈ queue + (db+device+inner)*file_count/4`，
但未考慮固定開銷（connection setup、result aggregation、scheduling overhead）。
低 file_count 時固定開銷佔比高。

**建議**: 模型改為 `total ≈ queue + fixed_overhead + (db+device+inner)*file_count/parallelism`，
用迴歸估算 fixed_overhead，或對 file_count < 50 組別在 Layer 2 加註 model fit 較差的 caveat。

### S3. Layer 1b contention window 定義模糊

Code 用 `±30 分鐘`（實際 60 分鐘 window），但文檔和 CLAUDE.md 描述為「30 分鐘內」。
應明確定義為 forward-looking window（order_created_at ~ +30min）或 backward-looking。

---

## 🟢 Minor Issues

### M1. Code quality warnings
- **SettingWithCopyWarning** in `3_slow_device_drilldown.ipynb`: `top10_orders` 是 slice，
  應先 `.copy()` 再賦值新欄位。
- **FixedFormatter warning** in `1a_system_anomaly.ipynb`: 應用 `ax.set_xticks()` + `set_xticklabels()` 配對使用。
- `matplotlib.use('Agg')` + `plt.show()` 組合在 headless 環境會觸發 UserWarning，可移除 `plt.show()`。

### M2. Boxplot 選取邏輯不符分析目的
1a 的 boxplot 選取「order count 最多的 top 20 devices」，但分析目標是異常偵測，
應改為選取「有異常訂單的 devices」或「per_file_duration variance 最大的 devices」。

### M3. Dashboard 建議不是 data-driven
`0_summary_dashboard.ipynb` 的「建議行動方案」是靜態 markdown，
應根據實際分析數據動態生成（如：自動列出 top slow devices、dominant anomaly type 等）。

### M4. Location 切面分析無差異
Layer 3 的 loc_1 breakdown 顯示所有 FAB median 均為 3.0s，無顯著差異。
此圖表對決策無貢獻，應加上 Mann-Whitney U test 或至少標註「無顯著差異」。

---

## 各 Layer 結論可信度

| Layer | 結論 | 可信度 | 原因 |
|-------|------|--------|------|
| 1a    | 1576 筆系統異常 | ⚠️ 中 | Recall 100% 但 Precision 35%，FP 多為 user_burst |
| 1b    | 1459 筆 user 異常 | ❌ 低 | Contention P/R 均 <5%，large_filecount 96% 為正常訂單 |
| 2     | Device 佔 52% 為主要瓶頸 | ✅ 高 | 排除邏輯有偏但 Device 佔比穩定，結論不受影響 |
| 3     | 8 台慢機台 (median 12.5-14s) | ✅ 高 | 與 ground truth 完全吻合（移除誤入的 2 台後） |

---

## 建議修復優先順序

1. **重寫 Layer 1b** — contention 偵測邏輯、移除 large_filecount
2. **收緊 Layer 1a** — 減少 FP（考慮提高 IQR multiplier 或用 isolation forest）
3. **修正 Layer 3 Top-N** — 改用 gap detection
4. **Layer 2 加入 model validation** — 比較 est_total vs actual，低 file_count 組加 caveat
5. **修復 code warnings**
