# ===== 共用參數 =====
# 所有 notebook 共用，改這裡一次生效。
# 每個 notebook 用 exec(open('../config/params.py').read()) 載入。

from pathlib import Path as _Path
REPORTS_DIR = _Path('../reports')
REPORTS_DIR.mkdir(exist_ok=True)

DATA_PATH = '../data/orders.csv'
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'   # order_created_at 的時間格式 (例: 2026-01-01 11:11:11.123456)
PARALLELISM = 4                            # 每筆 order 的並行 thread 數（問開發團隊確認）
FILE_COUNT_BINS = [0, 100, 1000, 2000, 100000]
FILE_COUNT_LABELS = ['<100', '100-1000', '1000-2000', '2000+']
GAP_MIN_RATIO = 2.0                        # 慢機台 gap detection 的最小比值

# Step 1 — Contention
CONTENTION_WINDOW_MINUTES = 30             # 同 device 多單的時間窗口（分鐘）
CONTENTION_MIN_ORDERS = 3                  # 窗口內最少幾單算 contention
TOP_N_MODELS = 15                          # Device model 圖表顯示前幾名
TREND_LAST_N_DAYS = 0                      # Duration trend 只顯示最近 N 天（0 = 全部）

# Step 6 — Capacity Sizing
BURST_MULTIPLIER = 10                      # 模擬某 loc_2 爆量到現在 peak 的幾倍
CAPACITY_BUFFER = 1.3                      # 安全餘量（1.3 = 多留 30% buffer）

# Step 2 — System Anomaly
DEVICE_IQR_MULTIPLIER = 4                  # device timeout: Q3 + N × IQR（越大越嚴格）
DB_IQR_MULTIPLIER = 4                      # db lock: Q3 + N × IQR（越大越嚴格）
QUEUE_IQR_MULTIPLIER = 4                   # queue stuck: Q3 + N × IQR（越大越嚴格）
MIN_ORDERS_PER_DEVICE = 20                 # device 訂單 ≥ 此值才用 per-device IQR
MIN_ORDERS_PER_MODEL = 30                  # model 訂單 ≥ 此值才用 per-model IQR（device 不夠時 fallback）
MIN_DEVICE_THRESHOLD = 20                  # device_duration 閾值下限（秒），IQR 太小時保底
MIN_DB_THRESHOLD = 5                       # db_duration 閾值下限（秒），IQR≈0 時保底
MIN_QUEUE_THRESHOLD = 30                   # queue_duration 閾值下限（秒），IQR≈1 時保底

# Step 4 — Usage Analysis
HIGH_USAGE_PERCENTILE = 75                 # device 訂單數 >= P_N 視為 high usage（top 25%）

# Step 3 — SLA Rules: (max_file_count, max_duration_seconds, label)
SLA_RULES = [
    (500, 1800, 'file<500 → 30min'),
    (2000, 3600, 'file<2000 → 60min'),
    (100000, 7200, 'all → 120min'),
]
