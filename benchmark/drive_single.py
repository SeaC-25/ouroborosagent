"""drive_single.py — single-engagement orchestrator (v28.4).

For platforms without a challenge-scheduling API (CTFy GAUNTLET single
engagements): no list/start/submit conveyor — the mission card IS the task.
The driver's job degenerates to:
  1. inject the mission card once
  2. keep the agent alive with a light idle-guard loop (no platform
     scoreboard to reconcile — observations come from the blackboard)
  3. surface sub-loop results and FLAG{...} finds to the operator

Flag submission is NOT automated here: single-engagement platforms take
flags via their own channel (MCP tool / web UI) — the agent writes findings
to the blackboard; the operator (or an outer wrapper) submits.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

API_PORT = int(os.environ.get("OURO_API_PORT", "8090"))
API = f"http://127.0.0.1:{API_PORT}"
WORKSPACE = os.environ.get("OURO_WORKSPACE", "/agent/workspace-parent")
MISSION = os.environ.get("OURO_MISSION", "")
MISSION_FILE = os.environ.get("OURO_MISSION_FILE", "")
MAX_TURNS = int(os.environ.get("OURO_MAX_TURNS", "3000"))
TURN_DELAY = float(os.environ.get("OURO_TURN_DELAY_S", "30"))

ACTION_RE = re.compile(r"^ACTION:\w+", re.MULTILINE)
FLAG_RE = re.compile(r"FLAG\{[^}\s]{1,256}\}")
PROVIDER_FAIL_MARKERS = ("模型调用失败", "generation failed", "provider_error")


def direct_open(req, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def chat(message: str, timeout: int = 280, max_tokens: int = 0) -> str:
    body = {"message": message}
    if max_tokens:
        body["maxTokens"] = max_tokens
    req = urllib.request.Request(
        API + "/api/ai/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(3):
        try:
            with direct_open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))["message"]["content"]
        except Exception as exc:
            print(f"[single] chat retry {attempt + 1}: {exc}", flush=True)
            time.sleep(5)
    return ""


def chat_until_ok(message: str, max_retries: int = 12) -> str:
    delay = 5.0
    reply = ""
    for attempt in range(max_retries):
        reply = chat(message)
        if reply and not any(m in reply for m in PROVIDER_FAIL_MARKERS):
            return reply
        print(f"[single] provider failure (attempt {attempt + 1}), backoff {delay:.0f}s", flush=True)
        time.sleep(delay)
        delay = min(delay * 1.7, 60.0)
    return reply


def subloops() -> list:
    try:
        with direct_open(urllib.request.Request(API + "/api/ai/subloops"), timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")).get("subloops", [])
    except Exception:
        return []


def board_facts(ws: str) -> list:
    """Read the blackboard for FLAG finds and recent conclusions."""
    try:
        path = f"{ws}/runtime/blackboard.jsonl"
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:
        return []


def main() -> int:
    mission = MISSION
    if not mission and MISSION_FILE and os.path.exists(MISSION_FILE):
        mission = open(MISSION_FILE, encoding="utf-8").read()
    if not mission:
        print("[single] no mission (OURO_MISSION / OURO_MISSION_FILE)", file=sys.stderr, flush=True)
        return 2

    # Bootstrap (env-only workspace, same schema as the other drivers).
    os.makedirs(f"{WORKSPACE}/runtime", exist_ok=True)
    os.makedirs(f"{WORKSPACE}/replay", exist_ok=True)
    name = os.environ.get("OURO_PROVIDER_NAME", "benchmark-provider")
    model = os.environ.get("OURO_PROVIDER_MODEL", "")
    base_env = os.environ.get("OURO_PROVIDER_BASE_URL_ENV", "OURO_PROVIDER_BASE_URL")
    key_env = os.environ.get("OURO_PROVIDER_KEY_ENV", "OURO_PROVIDER_API_KEY")
    open(f"{WORKSPACE}/providers.yaml", "w", encoding="utf-8").write(
        f"version: 1\nproviders:\n  - name: {name}\n"
        f"    type: openai_compatible\n    model: {model}\n"
        f"    base_url_env: {base_env}\n    api_key_env: {key_env}\n"
        f"    timeout_ms: 180000\n    capabilities: [chat, code, reasoning]\n"
        f"    enabled: true\n")
    open(f"{WORKSPACE}/scope.yaml", "w", encoding="utf-8").write(
        "version: 1\nscope:\n  target_policy: disabled\n  targets: []\n"
        "  exclusions: []\nexecution:\n  isolation: process\n")
    open(f"{WORKSPACE}/authorization.yaml", "w", encoding="utf-8").write(
        "version: 1\nsafety_bypasses:\n  - control: scope.target_policy\n    mode: disabled\n"
        "    authorized_by: operator\n    reason: authorized engagement\n")
    kb_link = os.path.join(WORKSPACE, "kb")
    kb_src = os.environ.get("OURO_KB_SRC", "/agent/kb")
    if not os.path.exists(kb_link) and os.path.exists(kb_src):
        try:
            os.symlink(kb_src, kb_link)
        except OSError:
            import shutil
            shutil.copytree(kb_src, kb_link)

    agent_bin = os.environ.get("OURO_AGENT_BIN", "/agent/ouro")
    log_path = os.environ.get("OURO_LOG_PATH", "/agent/ouro-parent.log")
    agent = subprocess.Popen(
        [agent_bin, "serve", WORKSPACE, "--port", str(API_PORT)],
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT)
    print(f"[single] agent pid={agent.pid}", flush=True)
    deadline = time.time() + 120
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        try:
            with opener.open(API + "/api/health", timeout=5):
                break
        except Exception:
            time.sleep(1.0)
    print("[single] agent ready", flush=True)

    try:
        # Phase 1: inject the mission card (with exploration clause from the
        # autonomy contract already in the system prompt).
        kickoff = (
            mission
            + "\n\n立即开始：先派并行侦察子循环（公网面/端口面各一条，结论写黑板），"
              "基于侦察证据逐步深入。发现 FLAG{...} 立即 ACTION:BLACKBOARD 落盘并继续找下一个。")
        content = chat_until_ok(kickoff)
        print(f"[single] mission injected, turn 1 len={len(content)}", flush=True)

        # MBEE intent loop (v28.4 architecture): every cycle presents FACTS
        # (board deltas + sub-loop states + flags) and asks for ONE bounded
        # intent — the 330-char envelope physically cannot become an essay.
        # Intent failure/timeout falls back to a default policy. The open
        # conversational loop was the analysis-paralysis incubator (79 READs
        # doing file archaeology instead of touching the target).
        seen_flags = set()
        for turn in range(2, MAX_TURNS + 1):
            loops = subloops()
            running = [l for l in loops if l["status"] == "running"]
            facts = board_facts(WORKSPACE)
            new_flags = set()
            for f in facts:
                for flag in FLAG_RE.findall(f.get("statement", "")):
                    new_flags.add(flag)
            fresh = new_flags - seen_flags
            if fresh:
                seen_flags |= fresh
                print(f"[single] FLAG FOUND: {sorted(fresh)}", flush=True)

            # Situation = facts only, no conversation history.
            situation_lines = [f"任务：{MISSION[:120]}"]
            if fresh:
                situation_lines.append(f"新捕获 flag：{sorted(fresh)}")
            if loops:
                situation_lines.append("子循环：" + "; ".join(
                    f"{l['name']}={l['status']}(轮{l['turns']})" for l in loops[:5]))
            recent = facts[-6:] if len(facts) > 6 else facts
            for f in recent:
                situation_lines.append(f"- {f.get('statement', '')[:100]}")
            situation = "\n".join(situation_lines)

            # Ask MBEE (bounded envelope + guillotine).
            intent_out = ""
            try:
                req = urllib.request.Request(
                    API + "/api/ai/mbee-intent",
                    data=json.dumps({"situation": situation}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                with direct_open(req, timeout=45) as resp:
                    intent_out = json.loads(resp.read().decode("utf-8")).get("result", "")
            except Exception as exc:
                print(f"[single] mbee unavailable ({exc}), default policy", flush=True)

            # Default policy when no usable intent: keep >=1 recon loop alive.
            if "SPAWN_PULSE" not in intent_out and not running:
                # Default policy via the DIRECT spawn endpoint: zero LLM
                # dependency for the spawn itself (chat-path spawns were
                # eaten by model thinking timeouts every cycle).
                goal = "侦察目标面：用域名观测任务卡列出的入口（www/shop/blog.vantageoutfitters.example——网关需正确 Host 头，裸 IP 会 502）。记录技术栈指纹、表单/登录点、JS 路由、可疑路径，全部 ACTION:BLACKBOARD 写黑板后 DONE"
                try:
                    req2 = urllib.request.Request(
                        API + "/api/ai/spawn-direct",
                        data=json.dumps({"name": f"recon-{turn}", "goal": goal}).encode("utf-8"),
                        headers={"Content-Type": "application/json"}, method="POST")
                    with direct_open(req2, timeout=30) as resp:
                        print(f"[single] direct-spawned recon-{turn}", flush=True)
                except Exception as exc:
                    print(f"[single] direct spawn failed: {exc}", flush=True)
            print(f"[single] turn {turn} flags={len(seen_flags)} running={len(running)} intent={'yes' if intent_out else 'default'}", flush=True)
            time.sleep(TURN_DELAY)
    finally:
        agent.terminate()
        try:
            agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            agent.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
