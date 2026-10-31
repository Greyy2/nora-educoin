import os
import shutil
from pathlib import Path

def get_dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except Exception:
        pass
    return total

def fmt_bytes(n: int) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PiB"

print("=== DISK & FILESYSTEM INVENTORY ===")
root_stat = shutil.disk_usage("/home/vmc03/norabt")
print(f"Workspace (/home/vmc03/norabt): Total={fmt_bytes(root_stat.total)}, Used={fmt_bytes(root_stat.used)}, Free={fmt_bytes(root_stat.free)} ({root_stat.free / root_stat.total * 100:.1f}% free)")

data_paths = [
    Path("nora/data/catalog"),
    Path("nora/edu/data"),
    Path("nora/coin/data"),
    Path("nora/data/cache"),
]

for dp in data_paths:
    if dp.exists():
        size = get_dir_size(dp)
        file_count = sum(1 for _ in dp.rglob("*") if _.is_file())
        print(f"Directory {dp}: size={fmt_bytes(size)}, files={file_count}")
    else:
        print(f"Directory {dp}: NOT FOUND")

print("\n=== CGROUP & MEMORY LIMITS ===")
cgroup_candidates = [
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    Path("/sys/fs/cgroup/memory.high"),
]
found_cgroup = False
for cp in cgroup_candidates:
    if cp.exists():
        try:
            val = cp.read_text().strip()
            print(f"{cp}: {val} ({fmt_bytes(int(val)) if val.isdigit() else val})")
            found_cgroup = True
        except Exception as e:
            print(f"{cp}: error reading ({e})")

if not found_cgroup:
    print("No standard cgroup v1/v2 memory file found at inspected paths")

# Process memory limits
try:
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    print(f"RLIMIT_AS (virtual memory limit): soft={fmt_bytes(soft) if soft != -1 else 'unlimited'}, hard={fmt_bytes(hard) if hard != -1 else 'unlimited'}")
except Exception as e:
    print(f"RLIMIT_AS query error: {e}")

# Process status
try:
    with open("/proc/self/status") as f:
        for line in f:
            if any(line.startswith(k) for k in ["VmPeak:", "VmSize:", "VmHWM:", "VmRSS:"]):
                print(f"Proc status: {line.strip()}")
except Exception as e:
    print(f"Proc status query error: {e}")
