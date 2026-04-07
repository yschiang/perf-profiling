# ===== 共用參數 =====
# 所有 notebook 共用，改這裡一次生效。
# 每個 notebook 用 exec(open('../config/params.py').read()) 載入。

DATA_PATH = '../data/orders.csv'
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'   # order_created_at 的時間格式 (例: 2026-01-01 11:11:11.123456)
PARALLELISM = 4                            # 每筆 order 的並行 thread 數（問開發團隊確認）
FILE_COUNT_BINS = [0, 50, 300, 1000, 2000, 5000]
FILE_COUNT_LABELS = ['<50', '50-300', '300-1000', '1000-2000', '2000+']
GAP_MIN_RATIO = 2.0                        # 慢機台 gap detection 的最小比值
