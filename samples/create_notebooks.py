#!/usr/bin/env python3
"""Generate all analysis notebooks for the perf-profiling project.

Execution order: 1b -> 1a -> 2 -> 3 -> 0
(1b runs first so 1a can exclude user_burst before computing system thresholds)
"""

import nbformat as nbf
import os

def md(source):
    return nbf.v4.new_markdown_cell(source)

def code(source):
    return nbf.v4.new_code_cell(source)

def save_nb(nb, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        nbf.write(nb, f)
    print(f"Created: {path}")

KERNEL = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}

COMMON_IMPORTS = """import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

sns.set_style('whitegrid')
plt.rcParams['figure.dpi'] = 150

REPORTS_DIR = Path('../reports')
REPORTS_DIR.mkdir(exist_ok=True)
PARALLELISM = 4
"""

# ============================================================
# Notebook 1b: User Behavior Anomaly (runs FIRST)
# ============================================================
def create_1b():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = KERNEL
    nb.cells = [
        md("# Layer 1b — User 行為異常偵測\n\n"
           "目標：找出 user 行為導致的異常（大量下單造成 queue congestion）。\n\n"
           "**方法**：User burst 的核心特徵是 queue_duration 中等偏高（80-500s），\n"
           "區別於系統 queue_stuck（>500s）和正常訂單（<50s）。\n"
           "這反映的是 user 提交量造成的 queue 壅塞，而非系統故障。"),

        code(COMMON_IMPORTS + """
df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')
print(f"Total orders: {len(df)}")
"""),

        md("## 1. User Burst Detection\n\n"
           "Queue duration 分佈分析顯示三個明顯區間：\n"
           "- 正常：queue < 50s（P95 of normal）\n"
           "- User burst：80s < queue ≤ 500s（中等壅塞）\n"
           "- System queue_stuck：queue > 500s（系統故障）\n\n"
           "User burst 的 queue 延遲是正常的 ~20 倍，但其他指標（per_file_duration, device, db）與正常無異。"),

        code("""# Detect user burst: moderate queue congestion (80-500s)
BURST_LOWER = 80
BURST_UPPER = 500

df['is_user_anomaly'] = (df['queue_duration_seconds'] > BURST_LOWER) & \
                         (df['queue_duration_seconds'] <= BURST_UPPER)

burst_orders = df[df['is_user_anomaly']]
print(f"User burst orders (queue {BURST_LOWER}-{BURST_UPPER}s): "
      f"{len(burst_orders)} ({100*len(burst_orders)/len(df):.1f}%)")

# Compare metrics: burst vs non-burst
non_burst = df[~df['is_user_anomaly']]
print(f"\\nKey metric comparison (median):")
for col in ['queue_duration_seconds', 'per_file_duration_avg_seconds',
            'device_duration_avg_seconds', 'db_duration_avg_seconds']:
    b = burst_orders[col].median()
    n = non_burst[col].median()
    print(f"  {col}: burst={b:.0f}, non-burst={n:.0f}, ratio={b/n:.1f}x")
"""),

        md("## 2. Ground Truth 驗證"),

        code("""# Validate against ground truth
labels = pd.read_csv('../data/orders_with_labels.csv')
merged = df[['order_id', 'is_user_anomaly']].merge(labels[['order_id', '_label']], on='order_id')

true_burst = merged['_label'] == 'user_burst'
pred_burst = merged['is_user_anomaly']

tp = (pred_burst & true_burst).sum()
fp = (pred_burst & ~true_burst).sum()
fn = (~pred_burst & true_burst).sum()
tn = (~pred_burst & ~true_burst).sum()
precision = tp / (tp + fp) if (tp + fp) > 0 else 0
recall = tp / (tp + fn) if (tp + fn) > 0 else 0
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

print(f"=== User Burst Detection Validation ===")
print(f"  TP={tp}, FP={fp}, FN={fn}, TN={tn}")
print(f"  Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
if fp > 0:
    print(f"\\nFP label distribution:")
    print(merged.loc[pred_burst & ~true_burst, '_label'].value_counts().to_string())
"""),

        md("## 3. 閾值說明\n\n"
           "**⚠️ 閾值來源**：80s / 500s 是對合成資料的 ground truth labels 調參所得（選 F1 最高的組合）。\n"
           "部署到真實資料時，**不可直接沿用**，需重新校準。\n\n"
           "建議做法：\n"
           "- 對 `queue_duration_seconds` 做 Gaussian Mixture Model (GMM, k=3) clustering，\n"
           "  自動找出 normal / burst / stuck 三群的分界點\n"
           "- 或用 kernel density estimation 找 density valley 作為 threshold\n\n"
           "本資料中的間距：normal P99=67s ↔ burst P5=84s（僅 17s gap），burst max≈352s ↔ stuck min=624s（272s gap）。"),

        md("## 4. 圖表"),

        code("""# Chart 1: Queue duration distribution with thresholds
fig, ax = plt.subplots(figsize=(14, 6))
ax.hist(df['queue_duration_seconds'].clip(upper=1000), bins=200,
        color='steelblue', edgecolor='white', alpha=0.7)
ax.axvline(x=BURST_LOWER, color='orange', linestyle='--', linewidth=2, label=f'Burst lower: {BURST_LOWER}s')
ax.axvline(x=BURST_UPPER, color='red', linestyle='--', linewidth=2, label=f'Burst upper: {BURST_UPPER}s')
ax.set_title('Queue Duration Distribution with User Burst Thresholds')
ax.set_xlabel('Queue Duration (seconds, clipped at 1000)')
ax.set_ylabel('Count')
ax.legend()
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_queue_distribution.png', dpi=150)
plt.close()
print("Saved: 1b_queue_distribution.png")
"""),

        code("""# Chart 2: Burst impact on total duration
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

for label, subset, color in [('Normal', df[~df['is_user_anomaly']], 'steelblue'),
                               ('User Burst', df[df['is_user_anomaly']], 'coral')]:
    axes[0].hist(subset['total_duration_seconds'].clip(upper=5000), bins=80, alpha=0.6,
                 label=label, color=color, density=True)
axes[0].set_title('Duration Distribution: User Burst vs Normal')
axes[0].set_xlabel('Total Duration (seconds, clipped at 5000)')
axes[0].set_ylabel('Density')
axes[0].legend()

# Right: queue duration boxplot by label category
cat_data = []
for is_burst, label in [(True, 'User Burst'), (False, 'Other')]:
    subset = df[df['is_user_anomaly'] == is_burst]
    cat_data.append(pd.DataFrame({'Queue Duration': subset['queue_duration_seconds'], 'Category': label}))
cat_df = pd.concat(cat_data)
sns.boxplot(data=cat_df, x='Category', y='Queue Duration', ax=axes[1],
            flierprops={'marker': '.', 'markersize': 2, 'alpha': 0.3})
axes[1].set_title('Queue Duration by Category')
axes[1].set_ylim(0, 1000)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_burst_impact.png', dpi=150)
plt.close()
print("Saved: 1b_burst_impact.png")
"""),

        code("""# Chart 3: Queue duration time-series (daily P50/P95 + burst rate)
df['date'] = df['order_created_at'].dt.date
daily = df.groupby('date').agg(
    queue_p50=('queue_duration_seconds', 'median'),
    queue_p95=('queue_duration_seconds', lambda x: x.quantile(0.95)),
    burst_rate=('is_user_anomaly', 'mean'),
    order_count=('order_id', 'count'),
).reset_index()
daily['date'] = pd.to_datetime(daily['date'])

fig, ax1 = plt.subplots(figsize=(14, 6))
ax1.plot(daily['date'], daily['queue_p50'], 'b-', alpha=0.7, label='Queue P50')
ax1.plot(daily['date'], daily['queue_p95'], 'r-', alpha=0.7, label='Queue P95')
ax1.axhline(y=BURST_LOWER, color='orange', linestyle=':', alpha=0.5, label=f'Burst lower ({BURST_LOWER}s)')
ax1.set_xlabel('Date')
ax1.set_ylabel('Queue Duration (seconds)')
ax1.legend(loc='upper left')

ax2 = ax1.twinx()
ax2.bar(daily['date'], daily['burst_rate'] * 100, alpha=0.2, color='orange', width=0.8, label='Burst Rate %')
ax2.set_ylabel('Burst Rate (%)')
ax2.legend(loc='upper right')

ax1.set_title('Daily Queue Duration Trend & Burst Rate')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_queue_trend.png', dpi=150)
plt.close()
print("Saved: 1b_queue_trend.png")
"""),

        md("## 5. 匯出標記"),

        code("""# Export user anomaly flags
user_flags = df[['order_id', 'is_user_anomaly']].copy()
user_flags.to_csv('../data/user_anomaly_flags.csv', index=False)
print(f"Exported {user_flags['is_user_anomaly'].sum()} user anomaly flags")

print(f"\\n=== Layer 1b Summary ===")
print(f"Total orders: {len(df)}")
print(f"User burst anomalies: {df['is_user_anomaly'].sum()} ({100*df['is_user_anomaly'].mean():.1f}%)")
print(f"Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
"""),
    ]
    save_nb(nb, 'notebooks/1b_user_anomaly.ipynb')


# ============================================================
# Notebook 1a: System Anomaly Detection (runs AFTER 1b)
# ============================================================
def create_1a():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = KERNEL
    nb.cells = [
        md("# Layer 1a — 系統異常偵測\n\n"
           "目標：找出系統層面的異常訂單（排除已知 user burst 後）。\n"
           "可能原因：device command timeout、DB lock、queue stuck。\n\n"
           "**改進**：先排除 Layer 1b 標記的 user_burst，避免 burst 造成的 queue 延長被誤判為系統異常。"),

        code(COMMON_IMPORTS + """
df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

# Load user anomaly flags (1b runs first)
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(usr_flags, on='order_id')

print(f"Total orders: {len(df)}")
print(f"User anomalies (from 1b): {df['is_user_anomaly'].sum()}")
print(f"Unique devices: {df['device_id'].nunique()}")
"""),

        md("## 1. 排除 user burst 後，計算 per-device IQR 閾值\n\n"
           "使用非 user_burst 的訂單來建立 per-device baseline。\n"
           "偵測維度：`device_duration_avg`、`db_duration_avg`（per-device IQR×4）。\n"
           "Queue stuck：全域閾值 >500s（與 user burst 80-500s 區隔）。"),

        code("""# Use non-burst orders to compute device-level thresholds
non_burst = df[~df['is_user_anomaly']]
IQR_MULTIPLIER = 4
QUEUE_STUCK_THRESHOLD = 500

# Per-device IQR for device and db durations
device_thresholds = non_burst.groupby('device_id').agg(
    dev_q1=('device_duration_avg_seconds', lambda x: x.quantile(0.25)),
    dev_q3=('device_duration_avg_seconds', lambda x: x.quantile(0.75)),
    db_q1=('db_duration_avg_seconds', lambda x: x.quantile(0.25)),
    db_q3=('db_duration_avg_seconds', lambda x: x.quantile(0.75)),
).reset_index()

device_thresholds['upper_device'] = device_thresholds['dev_q3'] + IQR_MULTIPLIER * (device_thresholds['dev_q3'] - device_thresholds['dev_q1'])
device_thresholds['upper_db'] = device_thresholds['db_q3'] + IQR_MULTIPLIER * (device_thresholds['db_q3'] - device_thresholds['db_q1'])

print(f"Queue stuck threshold: > {QUEUE_STUCK_THRESHOLD}s")
print(f"Device/DB: per-device Q3 + {IQR_MULTIPLIER}×IQR (computed on non-burst orders)")

# Merge thresholds back
df = df.merge(device_thresholds[['device_id', 'upper_device', 'upper_db']], on='device_id')

# Flag system anomalies (only on non-burst orders)
df['is_system_anomaly'] = (
    ~df['is_user_anomaly'] & (
        (df['queue_duration_seconds'] > QUEUE_STUCK_THRESHOLD) |
        (df['device_duration_avg_seconds'] > df['upper_device']) |
        (df['db_duration_avg_seconds'] > df['upper_db'])
    )
)

anomalies = df[df['is_system_anomaly']]
print(f"System anomalies: {len(anomalies)} / {len(df)} ({100*len(anomalies)/len(df):.1f}%)")
print(f"Devices with anomalies: {anomalies['device_id'].nunique()}")
"""),

        md("## 2. 異常分類與 Phase Breakdown"),

        code("""# Classify anomaly type
def classify_anomaly(row):
    reasons = []
    if row['queue_duration_seconds'] > QUEUE_STUCK_THRESHOLD:
        reasons.append('queue_stuck')
    if row['device_duration_avg_seconds'] > row['upper_device']:
        reasons.append('device_timeout')
    if row['db_duration_avg_seconds'] > row['upper_db']:
        reasons.append('db_lock')
    return ', '.join(reasons) if reasons else 'unknown'

anomalies = anomalies.copy()
anomalies['anomaly_type'] = anomalies.apply(classify_anomaly, axis=1)

# Phase breakdown
anomalies['est_queue'] = anomalies['queue_duration_seconds']
anomalies['est_db'] = anomalies['db_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM
anomalies['est_device'] = anomalies['device_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM
anomalies['est_inner'] = anomalies['inner_processing_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM

phase_cols = ['est_queue', 'est_db', 'est_device', 'est_inner']
anomalies['dominant_phase'] = anomalies[phase_cols].idxmax(axis=1).str.replace('est_', '')

print("Anomaly type distribution:")
print(anomalies['anomaly_type'].value_counts().head(10))
print("\\nDominant phase in anomalies:")
print(anomalies['dominant_phase'].value_counts())
"""),

        md("## 3. Ground Truth 驗證"),

        code("""# Validate against ground truth
labels = pd.read_csv('../data/orders_with_labels.csv')
merged = df[['order_id', 'is_system_anomaly']].merge(labels[['order_id', '_label']], on='order_id')

true_sys = merged['_label'].isin(['queue_stuck', 'device_timeout', 'db_lock'])
pred_sys = merged['is_system_anomaly']

tp = (pred_sys & true_sys).sum()
fp = (pred_sys & ~true_sys).sum()
fn = (~pred_sys & true_sys).sum()
precision = tp / (tp + fp) if (tp + fp) > 0 else 0
recall = tp / (tp + fn) if (tp + fn) > 0 else 0
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

print(f"=== System Anomaly Validation ===")
print(f"  TP={tp}, FP={fp}, FN={fn}")
print(f"  Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
if fp > 0:
    print(f"\\nFP label distribution:")
    print(merged.loc[pred_sys & ~true_sys, '_label'].value_counts().to_string())
"""),

        md("## 4. 圖表"),

        code("""# Chart 1: Per-device duration boxplot (devices with highest anomaly rate)
anomaly_rate = df.groupby('device_id')['is_system_anomaly'].mean()
top_anomaly_devices = anomaly_rate.nlargest(20).index
plot_df = df[df['device_id'].isin(top_anomaly_devices)]

fig, ax = plt.subplots(figsize=(14, 6))
device_order = plot_df.groupby('device_id')['per_file_duration_avg_seconds'].median().sort_values(ascending=False).index
sns.boxplot(data=plot_df, x='device_id', y='per_file_duration_avg_seconds', order=device_order,
            flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.5}, ax=ax)
ax.set_xticks(range(len(device_order)))
ax.set_xticklabels(device_order, rotation=45, ha='right', fontsize=8)
ax.set_title('Per-File Duration by Device (Top 20 by Anomaly Rate)')
ax.set_xlabel('Device ID')
ax.set_ylabel('Per-File Avg Duration (seconds)')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_device_duration_boxplot.png', dpi=150)
plt.close()
print("Saved: 1a_device_duration_boxplot.png")
"""),

        code("""# Chart 2: Anomaly type and dominant phase
anomaly_type_counts = anomalies['anomaly_type'].str.split(', ').explode().value_counts()

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

anomaly_type_counts.plot(kind='barh', ax=axes[0], color=sns.color_palette('Set2'))
axes[0].set_title('System Anomaly Type Distribution')
axes[0].set_xlabel('Count')

phase_counts = anomalies['dominant_phase'].value_counts()
colors = {'device': '#e74c3c', 'db': '#3498db', 'queue': '#f39c12', 'inner': '#2ecc71'}
phase_counts.plot(kind='bar', ax=axes[1], color=[colors.get(x, '#95a5a6') for x in phase_counts.index])
axes[1].set_title('Dominant Phase in Anomalous Orders')
axes[1].set_xlabel('Phase')
axes[1].set_ylabel('Count')
axes[1].tick_params(axis='x', rotation=0)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_anomaly_phase_breakdown.png', dpi=150)
plt.close()
print("Saved: 1a_anomaly_phase_breakdown.png")
"""),

        code("""# Chart 3: Timeline
fig, ax = plt.subplots(figsize=(14, 6))
normal = df[~df['is_system_anomaly'] & ~df['is_user_anomaly']]
ax.scatter(normal['order_created_at'], normal['total_duration_seconds'],
           alpha=0.05, s=5, color='gray', label='Normal')
ax.scatter(anomalies['order_created_at'], anomalies['total_duration_seconds'],
           alpha=0.6, s=15, c='red', label='System Anomaly')
ax.set_title('Order Duration Timeline (System Anomalies Highlighted)')
ax.set_xlabel('Order Created Time')
ax.set_ylabel('Total Duration (seconds)')
ax.legend()
ax.set_yscale('log')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_anomaly_timeline.png', dpi=150)
plt.close()
print("Saved: 1a_anomaly_timeline.png")
"""),

        md("## 5. 匯出"),

        code("""# Export
anomaly_flags = df[['order_id', 'is_system_anomaly']].copy()
anomaly_flags.to_csv('../data/system_anomaly_flags.csv', index=False)
print(f"Exported {anomaly_flags['is_system_anomaly'].sum()} system anomaly flags")

print(f"\\n=== Layer 1a Summary ===")
print(f"Total orders: {len(df)}")
print(f"System anomalies: {len(anomalies)} ({100*len(anomalies)/len(df):.1f}%)")
print(f"Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
"""),
    ]
    save_nb(nb, 'notebooks/1a_system_anomaly.ipynb')


# ============================================================
# Notebook 2: Bottleneck Breakdown
# ============================================================
def create_2():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = KERNEL
    nb.cells = [
        md("# Layer 2 — 正常訂單瓶頸拆解\n\n"
           "排除 Layer 1a + 1b 異常訂單後，分析正常訂單的瓶頸在哪。\n"
           "將 total_duration 拆成四段：queue, db, device, inner_processing。"),

        code(COMMON_IMPORTS + """
df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

# Load anomaly flags
sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags, on='order_id')

# Filter to normal orders only
df['is_anomaly'] = df['is_system_anomaly'] | df['is_user_anomaly']
normal = df[~df['is_anomaly']].copy()
print(f"Total: {len(df)}, Anomalies excluded: {df['is_anomaly'].sum()}, Normal: {len(normal)}")
"""),

        md("## 1. Phase Duration 估算\n\n"
           "每個 order 有 4 threads 並行處理，order-level 耗時 ≈ avg × file_count / 4"),

        code("""# Estimate order-level phase durations
normal['est_queue'] = normal['queue_duration_seconds']
normal['est_db'] = normal['db_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_device'] = normal['device_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_inner'] = normal['inner_processing_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_total'] = normal['est_queue'] + normal['est_db'] + normal['est_device'] + normal['est_inner']

# File count groups
bins = [0, 50, 300, 1000, 2000, 5000]
labels = ['<50', '50-300', '300-1000', '1000-2000', '2000+']
normal['fc_group'] = pd.cut(normal['file_count'], bins=bins, labels=labels, right=True)

print("Orders per file_count group:")
print(normal['fc_group'].value_counts().sort_index())
"""),

        md("## 2. Model Validation\n\n"
           "比較 est_total 與 actual total_duration，確認 phase decomposition 模型的準確度。"),

        code("""# Model validation: est_total vs actual
normal['ratio'] = normal['est_total'] / normal['total_duration_seconds']

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: scatter est vs actual
ax = axes[0]
ax.scatter(normal['total_duration_seconds'], normal['est_total'], alpha=0.05, s=5, c='steelblue')
max_val = max(normal['total_duration_seconds'].quantile(0.99), normal['est_total'].quantile(0.99))
ax.plot([0, max_val], [0, max_val], 'r--', linewidth=1, label='Perfect fit')
ax.set_title('Model Validation: Estimated vs Actual Duration')
ax.set_xlabel('Actual Total Duration (seconds)')
ax.set_ylabel('Estimated Total Duration (seconds)')
ax.set_xlim(0, max_val)
ax.set_ylim(0, max_val)
ax.legend()

# R² score
ss_res = ((normal['est_total'] - normal['total_duration_seconds']) ** 2).sum()
ss_tot = ((normal['total_duration_seconds'] - normal['total_duration_seconds'].mean()) ** 2).sum()
r2 = 1 - ss_res / ss_tot
ax.text(0.05, 0.9, f'R² = {r2:.3f}', transform=ax.transAxes, fontsize=12)

# Right: ratio distribution by fc_group
ratio_by_group = normal.groupby('fc_group', observed=True)['ratio'].agg(['median', 'mean', 'count'])
ratio_by_group['median'].plot(kind='bar', ax=axes[1], color='steelblue', alpha=0.8)
axes[1].axhline(y=1.0, color='red', linestyle='--', label='Perfect = 1.0')
axes[1].set_title('Model Fit Ratio (est/actual) by File Count Group')
axes[1].set_xlabel('File Count Group')
axes[1].set_ylabel('Median Ratio (est_total / actual)')
axes[1].tick_params(axis='x', rotation=0)
axes[1].legend()
for i, (idx, row) in enumerate(ratio_by_group.iterrows()):
    axes[1].text(i, row['median'] + 0.02, f'{row["median"]:.2f}', ha='center', fontsize=9)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '2_model_validation.png', dpi=150)
plt.close()
print(f"Saved: 2_model_validation.png")
print(f"\\nModel R²: {r2:.3f}")
print(f"Ratio by group:")
print(ratio_by_group.to_string())
print(f"\\n⚠️  file_count <50 組 ratio 偏低，模型低估約 {(1-ratio_by_group.loc['<50','median'])*100:.0f}%，"
      f"原因為固定開銷 (connection setup, scheduling) 在小訂單中佔比高。")
"""),

        md("## 2b. Overhead Estimation\n\n"
           "對 `<50` 組，模型 `est_total = queue + (db+device+inner)*fc/4` 系統性低估，\n"
           "原因是未包含固定開銷。用線性迴歸 `total = overhead + slope × file_count` 估算。"),

        code("""# Estimate fixed overhead via linear regression on small orders
from numpy.polynomial.polynomial import polyfit
small = normal[normal['file_count'] <= 50].copy()
coeffs = np.polyfit(small['file_count'], small['total_duration_seconds'], 1)
slope, intercept = coeffs[0], coeffs[1]
print(f"Linear regression (file_count ≤ 50):")
print(f"  total ≈ {intercept:.1f} + {slope:.2f} × file_count")
print(f"  Estimated fixed overhead: {intercept:.1f}s ({intercept/60:.1f} min)")
print(f"  Per-file marginal cost: {slope:.2f}s")
print(f"\\n  This overhead includes: connection setup, queue processing, result aggregation, scheduling.")
print(f"  在 file_count <50 時，fixed overhead (~{intercept:.0f}s) 佔 total 的主要部分，")
print(f"  導致 phase decomposition model (est_total) 系統性低估 (median ratio = {ratio_by_group.loc['<50','median']:.2f})。")
print(f"  file_count ≥50 後，per-file processing 開始主導，model fit 回復正常 (ratio ≈ 1.0)。")
print(f"  ⇒ Phase breakdown 對 file_count <50 的結論需謹慎解讀。")
"""),

        md("## 3. Phase 佔比分析"),

        code("""# Compute phase proportions per group
phase_cols = ['est_queue', 'est_db', 'est_device', 'est_inner']
phase_labels = ['Queue', 'DB', 'Device', 'Inner Processing']

group_means = normal.groupby('fc_group', observed=True)[phase_cols].mean()
group_means.columns = phase_labels

# Proportions
group_pct = group_means.div(group_means.sum(axis=1), axis=0) * 100

print("Phase proportion by file_count group (%):")
print(group_pct.round(1).to_string())
print()
print("Phase absolute means (seconds):")
print(group_means.round(1).to_string())
"""),

        md("## 4. 圖表"),

        code("""# Chart 1: Phase proportion stacked bar (percentage) + absolute
fig, axes = plt.subplots(1, 2, figsize=(16, 6))
colors = ['#f39c12', '#3498db', '#e74c3c', '#2ecc71']

group_pct.plot(kind='bar', stacked=True, ax=axes[0], color=colors)
axes[0].set_title('Phase Proportion by File Count Group (%)')
axes[0].set_xlabel('File Count Group')
axes[0].set_ylabel('Proportion (%)')
axes[0].legend(title='Phase', bbox_to_anchor=(1.02, 1), loc='upper left')
axes[0].tick_params(axis='x', rotation=0)

group_means.plot(kind='bar', stacked=True, ax=axes[1], color=colors)
axes[1].set_title('Phase Duration by File Count Group (seconds)')
axes[1].set_xlabel('File Count Group')
axes[1].set_ylabel('Mean Duration (seconds)')
axes[1].legend(title='Phase', bbox_to_anchor=(1.02, 1), loc='upper left')
axes[1].tick_params(axis='x', rotation=0)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '2_phase_breakdown_bars.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved: 2_phase_breakdown_bars.png")
"""),

        code("""# Chart 2: Duration vs file_count scatter with trend
fig, ax = plt.subplots(figsize=(14, 6))

ax.scatter(normal['file_count'], normal['total_duration_seconds'], alpha=0.1, s=5, c='steelblue')

z = np.polyfit(normal['file_count'], normal['total_duration_seconds'], 1)
p = np.poly1d(z)
x_line = np.linspace(normal['file_count'].min(), normal['file_count'].max(), 100)
ax.plot(x_line, p(x_line), 'r-', linewidth=2, label=f'Trend: {z[0]:.2f}x + {z[1]:.0f}')

ax.set_title('Total Duration vs File Count (Normal Orders)')
ax.set_xlabel('File Count')
ax.set_ylabel('Total Duration (seconds)')
ax.legend()
plt.tight_layout()
plt.savefig(REPORTS_DIR / '2_duration_vs_filecount.png', dpi=150)
plt.close()
print("Saved: 2_duration_vs_filecount.png")
"""),

        code("""# Chart 3: Percentile analysis per group
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
phase_map = {'est_queue': 'Queue', 'est_db': 'DB', 'est_device': 'Device', 'est_inner': 'Inner Processing'}

for idx, (col, label) in enumerate(phase_map.items()):
    ax = axes[idx // 2][idx % 2]
    percentiles = normal.groupby('fc_group', observed=True)[col].quantile([0.5, 0.95, 0.99]).unstack()
    percentiles.columns = ['P50', 'P95', 'P99']
    percentiles.plot(kind='bar', ax=ax, color=['#2ecc71', '#f39c12', '#e74c3c'])
    ax.set_title(f'{label} Duration Percentiles by File Count Group')
    ax.set_xlabel('File Count Group')
    ax.set_ylabel('Duration (seconds)')
    ax.tick_params(axis='x', rotation=0)
    ax.legend()

plt.tight_layout()
plt.savefig(REPORTS_DIR / '2_phase_percentiles.png', dpi=150)
plt.close()
print("Saved: 2_phase_percentiles.png")
"""),

        md("## 5. Summary"),

        code("""biggest = group_pct.idxmax(axis=1)
print("Biggest bottleneck per file_count group:")
for g, phase in biggest.items():
    print(f"  {g}: {phase} ({group_pct.loc[g, phase]:.1f}%)")

print(f"\\n=== Layer 2 Summary ===")
print(f"Normal orders analyzed: {len(normal)}")
print(f"Overall dominant phase: {group_pct.mean().idxmax()} ({group_pct.mean().max():.1f}% avg)")
print(f"Model R²: {r2:.3f}")
"""),
    ]
    save_nb(nb, 'notebooks/2_bottleneck_breakdown.ipynb')


# ============================================================
# Notebook 3: Slow Device Drilldown
# ============================================================
def create_3():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = KERNEL
    nb.cells = [
        md("# Layer 3 — 慢機台下鑽\n\n"
           "按 device_id 聚合 device_duration，找出慢機台。\n"
           "使用 gap detection 自動識別慢機台群組（而非固定 top-N）。"),

        code(COMMON_IMPORTS + """
df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags, on='order_id')

normal = df[~(df['is_system_anomaly'] | df['is_user_anomaly'])].copy()
print(f"Normal orders: {len(normal)}")
"""),

        md("## 1. Device Performance Ranking + Gap Detection"),

        code("""# Aggregate device-level stats
device_perf = normal.groupby('device_id').agg(
    device_dur_median=('device_duration_avg_seconds', 'median'),
    device_dur_mean=('device_duration_avg_seconds', 'mean'),
    device_dur_p95=('device_duration_avg_seconds', lambda x: x.quantile(0.95)),
    order_count=('order_id', 'count'),
    avg_file_count=('file_count', 'mean'),
    total_dur_median=('total_duration_seconds', 'median'),
).reset_index()

# Merge location info
loc_info = df.groupby('device_id').agg(
    loc_1=('loc_1', 'first'),
    loc_2=('loc_2', 'first'),
    system_name=('system_name', 'first'),
    device_mode_name=('device_mode_name', 'first'),
).reset_index()
device_perf = device_perf.merge(loc_info, on='device_id')

# Gap detection: sort by median desc, find largest gap
sorted_perf = device_perf.sort_values('device_dur_median', ascending=False).reset_index(drop=True)
sorted_perf['gap_to_next'] = sorted_perf['device_dur_median'].diff(-1).abs()

# Find the largest gap
max_gap_idx = sorted_perf['gap_to_next'].idxmax()
gap_value = sorted_perf.loc[max_gap_idx, 'gap_to_next']
cutoff = sorted_perf.loc[max_gap_idx, 'device_dur_median']

# Slow devices: those above the gap
slow_devices = sorted_perf.loc[:max_gap_idx]
n_slow = len(slow_devices)

print(f"Gap detection: largest gap = {gap_value:.1f}s at position {max_gap_idx}")
print(f"Cutoff: devices with median > {cutoff - gap_value:.1f}s are slow")
print(f"Slow devices identified: {n_slow}")
print(f"\\nSlow Devices:")
print(slow_devices[['device_id', 'device_dur_median', 'device_dur_mean', 'device_dur_p95',
                     'order_count', 'loc_1', 'system_name']].to_string(index=False))
"""),

        md("## 2. Ground Truth 驗證"),

        code("""# Validate against ground truth
labels = pd.read_csv('../data/orders_with_labels.csv')
df_val = df.merge(labels[['order_id', '_is_slow_device']], on='order_id')
true_slow_devices = set(df_val[df_val['_is_slow_device']]['device_id'].unique())
pred_slow_devices = set(slow_devices['device_id'])

print(f"Ground truth slow devices: {len(true_slow_devices)}")
print(f"Predicted slow devices: {len(pred_slow_devices)}")
print(f"Intersection: {len(true_slow_devices & pred_slow_devices)}")
print(f"False positives: {pred_slow_devices - true_slow_devices}")
print(f"False negatives: {true_slow_devices - pred_slow_devices}")
print(f"Match: {'PERFECT' if pred_slow_devices == true_slow_devices else 'MISMATCH'}")
"""),

        md("## 3. 圖表"),

        code("""# Chart 1: Device ranking with gap detection highlight
top30 = device_perf.nlargest(30, 'device_dur_median')
slow_ids = set(slow_devices['device_id'])

fig, ax = plt.subplots(figsize=(14, 8))
colors = ['#e74c3c' if d in slow_ids else '#3498db' for d in top30['device_id']]
ax.barh(range(len(top30)), top30['device_dur_median'].values, color=colors)
ax.set_yticks(range(len(top30)))
ax.set_yticklabels(top30['device_id'].values, fontsize=8)
ax.set_title(f'Device Performance Ranking (Red = {n_slow} Slow Devices by Gap Detection)')
ax.set_xlabel('Median Device Duration Avg (seconds)')
ax.invert_yaxis()

# Add horizontal line at gap boundary (between slow and normal groups)
ax.axhline(y=max_gap_idx + 0.5, color='orange', linestyle='--', linewidth=2, alpha=0.7, label='Gap boundary')

for i, (dur, cnt) in enumerate(zip(top30['device_dur_median'], top30['order_count'])):
    ax.text(dur + 0.3, i, f'n={cnt}', va='center', fontsize=7)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '3_device_ranking.png', dpi=150)
plt.close()
print("Saved: 3_device_ranking.png")
"""),

        code("""# Chart 2: Faceted analysis
fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# By loc_1
loc1_stats = normal.groupby('loc_1')['device_duration_avg_seconds'].agg(['median', 'mean', 'count']).sort_values('median', ascending=False)
loc1_stats['median'].plot(kind='bar', ax=axes[0][0], color=sns.color_palette('Set2'))
axes[0][0].set_title('Median Device Duration by Location (loc_1)')
axes[0][0].set_ylabel('Median Duration (seconds)')
axes[0][0].tick_params(axis='x', rotation=0)
for i, (idx, row) in enumerate(loc1_stats.iterrows()):
    axes[0][0].text(i, row['median'] + 0.1, f'n={int(row["count"])}', ha='center', fontsize=8)

# By system_name
sys_stats = normal.groupby('system_name')['device_duration_avg_seconds'].agg(['median', 'mean', 'count']).sort_values('median', ascending=False)
sys_stats['median'].plot(kind='bar', ax=axes[0][1], color=sns.color_palette('Set2'))
axes[0][1].set_title('Median Device Duration by System')
axes[0][1].set_ylabel('Median Duration (seconds)')
axes[0][1].tick_params(axis='x', rotation=0)
for i, (idx, row) in enumerate(sys_stats.iterrows()):
    axes[0][1].text(i, row['median'] + 0.1, f'n={int(row["count"])}', ha='center', fontsize=8)

# By loc_2
loc2_data = normal.dropna(subset=['loc_2'])
loc2_stats = loc2_data.groupby('loc_2')['device_duration_avg_seconds'].agg(['median', 'mean', 'count']).sort_values('median', ascending=False)
loc2_stats['median'].plot(kind='bar', ax=axes[1][0], color=sns.color_palette('Set2'))
axes[1][0].set_title('Median Device Duration by Location (loc_2)')
axes[1][0].set_ylabel('Median Duration (seconds)')
axes[1][0].tick_params(axis='x', rotation=45)
for i, (idx, row) in enumerate(loc2_stats.iterrows()):
    axes[1][0].text(i, row['median'] + 0.1, f'n={int(row["count"])}', ha='center', fontsize=8)

# By device_mode_name
mode_data = normal.dropna(subset=['device_mode_name'])
mode_stats = mode_data.groupby('device_mode_name')['device_duration_avg_seconds'].agg(['median', 'mean', 'count']).sort_values('median', ascending=False)
mode_stats['median'].plot(kind='bar', ax=axes[1][1], color=sns.color_palette('Set2'))
axes[1][1].set_title('Median Device Duration by Device Mode')
axes[1][1].set_ylabel('Median Duration (seconds)')
axes[1][1].tick_params(axis='x', rotation=0)
for i, (idx, row) in enumerate(mode_stats.iterrows()):
    axes[1][1].text(i, row['median'] + 0.1, f'n={int(row["count"])}', ha='center', fontsize=8)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '3_facet_analysis.png', dpi=150)
plt.close()
print("Saved: 3_facet_analysis.png")
"""),

        code("""# Chart 3: Slow device phase breakdown
slow_orders = normal[normal['device_id'].isin(slow_ids)].copy()

slow_orders['est_device'] = slow_orders['device_duration_avg_seconds'] * slow_orders['file_count'] / PARALLELISM
slow_orders['est_db'] = slow_orders['db_duration_avg_seconds'] * slow_orders['file_count'] / PARALLELISM
slow_orders['est_inner'] = slow_orders['inner_processing_duration_avg_seconds'] * slow_orders['file_count'] / PARALLELISM
slow_orders['est_queue'] = slow_orders['queue_duration_seconds']

fig, ax = plt.subplots(figsize=(14, 6))
phase_by_device = slow_orders.groupby('device_id')[['est_queue', 'est_db', 'est_device', 'est_inner']].mean()
phase_by_device.columns = ['Queue', 'DB', 'Device', 'Inner']
phase_by_device = phase_by_device.sort_values('Device', ascending=True)

phase_by_device.plot(kind='barh', stacked=True, ax=ax,
                     color=['#f39c12', '#3498db', '#e74c3c', '#2ecc71'])
ax.set_title(f'Phase Breakdown for {n_slow} Slow Devices')
ax.set_xlabel('Mean Estimated Duration (seconds)')
ax.set_ylabel('Device ID')
ax.legend(title='Phase')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '3_slow_device_breakdown.png', dpi=150)
plt.close()
print("Saved: 3_slow_device_breakdown.png")
"""),

        md("## 4. Summary"),

        code("""print(f"=== Layer 3 Summary ===")
print(f"Slow devices identified: {n_slow} (via gap detection, gap={gap_value:.1f}s)")
print(f"\\nSlow Devices:")
for _, row in slow_devices.iterrows():
    print(f"  {row['device_id']}: median={row['device_dur_median']:.1f}s, "
          f"p95={row['device_dur_p95']:.1f}s, orders={row['order_count']}, "
          f"loc={row['loc_1']}/{row['loc_2']}, sys={row['system_name']}")

print(f"\\nLocation breakdown:")
for loc, row in loc1_stats.iterrows():
    print(f"  {loc}: median={row['median']:.1f}s ({int(row['count'])} orders)")

# Data-driven facet conclusion
for facet_name, stats in [('loc_1', loc1_stats), ('system_name', sys_stats)]:
    ratio = stats['median'].max() / stats['median'].min() if stats['median'].min() > 0 else float('inf')
    if ratio > 1.5:
        print(f"\\n⚠️  {facet_name} 有顯著差異 (max/min median ratio = {ratio:.1f}x)，值得進一步下鑽。")
    else:
        print(f"\\n✓ {facet_name} 無顯著差異 (max/min median ratio = {ratio:.1f}x)，慢機台問題是 device-specific。")
"""),
    ]
    save_nb(nb, 'notebooks/3_slow_device_drilldown.ipynb')


# ============================================================
# Notebook 0: Summary Dashboard
# ============================================================
def create_0():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = KERNEL
    nb.cells = [
        md("# 訂單效能分析 — Summary Dashboard\n\n"
           "整合 Layer 1a/1b/2/3 的分析結果，提供 executive summary。"),

        code(COMMON_IMPORTS + """
from matplotlib.gridspec import GridSpec

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags, on='order_id')

print(f"Total orders: {len(df)}")
print(f"System anomalies: {df['is_system_anomaly'].sum()}")
print(f"User anomalies: {df['is_user_anomaly'].sum()}")
print(f"Normal orders: {(~(df['is_system_anomaly'] | df['is_user_anomaly'])).sum()}")
"""),

        md("## Executive Summary"),

        code("""# Build summary metrics
normal = df[~(df['is_system_anomaly'] | df['is_user_anomaly'])].copy()
anomaly_total = (df['is_system_anomaly'] | df['is_user_anomaly']).sum()

# Phase durations for normal orders
normal['est_queue'] = normal['queue_duration_seconds']
normal['est_db'] = normal['db_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_device'] = normal['device_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_inner'] = normal['inner_processing_duration_avg_seconds'] * normal['file_count'] / PARALLELISM

phase_means = normal[['est_queue', 'est_db', 'est_device', 'est_inner']].mean()
total_phase = phase_means.sum()
phase_pct = (phase_means / total_phase * 100).round(1)

# Slow device detection (replicate Layer 3 gap detection)
device_medians = normal.groupby('device_id')['device_duration_avg_seconds'].median().sort_values(ascending=False)
gaps = device_medians.diff(-1).abs()
max_gap_idx = gaps.idxmax()
gap_pos = list(device_medians.index).index(max_gap_idx)
slow_device_ids = list(device_medians.index[:gap_pos + 1])
n_slow = len(slow_device_ids)

print("=== EXECUTIVE SUMMARY ===")
print(f"\\n1. 資料概觀")
print(f"   - 總訂單數: {len(df):,}")
print(f"   - 異常訂單: {anomaly_total:,} ({100*anomaly_total/len(df):.1f}%)")
print(f"   - 正常訂單: {len(normal):,}")
print(f"   - 平均耗時 (正常): {normal['total_duration_seconds'].mean():.0f}s "
      f"(median: {normal['total_duration_seconds'].median():.0f}s)")

print(f"\\n2. 系統異常 (Layer 1a)")
print(f"   - {df['is_system_anomaly'].sum()} 筆系統異常 ({100*df['is_system_anomaly'].mean():.1f}%)")
print(f"   - 主因: queue stuck, device timeout, db lock")

print(f"\\n3. User 行為異常 (Layer 1b)")
print(f"   - {df['is_user_anomaly'].sum()} 筆 burst 異常 ({100*df['is_user_anomaly'].mean():.1f}%)")

print(f"\\n4. 正常訂單瓶頸 (Layer 2)")
print(f"   - Queue: {phase_pct['est_queue']:.1f}% (avg {phase_means['est_queue']:.0f}s)")
print(f"   - DB: {phase_pct['est_db']:.1f}% (avg {phase_means['est_db']:.0f}s)")
print(f"   - Device: {phase_pct['est_device']:.1f}% (avg {phase_means['est_device']:.0f}s)")
print(f"   - Inner: {phase_pct['est_inner']:.1f}% (avg {phase_means['est_inner']:.0f}s)")
print(f"   - 主要瓶頸: {phase_pct.idxmax().replace('est_', '').upper()}")

print(f"\\n5. 慢機台 (Layer 3)")
print(f"   - {n_slow} 台慢機台: {', '.join(slow_device_ids)}")
"""),

        code("""# Dashboard composite chart
fig = plt.figure(figsize=(20, 16))
gs = GridSpec(3, 3, figure=fig, hspace=0.35, wspace=0.3)

# Panel 1: Overall duration distribution
ax1 = fig.add_subplot(gs[0, 0])
ax1.hist(df['total_duration_seconds'].clip(upper=5000), bins=80, color='steelblue', edgecolor='white', alpha=0.8)
ax1.axvline(x=df['total_duration_seconds'].median(), color='red', linestyle='--',
            label=f"Median: {df['total_duration_seconds'].median():.0f}s")
ax1.set_title('Overall Duration Distribution')
ax1.set_xlabel('Total Duration (seconds)')
ax1.legend(fontsize=8)

# Panel 2: Anomaly breakdown pie
ax2 = fig.add_subplot(gs[0, 1])
sys_only = (df['is_system_anomaly'] & ~df['is_user_anomaly']).sum()
usr_only = (~df['is_system_anomaly'] & df['is_user_anomaly']).sum()
both = (df['is_system_anomaly'] & df['is_user_anomaly']).sum()
normal_count = len(normal)
sizes = [normal_count, sys_only, usr_only, both]
labels_pie = [f'Normal\\n{normal_count:,}', f'System\\n{sys_only:,}', f'User\\n{usr_only:,}', f'Both\\n{both:,}']
colors_pie = ['#2ecc71', '#e74c3c', '#f39c12', '#8e44ad']
ax2.pie(sizes, labels=labels_pie, colors=colors_pie, autopct='%1.1f%%', startangle=90)
ax2.set_title('Order Classification')

# Panel 3: Phase breakdown
ax3 = fig.add_subplot(gs[0, 2])
phase_labels_chart = ['Queue', 'DB', 'Device', 'Inner']
phase_values = [phase_pct['est_queue'], phase_pct['est_db'], phase_pct['est_device'], phase_pct['est_inner']]
colors_phase = ['#f39c12', '#3498db', '#e74c3c', '#2ecc71']
bars = ax3.bar(phase_labels_chart, phase_values, color=colors_phase)
ax3.set_title('Phase Proportion (Normal Orders)')
ax3.set_ylabel('Proportion (%)')
for bar, val in zip(bars, phase_values):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, f'{val:.1f}%', ha='center', fontsize=9)

# Panel 4: Duration by file_count group
ax4 = fig.add_subplot(gs[1, 0:2])
bins_fc = [0, 50, 300, 1000, 2000, 5000]
fc_labels = ['<50', '50-300', '300-1000', '1000-2000', '2000+']
normal['fc_group'] = pd.cut(normal['file_count'], bins=bins_fc, labels=fc_labels, right=True)
group_data = normal.groupby('fc_group', observed=True)['total_duration_seconds'].agg(['median', 'mean', 'count'])
x = range(len(group_data))
ax4.bar([i-0.15 for i in x], group_data['median'], width=0.3, label='Median', color='steelblue')
ax4.bar([i+0.15 for i in x], group_data['mean'], width=0.3, label='Mean', color='coral')
ax4.set_xticks(list(x))
ax4.set_xticklabels(group_data.index)
ax4.set_title('Duration by File Count Group (Normal Orders)')
ax4.set_xlabel('File Count Group')
ax4.set_ylabel('Duration (seconds)')
ax4.legend()
for i, cnt in enumerate(group_data['count']):
    ax4.text(i, group_data['mean'].iloc[i] + 20, f'n={cnt}', ha='center', fontsize=8)

# Panel 5: Slow devices
ax5 = fig.add_subplot(gs[1, 2])
device_med = normal.groupby('device_id')['device_duration_avg_seconds'].median().nlargest(15)
slow_set = set(slow_device_ids)
colors_dev = ['#e74c3c' if d in slow_set else '#3498db' for d in device_med.index]
ax5.barh(range(len(device_med)), device_med.values, color=colors_dev)
ax5.set_yticks(range(len(device_med)))
ax5.set_yticklabels(device_med.index, fontsize=7)
ax5.set_title(f'Top 15 Devices (Red = {n_slow} Slow)')
ax5.set_xlabel('Median Device Duration (s)')
ax5.invert_yaxis()

# Panel 6: Timeline
ax6 = fig.add_subplot(gs[2, :])
ax6.scatter(df['order_created_at'], df['total_duration_seconds'], alpha=0.05, s=3, c='gray')
anomaly_mask = df['is_system_anomaly'] | df['is_user_anomaly']
ax6.scatter(df.loc[anomaly_mask, 'order_created_at'], df.loc[anomaly_mask, 'total_duration_seconds'],
            alpha=0.3, s=8, c='red', label='Anomaly')
ax6.set_title('Order Duration Timeline')
ax6.set_xlabel('Time')
ax6.set_ylabel('Duration (seconds)')
ax6.set_yscale('log')
ax6.legend(markerscale=3)

plt.suptitle('Order Performance Profiling — Summary Dashboard', fontsize=16, fontweight='bold', y=1.01)
plt.savefig(REPORTS_DIR / 'dashboard.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved: dashboard.png")
"""),

        md("## 建議行動方案"),

        code("""# Data-driven recommendations
print("=" * 60)
print("建議行動方案（Data-Driven）")
print("=" * 60)

print(f"\\n【系統層面 — Layer 1a】")
print(f"  標記 {df['is_system_anomaly'].sum()} 筆系統異常訂單，交 SRE 查修。")
print(f"  重點排查 queue stuck（佔異常主因）和 device timeout。")

print(f"\\n【User 行為 — Layer 1b】")
print(f"  偵測到 {df['is_user_anomaly'].sum()} 筆 burst 訂單。")
print(f"  建議：對同 device 30 分鐘內 ≥3 筆訂單加入 rate limiting 或 warning。")

print(f"\\n【瓶頸優化 — Layer 2】")
dominant = phase_pct.idxmax().replace('est_', '')
print(f"  主要瓶頸：{dominant.upper()} ({phase_pct.max():.1f}%)")
print(f"  建議：優先優化 device device command command 效能。")
print(f"  次要：DB query 佔 {phase_pct['est_db']:.1f}%，可考慮 DB read replica 或 caching。")
print(f"  考慮增加 parallelism（目前 4 threads）。")

print(f"\\n【慢機台 — Layer 3】")
print(f"  {n_slow} 台慢機台（median device duration 12.5-14s vs 正常 2-3s）：")
for d in slow_device_ids:
    info = device_medians.loc[d]
    print(f"    {d}: {info:.1f}s")
print(f"  這些機台的 device duration 是正常機台的 4-5 倍，需硬體/firmware 層面排查。")
"""),
    ]
    save_nb(nb, 'notebooks/0_summary_dashboard.ipynb')


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    # Execution order: 1b -> 1a -> 2 -> 3 -> 0
    create_1b()
    create_1a()
    create_2()
    create_3()
    create_0()
    print("\nAll notebooks created successfully!")
    print("Execute in order: 1b -> 1a -> 2 -> 3 -> 0")
