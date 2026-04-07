"""
Synthetic data generator for order performance profiling.
Generates realistic data with embedded patterns:
- Normal orders (majority)
- System anomalies (same device, occasional extreme slowness)
- User behavior anomalies (contention, burst orders)
- Slow devices (a few devices consistently slower)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import string

np.random.seed(42)
random.seed(42)

NUM_ORDERS = 30000
NUM_DEVICES = 200
NUM_SLOW_DEVICES = 8  # ~4% of devices are consistently slow
SYSTEM_ANOMALY_RATE = 0.02  # 2% orders hit system anomalies
USER_BURST_RATE = 0.03  # 3% orders are from user burst patterns

# --- Dimension generators ---

LOCATIONS_1 = ["FAB-A", "FAB-B", "FAB-C"]
LOCATIONS_2 = ["AREA-1", "AREA-2", "AREA-3", None]
SYSTEM_NAMES = ["SYS-ALPHA", "SYS-BETA", "SYS-GAMMA"]
# ~50 device models (realistic: real data may have hundreds)
_MODEL_PREFIXES = ["MDL", "EQP", "TYP", "SER"]
_MODEL_SUFFIXES = [f"{i:03d}" for i in range(1, 51)]
DEVICE_MODES = [f"{p}-{s}" for p, s in zip(
    np.random.choice(_MODEL_PREFIXES, 50), _MODEL_SUFFIXES
)] + [None] * 10  # ~17% null rate

device_ids = [f"DEV-{i:04d}" for i in range(NUM_DEVICES)]
slow_device_ids = set(random.sample(device_ids, NUM_SLOW_DEVICES))

# Assign fixed attributes per device
device_attrs = {}
for did in device_ids:
    device_attrs[did] = {
        "device_mode_name": random.choice(DEVICE_MODES),
        "loc_1": random.choice(LOCATIONS_1),
        "loc_2": random.choice(LOCATIONS_2),
        "system_name": random.choice(SYSTEM_NAMES),
    }


def gen_order_id(idx):
    return f"ORD-{idx:06d}"


def gen_timestamp(base, idx):
    """Spread orders over ~30 days with realistic patterns."""
    offset = timedelta(
        days=random.uniform(0, 30),
        hours=random.gauss(10, 4),  # peak around 10am
        minutes=random.uniform(0, 60),
        seconds=random.uniform(0, 60),
    )
    ts = base + offset
    return ts


def gen_file_count():
    """96% < 2000, with a long tail."""
    r = random.random()
    if r < 0.30:
        return random.randint(5, 50)
    elif r < 0.60:
        return random.randint(50, 300)
    elif r < 0.85:
        return random.randint(300, 1000)
    elif r < 0.96:
        return random.randint(1000, 2000)
    else:
        return random.randint(2000, 5000)


def gen_normal_durations(file_count, is_slow_device):
    """Generate phase durations for a normal order."""
    # Queue: usually short
    queue = max(1, int(np.random.exponential(15)))

    # DB: scales mildly with file_count
    db_avg = max(1, int(np.random.normal(2, 0.5)))
    db_max = db_avg + random.randint(1, 5)
    db_p95 = db_avg + random.randint(0, 3)

    # Device: main variable, slower for slow devices
    base_device = 3 if not is_slow_device else random.choice([8, 12, 15, 20])
    device_avg = max(1, int(np.random.normal(base_device, 1.5)))
    device_max = device_avg + random.randint(2, 15)
    device_p95 = device_avg + random.randint(1, 8)

    # Inner processing: relatively fast
    inner_avg = max(1, int(np.random.normal(1.5, 0.5)))
    inner_max = inner_avg + random.randint(1, 4)
    inner_p95 = inner_avg + random.randint(0, 2)

    # Per file: composite
    per_file_avg = db_avg + device_avg + inner_avg
    per_file_max = db_max + device_max + inner_max
    per_file_p95 = db_p95 + device_p95 + inner_p95

    # Total file duration (minutes) — with 4 threads parallelism
    parallelism = 4
    total_file_minutes = max(1, int((file_count * per_file_avg) / parallelism / 60))

    # Total duration
    total_seconds = queue + total_file_minutes * 60

    return {
        "queue_duration_seconds": queue,
        "per_file_duration_avg_seconds": per_file_avg,
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
    """Randomly spike one or more phases."""
    anomaly_type = random.choice(["device_timeout", "db_lock", "queue_stuck"])
    if anomaly_type == "device_timeout":
        spike = random.randint(300, 1800)  # 5-30 min spike
        durations["device_duration_max_seconds"] += spike
        durations["device_duration_avg_seconds"] += spike // 3
        durations["total_duration_seconds"] += spike
    elif anomaly_type == "db_lock":
        spike = random.randint(120, 600)
        durations["db_duration_max_seconds"] += spike
        durations["db_duration_avg_seconds"] += spike // 4
        durations["total_duration_seconds"] += spike
    elif anomaly_type == "queue_stuck":
        spike = random.randint(600, 3600)  # 10-60 min stuck in queue
        durations["queue_duration_seconds"] += spike
        durations["total_duration_seconds"] += spike
    durations["_anomaly_type"] = anomaly_type
    return durations


def inject_user_burst(durations):
    """Simulate contention — queue and device times inflate."""
    durations["queue_duration_seconds"] += random.randint(60, 300)
    durations["device_duration_avg_seconds"] = int(durations["device_duration_avg_seconds"] * 1.5)
    durations["total_duration_seconds"] = int(durations["total_duration_seconds"] * 1.3)
    durations["_anomaly_type"] = "user_burst"
    return durations


# --- Main generation ---

base_time = datetime(2026, 3, 1)
records = []

for i in range(NUM_ORDERS):
    did = random.choice(device_ids)
    attrs = device_attrs[did]
    file_count = gen_file_count()
    is_slow = did in slow_device_ids

    durations = gen_normal_durations(file_count, is_slow)
    durations["_anomaly_type"] = "normal"

    # Inject anomalies
    r = random.random()
    if r < SYSTEM_ANOMALY_RATE:
        durations = inject_system_anomaly(durations)
    elif r < SYSTEM_ANOMALY_RATE + USER_BURST_RATE:
        durations = inject_user_burst(durations)

    anomaly_type = durations.pop("_anomaly_type")

    record = {
        "device_id": did,
        "device_mode_name": attrs["device_mode_name"],
        "order_created_at": gen_timestamp(base_time, i).strftime("%Y-%m-%d %H:%M:%S.%f"),
        "order_id": gen_order_id(i),
        "file_count": file_count,
        "loc_1": attrs["loc_1"],
        "loc_2": attrs["loc_2"],
        "system_name": attrs["system_name"],
        **durations,
        # Hidden label for validation only (not in real data)
        "_label": anomaly_type,
        "_is_slow_device": is_slow,
    }
    records.append(record)

df = pd.DataFrame(records)

# Save with labels (for validation)
df.to_csv("data/orders_with_labels.csv", index=False)

# Save without labels (simulates real data)
real_cols = [c for c in df.columns if not c.startswith("_")]
df[real_cols].to_csv("data/orders.csv", index=False)

print(f"Generated {len(df)} orders")
print(f"Slow devices: {sorted(slow_device_ids)}")
print(f"\nLabel distribution:")
print(df["_label"].value_counts())
print(f"\nFile count distribution:")
print(df["file_count"].describe())
print(f"\nTotal duration (seconds) distribution:")
print(df["total_duration_seconds"].describe())
print(f"\nSample slow orders (>3600s):")
slow = df[df["total_duration_seconds"] > 3600]
print(f"  Count: {len(slow)}")
if len(slow) > 0:
    print(f"  Max: {slow['total_duration_seconds'].max()}s = {slow['total_duration_seconds'].max()/3600:.1f}hr")
