"""parallel_entry.py — mode-selectable benchmark entrypoint.

OURO_DRIVE_MODE:
  parent   — ONE parent agent orchestrating via SPAWN/COLLECT sub-loops
             (the architecture upgrade: bounded sub-loop contexts, lean parent)
  sharded  — N independent sharded workers (fallback / comparison mode)
"""
import os
import subprocess
import sys

MODE = os.environ.get("OURO_DRIVE_MODE", "orchestrated")

if MODE == "single":
    print("[entry] single-engagement mode", flush=True)
    sys.exit(subprocess.call([sys.executable, "-u", "/agent/drive_single.py"]))
elif MODE == "orchestrated":
    print("[entry] hard-pipeline mode", flush=True)
    sys.exit(subprocess.call([sys.executable, "-u", "/agent/drive_orchestrated.py"]))
elif MODE == "parent":
    print("[entry] parent-orchestration mode", flush=True)
    sys.exit(subprocess.call([sys.executable, "-u", "/agent/drive_parent.py"]))

TOTAL = int(os.environ.get("OURO_WORKER_TOTAL", "3"))
procs = []
for index in range(TOTAL):
    env = dict(os.environ)
    env["OURO_WORKER_INDEX"] = str(index)
    env["OURO_WORKER_TOTAL"] = str(TOTAL)
    procs.append(subprocess.Popen(
        [sys.executable, "-u", "/agent/drive_autonomous.py"], env=env))
    print(f"[entry] worker {index} spawned", flush=True)

exit_codes = [p.wait() for p in procs]
print(f"[entry] all workers done: {exit_codes}", flush=True)
sys.exit(max(exit_codes) if exit_codes else 0)
