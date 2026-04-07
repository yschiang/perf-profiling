"""
Synthetic data generator for order performance profiling.
Target distributions (from real data observation):
  total_duration: P50=60, P75=200, P95=1000, P99=3000, max=100000
  file_count:     P50=100, P75=300, P95=1000, P99=2000, max=60000
  queue_duration:  P50=0, P75=1, P95=3, P99=8, max=60
  db_duration:     P50=0, P75=0.1, P95=0.2, P99=0.8, max=1200
  device_duration: P50=2, P75=4, P95=9, P99=15, max=500
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

np.random.seed(42)
random.seed(42)

NUM_ORDERS = 30000
NUM_DEVICES = 2000
NUM_SLOW_DEVICES = 40
SYSTEM_ANOMALY_RATE = 0.02
USER_BURST_RATE = 0.03
PARALLELISM = 4

# --- Dimensions ---
LOCATIONS_1 = ["FAB-A", "FAB-B", "FAB-C"]
LOCATIONS_2 = ["AREA-1", "AREA-2", "AREA-3", None]
SYSTEM_NAMES = ["SYS-ALPHA", "SYS-BETA", "SYS-GAMMA"]
_MODEL_PREFIXES = ["MDL", "EQP", "TYP", "SER"]
_MODEL_SUFFIXES = [f"{i:03d}" for i in range(1, 51)]
DEVICE_MODES = [f"{p}-{s}" for p, s in zip(
    np.random.choice(_MODEL_PREFIXES, 50), _MODEL_SUFFIXES
)] + [None] * 10

device_ids = [f"DEV-{i:04d}" for i in range(NUM_DEVICES)]
slow_device_ids = set(random.sample(device_ids, NUM_SLOW_DEVICES))

device_attrs = {}
for did in device_ids:
    device_attrs[did] = {
        "device_mode_name": random.choice(DEVICE_MODES),
        "loc_1": random.choice(LOCATIONS_1),
        "loc_2": random.choice(LOCATIONS_2),
        "system_name": random.choice(SYSTEM_NAMES),
    }


def gen_timestamp(base, idx):
    offset = timedelta(
        days=random.uniform(0, 30),
        hours=random.gauss(10, 4),
        minutes=random.uniform(0, 60),
        seconds=random.uniform(0, 60),
    )
    return base + offset


def gen_file_count():
    """P50=100, P75=300, P95=1000, P99=2000, max=60000"""
    v = np.random.lognormal(mean=np.log(100), sigma=1.4)
    return max(1, min(60000, int(v)))


def gen_queue():
    """P50=0, P75=1, P95=3, P99=8, max=60"""
    r = random.random()
    if r < 0.52:
        return 0.0
    elif r < 0.78:
        return round(random.uniform(0, 2), 1)
    elif r < 0.96:
        return round(random.uniform(1, 5), 1)
    elif r < 0.995:
        return round(random.uniform(5, 15), 1)
    else:
        return round(random.uniform(15, 60), 1)


def gen_device_duration(is_slow):
    """Normal: P50=2, P75=4, P95=9, P99=15, max=500
       Slow device: ~3-5x higher"""
    if is_slow:
        base = np.random.lognormal(mean=np.log(8), sigma=0.7)
    else:
        base = np.random.lognormal(mean=np.log(2), sigma=0.85)
    return round(max(0.1, min(500, base)), 2)


def gen_db_duration():
    """P50=0, P75=0.1, P95=0.2, P99=0.8, max=1200 (max from anomaly)"""
    r = random.random()
    if r < 0.55:
        return 0.0
    elif r < 0.80:
        return round(random.uniform(0, 0.15), 2)
    elif r < 0.96:
        return round(random.uniform(0.1, 0.3), 2)
    elif r < 0.995:
        return round(random.uniform(0.3, 2.0), 2)
    else:
        return round(random.uniform(2, 10), 2)


def gen_inner_duration():
    """Small: P50=0.5, P75=1, P95=2, P99=3"""
    v = np.random.lognormal(mean=np.log(0.5), sigma=0.7)
    return round(max(0, min(10, v)), 2)


def gen_normal_order(file_count, is_slow):
    queue = gen_queue()
    device_avg = gen_device_duration(is_slow)
    db_avg = gen_db_duration()
    inner_avg = gen_inner_duration()

    per_file_avg = device_avg + db_avg + inner_avg

    # Max and P95 are higher than avg (tail of per-file distribution)
    device_max = round(device_avg * random.uniform(2, 8), 2)
    device_p95 = round(device_avg * random.uniform(1.5, 4), 2)
    db_max = round(max(db_avg * random.uniform(2, 10), db_avg + 0.5), 2)
    db_p95 = round(max(db_avg * random.uniform(1.5, 5), db_avg + 0.1), 2)
    inner_max = round(inner_avg * random.uniform(2, 6), 2)
    inner_p95 = round(inner_avg * random.uniform(1.5, 3), 2)
    per_file_max = round(device_max + db_max + inner_max, 2)
    per_file_p95 = round(device_p95 + db_p95 + inner_p95, 2)

    # Total file duration (minutes)
    total_file_seconds = (file_count * per_file_avg) / PARALLELISM
    total_file_minutes = max(0, round(total_file_seconds / 60, 1))

    # Total duration = queue + file processing + small overhead
    overhead = random.uniform(2, 15)  # connection setup etc
    total_seconds = round(queue + total_file_seconds + overhead, 1)

    return {
        "queue_duration_seconds": queue,
        "per_file_duration_avg_seconds": round(per_file_avg, 2),
        "per_file_duration_max_seconds": per_file_max,
        "per_file_duration_p95_seconds": per_file_p95,
        "device_duration_avg_seconds": device_avg,
        "device_duration_max_seconds": device_max,
        "device_duration_p95_seconds": device_p95,
        "db_duration_avg_seconds": db_avg,
        "db_duration_max_seconds": db_max,
        "db_duration_p95_seconds": db_p95,
        "inner_processing_duration_avg_seconds": inner_avg,
        "inner_processing_duration_max_seconds": inner_max,
        "inner_processing_duration_p95_seconds": inner_p95,
        "total_file_duration_minutes": total_file_minutes,
        "total_duration_seconds": total_seconds,
    }


def inject_system_anomaly(durations):
    anomaly_type = random.choice(["device_timeout", "db_lock", "queue_stuck"])
    if anomaly_type == "device_timeout":
        spike = random.uniform(100, 500)
        durations["device_duration_avg_seconds"] += round(spike, 2)
        durations["device_duration_max_seconds"] += round(spike * 2, 2)
        durations["total_duration_seconds"] += round(spike * durations.get("_file_count", 100) / PARALLELISM, 1)
    elif anomaly_type == "db_lock":
        spike = random.uniform(50, 1200)
        durations["db_duration_avg_seconds"] += round(spike, 2)
        durations["db_duration_max_seconds"] += round(spike * 2, 2)
        durations["total_duration_seconds"] += round(spike * durations.get("_file_count", 100) / PARALLELISM, 1)
    elif anomaly_type == "queue_stuck":
        spike = random.uniform(20, 60)
        durations["queue_duration_seconds"] += round(spike, 1)
        durations["total_duration_seconds"] += round(spike, 1)
    durations["_anomaly_type"] = anomaly_type
    return durations


def inject_user_burst(durations):
    durations["device_duration_avg_seconds"] = round(durations["device_duration_avg_seconds"] * random.uniform(1.5, 3), 2)
    durations["total_duration_seconds"] = round(durations["total_duration_seconds"] * random.uniform(1.3, 2), 1)
    durations["_anomaly_type"] = "user_burst"
    return durations


# --- Generate ---
base_time = datetime(2026, 3, 1)
records = []

for i in range(NUM_ORDERS):
    did = random.choice(device_ids)
    attrs = device_attrs[did]
    file_count = gen_file_count()
    is_slow = did in slow_device_ids

    durations = gen_normal_order(file_count, is_slow)
    durations["_anomaly_type"] = "normal"
    durations["_file_count"] = file_count

    r = random.random()
    if r < SYSTEM_ANOMALY_RATE:
        durations = inject_system_anomaly(durations)
    elif r < SYSTEM_ANOMALY_RATE + USER_BURST_RATE:
        durations = inject_user_burst(durations)

    anomaly_type = durations.pop("_anomaly_type")
    durations.pop("_file_count", None)

    record = {
        "device_id": did,
        "device_mode_name": attrs["device_mode_name"],
        "order_created_at": gen_timestamp(base_time, i).strftime("%Y-%m-%d %H:%M:%S.%f"),
        "order_id": f"ORD-{i:06d}",
        "file_count": file_count,
        "loc_1": attrs["loc_1"],
        "loc_2": attrs["loc_2"],
        "system_name": attrs["system_name"],
        **durations,
        "_label": anomaly_type,
        "_is_slow_device": is_slow,
    }
    records.append(record)

df = pd.DataFrame(records)
df.to_csv("data/orders_with_labels.csv", index=False)
real_cols = [c for c in df.columns if not c.startswith("_")]
df[real_cols].to_csv("data/orders.csv", index=False)

# --- Verify ---
print(f"Generated {len(df)} orders, {df['device_id'].nunique()} devices")
print(f"\nLabel distribution:")
print(df["_label"].value_counts().to_string())

print(f"\n{'Metric':<35} {'P50':>8} {'P75':>8} {'P95':>8} {'P99':>8} {'Max':>10}")
print("-" * 75)
for col, target in [
    ('total_duration_seconds',    'P50=60, P75=200, P95=1000, P99=3000, max=100000'),
    ('file_count',                'P50=100, P75=300, P95=1000, P99=2000, max=60000'),
    ('queue_duration_seconds',    'P50=0, P75=1, P95=3, P99=8, max=60'),
    ('db_duration_avg_seconds',   'P50=0, P75=0.1, P95=0.2, P99=0.8, max=1200'),
    ('device_duration_avg_seconds','P50=2, P75=4, P95=9, P99=15, max=500'),
]:
    pcts = df[col].quantile([0.5, 0.75, 0.95, 0.99])
    print(f"{col:<35} {pcts[0.5]:>8.1f} {pcts[0.75]:>8.1f} {pcts[0.95]:>8.1f} {pcts[0.99]:>8.1f} {df[col].max():>10.1f}")

print(f"\nTarget:")
print(f"{'total_duration_seconds':<35} {'60':>8} {'200':>8} {'1000':>8} {'3000':>8} {'100000':>10}")
print(f"{'file_count':<35} {'100':>8} {'300':>8} {'1000':>8} {'2000':>8} {'60000':>10}")
print(f"{'queue_duration_seconds':<35} {'0':>8} {'1':>8} {'3':>8} {'8':>8} {'60':>10}")
print(f"{'db_duration_avg_seconds':<35} {'0':>8} {'0.1':>8} {'0.2':>8} {'0.8':>8} {'1200':>10}")
print(f"{'device_duration_avg_seconds':<35} {'2':>8} {'4':>8} {'9':>8} {'15':>8} {'500':>10}")
