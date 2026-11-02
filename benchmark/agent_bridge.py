"""agent_bridge.py — drive the Ouroboros agent over its local HTTP API.

The agent binary runs headless (`ouro serve`). This bridge talks to
/api/ai/chat: the model behind it reasons over raw observations and replies
with ACTION: lines (OBSERVE / BLACKBOARD / READ / WRITE / SEARCH ...) which
the backend executes scope-gated. The bridge feeds each challenge target
into the conversation and collects flags the model reports.

All knobs are env-driven (AGENTS.md): ports, timeouts, retries.
"""
import json
import os
import re
import time
import urllib.request
from typing import Any

API_PORT = int(os.environ.get("OURO_API_PORT", "8090"))
API_BASE = f"http://127.0.0.1:{API_PORT}"
CHAT_TIMEOUT = int(os.environ.get("OURO_CHAT_TIMEOUT_S", "600"))
FLAG_PATTERN = re.compile(os.environ.get(
    "OURO_FLAG_PATTERN", r"flag\{[^}\s]{1,256}\}"))


class AgentError(RuntimeError):
    pass


def _post(path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: int = 30) -> Any:
    with urllib.request.urlopen(API_BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_ready(deadline_s: int = 120) -> None:
    """Block until /api/health answers (backend boot + workspace init)."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            _get("/api/health")
            return
        except Exception:
            time.sleep(1.0)
    raise AgentError("agent API did not become ready in time")


def update_scope(targets: list[str], workspace: str) -> None:
    """Rewrite scope.yaml targets for the current challenge. The agent
    reads scope.yaml at call time (authorizeObserveTarget → LoadScopeConfig
    per request), so no backend restart is needed."""
    scope = ["version: 1", "scope:", "  target_policy: enforce", "  targets:"]
    scope += [f"    - kind: url\n      value: {t}" for t in targets]
    scope += ["  exclusions: []", "execution:", "  isolation: process"]
    with open(f"{workspace}/scope.yaml", "w", encoding="utf-8") as fh:
        fh.write("\n".join(scope) + "\n")


def ask_agent(prompt: str) -> str:
    """Send one chat turn; return the assistant content."""
    out = _post("/api/ai/chat", {"message": prompt}, timeout=CHAT_TIMEOUT)
    msg = out.get("message") or {}
    return msg.get("content", "")


def extract_flags(text: str) -> list[str]:
    return list(dict.fromkeys(FLAG_PATTERN.findall(text)))


SOLVE_PROMPT = """目标渗透测试已授权（TSec Benchmark 跑分任务，scope 已限定为该题目容器）。
靶场地址：{addrs}
题目描述：{description}
请系统性地完成侦察与漏洞检测，找到所有 flag（可能不止一个，共 {flag_count} 个）。
约束：
- 使用 ACTION:OBSERVE 观测目标（零判定原始观测），基于观测推理后再决定下一步。
- 发现的每个 flag 以单独一行 `FLAG: flag{...}` 的形式输出。
- 不做破坏性操作（不删库、不改配置、不做 DoS）。
"""


def solve_challenge(description: str, addrs: list[str], flag_count: int,
                    max_turns: int = 8) -> list[str]:
    """Multi-turn solve loop: keep prompting while the agent makes progress
    and has not yet reported the expected number of flags."""
    found: list[str] = []
    history_hint = ""
    for turn in range(max_turns):
        prompt = SOLVE_PROMPT.format(
            addrs=", ".join(addrs), description=description or "(无)",
            flag_count=flag_count,
        )
        if turn > 0:
            prompt += f"\n\n此前你已发现这些 flag：{found or '（尚无）'}。继续深入。"
        prompt += history_hint
        reply = ask_agent(prompt)
        flags = extract_flags(reply)
        for flag in flags:
            if flag not in found:
                found.append(flag)
        history_hint = f"\n\n上一轮你的回复（截断）：\n{reply[:2000]}"
        if len(found) >= flag_count:
            break
        if turn == max_turns - 1:
            break
        # Let the agent continue its reasoning chain within one turn budget.
        time.sleep(1.0)
    return found
