#!/usr/bin/env python3
"""Generate all analysis notebooks for the perf-profiling project."""

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

# ============================================================
# Notebook 1a: System Anomaly Detection
# ============================================================
def create_1a():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    nb.cells = [
        md("# Layer 1a — 系統異常偵測\n\n"
           "目標：找出系統層面的異常訂單。同一 device 大部分訂單很快，但少數異常慢（排除 file_count 影響後）。\n"
           "可能原因：SECS timeout、DB lock、queue stuck。"),

        code("""import pandas as pd
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

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')
print(f"Total orders: {len(df)}")
print(f"Unique devices: {df['device_id'].nunique()}")
"""),

        md("## 1. 計算 per-file duration 的 device-level 統計，標記 outliers\n\n"
           "使用 `per_file_duration_avg_seconds` 做異常偵測（排除 file_count 影響）。\n"
           "Outlier 定義：超過該 device 的 Q3 + 3×IQR。"),

        code("""# Compute per-device stats on per_file_duration_avg_seconds
device_stats = df.groupby('device_id')['per_file_duration_avg_seconds'].agg(
    median='median', q1=lambda x: x.quantile(0.25), q3=lambda x: x.quantile(0.75), count='count'
).reset_index()
device_stats['iqr'] = device_stats['q3'] - device_stats['q1']
device_stats['upper_fence'] = device_stats['q3'] + 3 * device_stats['iqr']

# Also check queue and device/db durations for outliers
for col, label in [('queue_duration_seconds', 'queue'),
                   ('device_duration_avg_seconds', 'device'),
                   ('db_duration_avg_seconds', 'db')]:
    stats = df.groupby('device_id')[col].agg(
        q1=lambda x: x.quantile(0.25), q3=lambda x: x.quantile(0.75)
    ).reset_index()
    stats[f'iqr_{label}'] = stats['q3'] - stats['q1']
    stats[f'upper_{label}'] = stats['q3'] + 3 * stats[f'iqr_{label}']
    device_stats = device_stats.merge(stats[['device_id', f'upper_{label}']], on='device_id')

# Merge thresholds back and flag outliers
df = df.merge(device_stats[['device_id', 'upper_fence', 'upper_queue', 'upper_device', 'upper_db']], on='device_id')
df['is_system_anomaly'] = (
    (df['per_file_duration_avg_seconds'] > df['upper_fence']) |
    (df['queue_duration_seconds'] > df['upper_queue']) |
    (df['device_duration_avg_seconds'] > df['upper_device']) |
    (df['db_duration_avg_seconds'] > df['upper_db'])
)

anomalies = df[df['is_system_anomaly']]
print(f"System anomalies: {len(anomalies)} / {len(df)} ({100*len(anomalies)/len(df):.1f}%)")
print(f"Devices with anomalies: {anomalies['device_id'].nunique()}")
"""),

        md("## 2. 異常訂單的 Phase Breakdown 分析\n\n判斷異常主要是哪個階段造成的。"),

        code("""# Classify anomaly type
PARALLELISM = 4

def classify_anomaly(row):
    reasons = []
    if row['queue_duration_seconds'] > row['upper_queue']:
        reasons.append('queue_stuck')
    if row['device_duration_avg_seconds'] > row['upper_device']:
        reasons.append('device_timeout')
    if row['db_duration_avg_seconds'] > row['upper_db']:
        reasons.append('db_lock')
    if row['per_file_duration_avg_seconds'] > row['upper_fence']:
        reasons.append('slow_processing')
    return ', '.join(reasons) if reasons else 'unknown'

anomalies = anomalies.copy()
anomalies['anomaly_type'] = anomalies.apply(classify_anomaly, axis=1)

# Phase breakdown for anomalies
anomalies['est_queue'] = anomalies['queue_duration_seconds']
anomalies['est_db'] = anomalies['db_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM
anomalies['est_device'] = anomalies['device_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM
anomalies['est_inner'] = anomalies['inner_processing_duration_avg_seconds'] * anomalies['file_count'] / PARALLELISM

# Which phase dominates?
phase_cols = ['est_queue', 'est_db', 'est_device', 'est_inner']
anomalies['dominant_phase'] = anomalies[phase_cols].idxmax(axis=1).str.replace('est_', '')

print("Anomaly type distribution:")
print(anomalies['anomaly_type'].value_counts().head(10))
print("\\nDominant phase in anomalies:")
print(anomalies['dominant_phase'].value_counts())
"""),

        md("## 3. 圖表"),

        code("""# Chart 1: Per-device per_file_duration distribution (top 20 devices by order count)
top_devices = df.groupby('device_id').size().nlargest(20).index
plot_df = df[df['device_id'].isin(top_devices)]

fig, ax = plt.subplots(figsize=(14, 6))
device_order = plot_df.groupby('device_id')['per_file_duration_avg_seconds'].median().sort_values(ascending=False).index
sns.boxplot(data=plot_df, x='device_id', y='per_file_duration_avg_seconds', order=device_order,
            flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.5}, ax=ax)
ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)
ax.set_title('Per-File Duration Distribution by Device (Top 20 by Order Count)')
ax.set_xlabel('Device ID')
ax.set_ylabel('Per-File Avg Duration (seconds)')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_device_duration_boxplot.png', dpi=150)
plt.show()
print("Saved: 1a_device_duration_boxplot.png")
"""),

        code("""# Chart 2: Anomaly phase breakdown stacked bar
anomaly_type_counts = anomalies['anomaly_type'].str.split(', ').explode().value_counts()

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: anomaly type counts
anomaly_type_counts.plot(kind='barh', ax=axes[0], color=sns.color_palette('Set2'))
axes[0].set_title('System Anomaly Type Distribution')
axes[0].set_xlabel('Count')

# Right: dominant phase
phase_counts = anomalies['dominant_phase'].value_counts()
colors = {'device': '#e74c3c', 'db': '#3498db', 'queue': '#f39c12', 'inner': '#2ecc71'}
phase_counts.plot(kind='bar', ax=axes[1], color=[colors.get(x, '#95a5a6') for x in phase_counts.index])
axes[1].set_title('Dominant Phase in Anomalous Orders')
axes[1].set_xlabel('Phase')
axes[1].set_ylabel('Count')
axes[1].tick_params(axis='x', rotation=0)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_anomaly_phase_breakdown.png', dpi=150)
plt.show()
print("Saved: 1a_anomaly_phase_breakdown.png")
"""),

        code("""# Chart 3: Anomaly timeline scatter
fig, ax = plt.subplots(figsize=(14, 6))
normal = df[~df['is_system_anomaly']]
ax.scatter(normal['order_created_at'], normal['total_duration_seconds'],
           alpha=0.05, s=5, color='gray', label='Normal')
scatter = ax.scatter(anomalies['order_created_at'], anomalies['total_duration_seconds'],
                     alpha=0.6, s=15, c='red', label='System Anomaly')
ax.set_title('Order Duration Timeline (System Anomalies Highlighted)')
ax.set_xlabel('Order Created Time')
ax.set_ylabel('Total Duration (seconds)')
ax.legend()
ax.set_yscale('log')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1a_anomaly_timeline.png', dpi=150)
plt.show()
print("Saved: 1a_anomaly_timeline.png")
"""),

        md("## 4. 匯出異常標記供其他 notebook 使用"),

        code("""# Export anomaly flags
anomaly_flags = df[['order_id', 'is_system_anomaly']].copy()
anomaly_flags.to_csv('../data/system_anomaly_flags.csv', index=False)
print(f"Exported {anomaly_flags['is_system_anomaly'].sum()} system anomaly flags")

# Summary stats
print(f"\\n=== Layer 1a Summary ===")
print(f"Total orders: {len(df)}")
print(f"System anomalies: {len(anomalies)} ({100*len(anomalies)/len(df):.1f}%)")
print(f"Top anomaly types:")
for t, c in anomalies['anomaly_type'].value_counts().head(5).items():
    print(f"  {t}: {c}")
"""),
    ]
    save_nb(nb, 'notebooks/1a_system_anomaly.ipynb')


# ============================================================
# Notebook 1b: User Behavior Anomaly
# ============================================================
def create_1b():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    nb.cells = [
        md("# Layer 1b — User 行為異常偵測\n\n"
           "目標：找出 user 行為導致的異常。\n"
           "- 同一 device 短時間內多筆訂單（contention）\n"
           "- file 數量異常大的訂單"),

        code("""import pandas as pd
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

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')
print(f"Total orders: {len(df)}")
"""),

        md("## 1. Contention 偵測\n\n"
           "同一 device 在 30 分鐘內有多筆訂單，可能造成 resource contention。"),

        code("""# Sort by device and time, then detect contention windows
df = df.sort_values(['device_id', 'order_created_at'])

# For each order, count how many orders on same device within +/- 30 min
WINDOW_MINUTES = 30

def count_contention(group):
    times = group['order_created_at'].values
    counts = []
    for i, t in enumerate(times):
        window_start = t - np.timedelta64(WINDOW_MINUTES, 'm')
        window_end = t + np.timedelta64(WINDOW_MINUTES, 'm')
        count = ((times >= window_start) & (times <= window_end)).sum()
        counts.append(count)
    return pd.Series(counts, index=group.index)

df['contention_count'] = df.groupby('device_id', group_keys=False).apply(count_contention)

# Flag contention: 3+ orders on same device within window
df['is_contention'] = df['contention_count'] >= 3
contention_orders = df[df['is_contention']]
print(f"Contention orders (≥3 within {WINDOW_MINUTES}min window): {len(contention_orders)} ({100*len(contention_orders)/len(df):.1f}%)")
print(f"Devices with contention: {contention_orders['device_id'].nunique()}")
"""),

        md("## 2. 異常大 file_count 偵測"),

        code("""# Flag orders with abnormally large file_count (global Q3 + 3*IQR)
q1 = df['file_count'].quantile(0.25)
q3 = df['file_count'].quantile(0.75)
iqr = q3 - q1
upper = q3 + 3 * iqr
df['is_large_filecount'] = df['file_count'] > upper
large_fc = df[df['is_large_filecount']]
print(f"Large file_count threshold: > {upper:.0f}")
print(f"Large file_count orders: {len(large_fc)} ({100*len(large_fc)/len(df):.1f}%)")
"""),

        md("## 3. 綜合 User 行為異常標記"),

        code("""df['is_user_anomaly'] = df['is_contention'] | df['is_large_filecount']
user_anomalies = df[df['is_user_anomaly']]
print(f"Total user anomalies: {len(user_anomalies)} ({100*len(user_anomalies)/len(df):.1f}%)")
print(f"  - Contention only: {(df['is_contention'] & ~df['is_large_filecount']).sum()}")
print(f"  - Large file_count only: {(~df['is_contention'] & df['is_large_filecount']).sum()}")
print(f"  - Both: {(df['is_contention'] & df['is_large_filecount']).sum()}")
"""),

        md("## 4. 圖表"),

        code("""# Chart 1: Contention heatmap - orders per device per hour
contention_df = df[df['is_contention']].copy()
contention_df['hour'] = contention_df['order_created_at'].dt.hour
contention_df['date'] = contention_df['order_created_at'].dt.date

# Top 15 devices by contention count
top_contention_devices = contention_df['device_id'].value_counts().head(15).index
heat_data = contention_df[contention_df['device_id'].isin(top_contention_devices)]
heat_pivot = heat_data.groupby(['device_id', 'hour']).size().unstack(fill_value=0)

fig, ax = plt.subplots(figsize=(14, 6))
sns.heatmap(heat_pivot, cmap='YlOrRd', annot=True, fmt='d', ax=ax, linewidths=0.5)
ax.set_title('Order Contention Heatmap: Orders per Hour (Top 15 Contention Devices)')
ax.set_xlabel('Hour of Day')
ax.set_ylabel('Device ID')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_contention_heatmap.png', dpi=150)
plt.show()
print("Saved: 1b_contention_heatmap.png")
"""),

        code("""# Chart 2: File count distribution with anomaly threshold
fig, ax = plt.subplots(figsize=(12, 6))
ax.hist(df['file_count'], bins=100, color='steelblue', alpha=0.7, edgecolor='white')
ax.axvline(x=upper, color='red', linestyle='--', linewidth=2, label=f'Threshold: {upper:.0f}')
ax.set_title('File Count Distribution with Anomaly Threshold')
ax.set_xlabel('File Count')
ax.set_ylabel('Number of Orders')
ax.legend()
ax.set_xlim(0, df['file_count'].quantile(0.99) * 1.2)
plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_filecount_distribution.png', dpi=150)
plt.show()
print("Saved: 1b_filecount_distribution.png")
"""),

        code("""# Chart 3: Contention impact on duration
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: contention vs no contention duration
for label, subset, color in [('No Contention', df[~df['is_contention']], 'steelblue'),
                               ('Contention', df[df['is_contention']], 'coral')]:
    axes[0].hist(subset['total_duration_seconds'].clip(upper=5000), bins=80, alpha=0.6,
                 label=label, color=color, density=True)
axes[0].set_title('Duration Distribution: Contention vs Normal')
axes[0].set_xlabel('Total Duration (seconds, clipped at 5000)')
axes[0].set_ylabel('Density')
axes[0].legend()

# Right: scatter of contention_count vs duration
ax = axes[1]
scatter = ax.scatter(df['contention_count'], df['total_duration_seconds'],
                     alpha=0.1, s=5, c=df['file_count'], cmap='viridis')
ax.set_title('Contention Count vs Total Duration')
ax.set_xlabel('Concurrent Orders on Same Device')
ax.set_ylabel('Total Duration (seconds)')
ax.set_yscale('log')
plt.colorbar(scatter, ax=ax, label='File Count')

plt.tight_layout()
plt.savefig(REPORTS_DIR / '1b_contention_impact.png', dpi=150)
plt.show()
print("Saved: 1b_contention_impact.png")
"""),

        md("## 5. 匯出標記"),

        code("""# Export user anomaly flags
user_flags = df[['order_id', 'is_user_anomaly', 'is_contention', 'is_large_filecount']].copy()
user_flags.to_csv('../data/user_anomaly_flags.csv', index=False)
print(f"Exported {user_flags['is_user_anomaly'].sum()} user anomaly flags")

print(f"\\n=== Layer 1b Summary ===")
print(f"Total orders: {len(df)}")
print(f"User anomalies: {len(user_anomalies)} ({100*len(user_anomalies)/len(df):.1f}%)")
print(f"Contention events: {df['is_contention'].sum()}")
print(f"Large file_count: {df['is_large_filecount'].sum()}")
"""),
    ]
    save_nb(nb, 'notebooks/1b_user_anomaly.ipynb')


# ============================================================
# Notebook 2: Bottleneck Breakdown
# ============================================================
def create_2():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    nb.cells = [
        md("# Layer 2 — 正常訂單瓶頸拆解\n\n"
           "排除 Layer 1a + 1b 異常訂單後，分析正常訂單的瓶頸在哪。\n"
           "將 total_duration 拆成四段：queue, db, device, inner_processing。"),

        code("""import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

sns.set_style('whitegrid')
plt.rcParams['figure.dpi'] = 150

REPORTS_DIR = Path('../reports')
PARALLELISM = 4

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

# Load anomaly flags
sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')

df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags[['order_id', 'is_user_anomaly']], on='order_id')

# Filter to normal orders only
df['is_anomaly'] = df['is_system_anomaly'] | df['is_user_anomaly']
normal = df[~df['is_anomaly']].copy()
print(f"Total: {len(df)}, Anomalies excluded: {df['is_anomaly'].sum()}, Normal: {len(normal)}")
"""),

        md("## 1. Phase Duration 估算\n\n"
           "每個 order 有 4 threads 並行處理，所以 order-level 耗時 ≈ avg × file_count / 4"),

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

        md("## 2. Phase 佔比分析"),

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

        md("## 3. 圖表"),

        code("""# Chart 1: Phase proportion stacked bar (percentage)
fig, axes = plt.subplots(1, 2, figsize=(16, 6))
colors = ['#f39c12', '#3498db', '#e74c3c', '#2ecc71']

group_pct.plot(kind='bar', stacked=True, ax=axes[0], color=colors)
axes[0].set_title('Phase Proportion by File Count Group (%)')
axes[0].set_xlabel('File Count Group')
axes[0].set_ylabel('Proportion (%)')
axes[0].legend(title='Phase', bbox_to_anchor=(1.02, 1), loc='upper left')
axes[0].tick_params(axis='x', rotation=0)

# Chart 2: Phase absolute stacked bar
group_means.plot(kind='bar', stacked=True, ax=axes[1], color=colors)
axes[1].set_title('Phase Duration by File Count Group (seconds)')
axes[1].set_xlabel('File Count Group')
axes[1].set_ylabel('Mean Duration (seconds)')
axes[1].legend(title='Phase', bbox_to_anchor=(1.02, 1), loc='upper left')
axes[1].tick_params(axis='x', rotation=0)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '2_phase_breakdown_bars.png', dpi=150, bbox_inches='tight')
plt.show()
print("Saved: 2_phase_breakdown_bars.png")
"""),

        code("""# Chart 3: Duration vs file_count scatter with trend
fig, ax = plt.subplots(figsize=(14, 6))

scatter = ax.scatter(normal['file_count'], normal['total_duration_seconds'],
                     alpha=0.1, s=5, c='steelblue')

# Add trend line
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
plt.show()
print("Saved: 2_duration_vs_filecount.png")
"""),

        code("""# Chart 4: Percentile analysis per group
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
plt.show()
print("Saved: 2_phase_percentiles.png")
"""),

        md("## 4. Summary"),

        code("""# Identify the biggest bottleneck per group
biggest = group_pct.idxmax(axis=1)
print("Biggest bottleneck per file_count group:")
for g, phase in biggest.items():
    print(f"  {g}: {phase} ({group_pct.loc[g, phase]:.1f}%)")

print(f"\\n=== Layer 2 Summary ===")
print(f"Normal orders analyzed: {len(normal)}")
print(f"Overall dominant phase: {group_pct.mean().idxmax()} ({group_pct.mean().max():.1f}% avg)")
"""),
    ]
    save_nb(nb, 'notebooks/2_bottleneck_breakdown.ipynb')


# ============================================================
# Notebook 3: Slow Device Drilldown
# ============================================================
def create_3():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    nb.cells = [
        md("# Layer 3 — 慢機台下鑽\n\n"
           "如果 device side 是主要瓶頸，按 device_id 聚合，找出最慢的 devices。\n"
           "按 loc_1, loc_2, system_name, device_mode_name 做切面分析。"),

        code("""import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

sns.set_style('whitegrid')
plt.rcParams['figure.dpi'] = 150

REPORTS_DIR = Path('../reports')
PARALLELISM = 4

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

# Load and merge anomaly flags
sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags[['order_id', 'is_user_anomaly']], on='order_id')

normal = df[~(df['is_system_anomaly'] | df['is_user_anomaly'])].copy()
print(f"Normal orders: {len(normal)}")
"""),

        md("## 1. Device Performance Ranking"),

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

# Top 10 slowest devices
top10_slow = device_perf.nlargest(10, 'device_dur_median')
print("Top 10 Slowest Devices (by median device_duration_avg):")
print(top10_slow[['device_id', 'device_dur_median', 'device_dur_mean', 'device_dur_p95',
                   'order_count', 'loc_1', 'system_name']].to_string(index=False))
"""),

        md("## 2. 圖表"),

        code("""# Chart 1: Device performance ranking (top 30)
top30 = device_perf.nlargest(30, 'device_dur_median')

fig, ax = plt.subplots(figsize=(14, 8))
colors = ['#e74c3c' if d in top10_slow['device_id'].values else '#3498db' for d in top30['device_id']]
bars = ax.barh(range(len(top30)), top30['device_dur_median'].values, color=colors)
ax.set_yticks(range(len(top30)))
ax.set_yticklabels(top30['device_id'].values, fontsize=8)
ax.set_title('Device Performance Ranking - Top 30 Slowest (Red = Top 10)')
ax.set_xlabel('Median Device Duration Avg (seconds)')
ax.invert_yaxis()

# Add order count annotation
for i, (dur, cnt) in enumerate(zip(top30['device_dur_median'], top30['order_count'])):
    ax.text(dur + 0.5, i, f'n={cnt}', va='center', fontsize=7)

plt.tight_layout()
plt.savefig(REPORTS_DIR / '3_device_ranking.png', dpi=150)
plt.show()
print("Saved: 3_device_ranking.png")
"""),

        code("""# Chart 2: Faceted analysis by loc_1, system_name
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

# By loc_2 (exclude NaN)
loc2_data = normal.dropna(subset=['loc_2'])
loc2_stats = loc2_data.groupby('loc_2')['device_duration_avg_seconds'].agg(['median', 'mean', 'count']).sort_values('median', ascending=False)
loc2_stats['median'].plot(kind='bar', ax=axes[1][0], color=sns.color_palette('Set2'))
axes[1][0].set_title('Median Device Duration by Location (loc_2)')
axes[1][0].set_ylabel('Median Duration (seconds)')
axes[1][0].tick_params(axis='x', rotation=45)
for i, (idx, row) in enumerate(loc2_stats.iterrows()):
    axes[1][0].text(i, row['median'] + 0.1, f'n={int(row["count"])}', ha='center', fontsize=8)

# By device_mode_name (exclude NaN)
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
plt.show()
print("Saved: 3_facet_analysis.png")
"""),

        code("""# Chart 3: Top 10 slow devices - detailed breakdown
fig, ax = plt.subplots(figsize=(14, 6))
top10_orders = normal[normal['device_id'].isin(top10_slow['device_id'])]

# Phase breakdown for slow devices
top10_orders['est_device'] = top10_orders['device_duration_avg_seconds'] * top10_orders['file_count'] / PARALLELISM
top10_orders['est_db'] = top10_orders['db_duration_avg_seconds'] * top10_orders['file_count'] / PARALLELISM
top10_orders['est_inner'] = top10_orders['inner_processing_duration_avg_seconds'] * top10_orders['file_count'] / PARALLELISM
top10_orders['est_queue'] = top10_orders['queue_duration_seconds']

phase_by_device = top10_orders.groupby('device_id')[['est_queue', 'est_db', 'est_device', 'est_inner']].mean()
phase_by_device.columns = ['Queue', 'DB', 'Device', 'Inner']
phase_by_device = phase_by_device.sort_values('Device', ascending=True)

phase_by_device.plot(kind='barh', stacked=True, ax=ax,
                     color=['#f39c12', '#3498db', '#e74c3c', '#2ecc71'])
ax.set_title('Phase Breakdown for Top 10 Slowest Devices')
ax.set_xlabel('Mean Estimated Duration (seconds)')
ax.set_ylabel('Device ID')
ax.legend(title='Phase')
plt.tight_layout()
plt.savefig(REPORTS_DIR / '3_slow_device_breakdown.png', dpi=150)
plt.show()
print("Saved: 3_slow_device_breakdown.png")
"""),

        md("## 3. Summary"),

        code("""print("=== Layer 3 Summary ===")
print(f"\\nTop 10 Slowest Devices:")
for _, row in top10_slow.iterrows():
    print(f"  {row['device_id']}: median={row['device_dur_median']:.1f}s, "
          f"p95={row['device_dur_p95']:.1f}s, orders={row['order_count']}, "
          f"loc={row['loc_1']}/{row['loc_2']}, sys={row['system_name']}")

print(f"\\nLocation breakdown:")
for loc, row in loc1_stats.iterrows():
    print(f"  {loc}: median={row['median']:.1f}s ({int(row['count'])} orders)")
"""),
    ]
    save_nb(nb, 'notebooks/3_slow_device_drilldown.ipynb')


# ============================================================
# Notebook 0: Summary Dashboard
# ============================================================
def create_0():
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    nb.cells = [
        md("# 訂單效能分析 — Summary Dashboard\n\n"
           "整合 Layer 1a/1b/2/3 的分析結果，提供 executive summary。"),

        code("""import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from matplotlib.gridspec import GridSpec
import matplotlib.image as mpimg

sns.set_style('whitegrid')
plt.rcParams['figure.dpi'] = 150

REPORTS_DIR = Path('../reports')
PARALLELISM = 4

df = pd.read_csv('../data/orders.csv')
df['order_created_at'] = pd.to_datetime(df['order_created_at'], format='%Y/%m/%d %I:%M:%S %p')

sys_flags = pd.read_csv('../data/system_anomaly_flags.csv')
usr_flags = pd.read_csv('../data/user_anomaly_flags.csv')
df = df.merge(sys_flags, on='order_id')
df = df.merge(usr_flags[['order_id', 'is_user_anomaly']], on='order_id')

print(f"Total orders: {len(df)}")
print(f"System anomalies: {df['is_system_anomaly'].sum()}")
print(f"User anomalies: {df['is_user_anomaly'].sum()}")
print(f"Normal orders: {(~(df['is_system_anomaly'] | df['is_user_anomaly'])).sum()}")
"""),

        md("## Executive Summary\n\n"
           "本分析對 30,000 筆半導體製造訂單進行四層效能剖析。"),

        code("""# Build summary metrics
normal = df[~(df['is_system_anomaly'] | df['is_user_anomaly'])].copy()
anomaly_total = df['is_system_anomaly'].sum() + df['is_user_anomaly'].sum() - (df['is_system_anomaly'] & df['is_user_anomaly']).sum()

# Phase durations for normal orders
normal['est_queue'] = normal['queue_duration_seconds']
normal['est_db'] = normal['db_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_device'] = normal['device_duration_avg_seconds'] * normal['file_count'] / PARALLELISM
normal['est_inner'] = normal['inner_processing_duration_avg_seconds'] * normal['file_count'] / PARALLELISM

phase_means = normal[['est_queue', 'est_db', 'est_device', 'est_inner']].mean()
total_phase = phase_means.sum()
phase_pct = (phase_means / total_phase * 100).round(1)

print("=== EXECUTIVE SUMMARY ===")
print(f"\\n1. 資料概觀")
print(f"   - 總訂單數: {len(df):,}")
print(f"   - 異常訂單: {anomaly_total:,} ({100*anomaly_total/len(df):.1f}%)")
print(f"   - 正常訂單: {len(normal):,}")
print(f"   - 平均耗時 (正常): {normal['total_duration_seconds'].mean():.0f}s (median: {normal['total_duration_seconds'].median():.0f}s)")

print(f"\\n2. 系統異常 (Layer 1a)")
print(f"   - {df['is_system_anomaly'].sum()} 筆系統異常 ({100*df['is_system_anomaly'].mean():.1f}%)")

print(f"\\n3. User 行為異常 (Layer 1b)")
print(f"   - {df['is_user_anomaly'].sum()} 筆行為異常 ({100*df['is_user_anomaly'].mean():.1f}%)")

print(f"\\n4. 正常訂單瓶頸 (Layer 2)")
print(f"   - Queue: {phase_pct['est_queue']:.1f}% (avg {phase_means['est_queue']:.0f}s)")
print(f"   - DB: {phase_pct['est_db']:.1f}% (avg {phase_means['est_db']:.0f}s)")
print(f"   - Device: {phase_pct['est_device']:.1f}% (avg {phase_means['est_device']:.0f}s)")
print(f"   - Inner: {phase_pct['est_inner']:.1f}% (avg {phase_means['est_inner']:.0f}s)")
print(f"   - 主要瓶頸: {phase_pct.idxmax().replace('est_', '').upper()}")
"""),

        code("""# Dashboard composite chart
fig = plt.figure(figsize=(20, 16))
gs = GridSpec(3, 3, figure=fig, hspace=0.35, wspace=0.3)

# Panel 1: Overall duration distribution
ax1 = fig.add_subplot(gs[0, 0])
ax1.hist(df['total_duration_seconds'].clip(upper=5000), bins=80, color='steelblue', edgecolor='white', alpha=0.8)
ax1.axvline(x=df['total_duration_seconds'].median(), color='red', linestyle='--', label=f"Median: {df['total_duration_seconds'].median():.0f}s")
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

# Panel 3: Phase breakdown overall
ax3 = fig.add_subplot(gs[0, 2])
phase_labels = ['Queue', 'DB', 'Device', 'Inner']
phase_values = [phase_pct['est_queue'], phase_pct['est_db'], phase_pct['est_device'], phase_pct['est_inner']]
colors_phase = ['#f39c12', '#3498db', '#e74c3c', '#2ecc71']
bars = ax3.bar(phase_labels, phase_values, color=colors_phase)
ax3.set_title('Phase Proportion (Normal Orders)')
ax3.set_ylabel('Proportion (%)')
for bar, val in zip(bars, phase_values):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, f'{val:.1f}%', ha='center', fontsize=9)

# Panel 4: Duration by file_count group
ax4 = fig.add_subplot(gs[1, 0:2])
bins = [0, 50, 300, 1000, 2000, 5000]
fc_labels = ['<50', '50-300', '300-1000', '1000-2000', '2000+']
normal['fc_group'] = pd.cut(normal['file_count'], bins=bins, labels=fc_labels, right=True)
group_data = normal.groupby('fc_group', observed=True)['total_duration_seconds'].agg(['median', 'mean', 'count'])
x = range(len(group_data))
ax4.bar([i-0.15 for i in x], group_data['median'], width=0.3, label='Median', color='steelblue')
ax4.bar([i+0.15 for i in x], group_data['mean'], width=0.3, label='Mean', color='coral')
ax4.set_xticks(x)
ax4.set_xticklabels(group_data.index)
ax4.set_title('Duration by File Count Group (Normal Orders)')
ax4.set_xlabel('File Count Group')
ax4.set_ylabel('Duration (seconds)')
ax4.legend()
for i, cnt in enumerate(group_data['count']):
    ax4.text(i, group_data['mean'].iloc[i] + 20, f'n={cnt}', ha='center', fontsize=8)

# Panel 5: Top 10 slow devices
ax5 = fig.add_subplot(gs[1, 2])
device_perf = normal.groupby('device_id')['device_duration_avg_seconds'].median().nlargest(10)
ax5.barh(range(len(device_perf)), device_perf.values, color='#e74c3c')
ax5.set_yticks(range(len(device_perf)))
ax5.set_yticklabels(device_perf.index, fontsize=7)
ax5.set_title('Top 10 Slowest Devices')
ax5.set_xlabel('Median Device Duration (s)')
ax5.invert_yaxis()

# Panel 6: Duration timeline
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
plt.show()
print("Saved: dashboard.png")
"""),

        md("## 建議行動方案\n\n"
           "### 系統層面 (Layer 1a)\n"
           "- 將標記的系統異常訂單交 SRE 團隊查修\n"
           "- 重點排查 device timeout 和 DB lock 問題\n"
           "- 建立自動告警機制\n\n"
           "### User 行為 (Layer 1b)\n"
           "- 對 contention 頻繁的 device 設置下單頻率限制\n"
           "- 對大 file_count 訂單設置 warning 或需 approval\n\n"
           "### 瓶頸優化 (Layer 2)\n"
           "- 根據各 file_count 組別的主要瓶頸制定優化策略\n"
           "- 考慮增加 parallelism (目前 4 threads)\n\n"
           "### 慢機台 (Layer 3)\n"
           "- 優先處理 Top 10 慢機台\n"
           "- 按 location/system 分組排查共因"),
    ]
    save_nb(nb, 'notebooks/0_summary_dashboard.ipynb')


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    create_1a()
    create_1b()
    create_2()
    create_3()
    create_0()
    print("\nAll notebooks created successfully!")
