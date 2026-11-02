"""driver.py — TSec Benchmark run loop driving the Ouroboros agent.

Flow (mirrors the SDK quick-start template):
  1. bootstrap the agent workspace from env (providers/scope)
  2. start `ouro serve` headless, wait for /api/health
  3. SDK VPN precheck (raises VpnCheckError before any platform call)
  4. for each incomplete challenge:
       start container -> update agent scope to its addresses
       -> agent solve loop -> submit each flag -> close container
  5. print the final scoreboard summary

Resource rule: at most 3 active challenges — the driver is strictly
sequential (start -> solve -> close), so the cap is never approached.
"""
import os
import subprocess
import sys
import time

from tsec_benchmark import (
    DuplicateSubmit,
    InvalidState,
    ResourceUnavailable,
    TSecBenchmark,
    VpnCheckError,
)

import agent_bridge
import bootstrap_workspace

WORKSPACE = os.environ.get("OURO_WORKSPACE", "/agent/workspace")
API_PORT = os.environ.get("OURO_API_PORT", "8090")
AGENT_LOG = os.environ.get("OURO_AGENT_LOG", "/agent/ouro.log")


def start_agent() -> subprocess.Popen:
    log = open(AGENT_LOG, "ab")
    proc = subprocess.Popen(
        ["/agent/ouro", "serve", WORKSPACE, "--port", API_PORT],
        stdout=log, stderr=log,
    )
    print(f"[driver] agent pid={proc.pid} port={API_PORT}", flush=True)
    return proc


def main() -> int:
    bootstrap_workspace.main()

    agent = start_agent()
    try:
        agent_bridge.wait_ready()
        print("[driver] agent API ready", flush=True)

        token = os.environ.get("BENCHMARK_TOKEN", "")
        base_url = os.environ.get("BENCHMARK_BASE_URL", "")
        if not token or not base_url:
            print("[driver] BENCHMARK_TOKEN / BENCHMARK_BASE_URL missing",
                  file=sys.stderr, flush=True)
            return 2

        with TSecBenchmark(base_url=base_url, token=token) as client:
            challenges = client.list_challenges()
            print(f"[driver] {len(challenges)} challenges", flush=True)

            solved = 0
            for ch in challenges:
                if ch.is_completed:
                    print(f"[driver] {ch.unique_code}: already completed",
                          flush=True)
                    continue
                try:
                    started = client.start_challenge(ch.unique_code)
                except ResourceUnavailable:
                    print(f"[driver] {ch.unique_code}: resource unavailable, "
                          "skipping", flush=True)
                    continue
                addrs = [f"http://{a}" for a in started.container_addr]
                print(f"[driver] {ch.unique_code} -> {addrs}", flush=True)
                try:
                    agent_bridge.update_scope(addrs, WORKSPACE)
                    flags = agent_bridge.solve_challenge(
                        ch.description, addrs, ch.flag_count)
                    print(f"[driver] {ch.unique_code}: agent found "
                          f"{len(flags)} flag(s)", flush=True)
                    for flag in flags:
                        try:
                            res = client.submit_flag(ch.unique_code, flag)
                            print(f"[driver]   submit {flag[:24]}... "
                                  f"correct={res.correct} "
                                  f"awarded={res.awarded} "
                                  f"progress={res.correct_flag_count}/"
                                  f"{res.total_flag_count}", flush=True)
                        except DuplicateSubmit:
                            pass
                except InvalidState as exc:
                    print(f"[driver] {ch.unique_code}: invalid state: {exc}",
                          flush=True)
                    raise
                finally:
                    client.close_challenge(ch.unique_code)
                if ch.unique_code:
                    pass
            print(f"[driver] run complete", flush=True)
            return 0
    except VpnCheckError as exc:
        print(f"[driver] VPN check failed: {exc}", file=sys.stderr, flush=True)
        return 3
    finally:
        agent.terminate()
        try:
            agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            agent.kill()


if __name__ == "__main__":
    sys.exit(main())
