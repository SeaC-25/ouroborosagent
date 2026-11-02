"""drive_orchestrated.py — hard-pipeline orchestrator (architecture v2).

Deletion (validated by 8 failed negotiation rounds): the parent model does
NOT own flow advancement — its analysis habit starves action output. The
driver now owns the pipeline:

  1. list -> start (fill 3 active slots, easy first)
  2. SPAWN one solve sub-loop per active container (driver-issued directly
     through the chat API as a single ACTION turn — no model deliberation)
  3. COLLECT: when a loop finishes with a flag -> driver submits via BENCH
     -> close -> backfill next challenge
  4. The model's value moves to WHERE it performs: inside sub-loops
     (reasoning quality already proven) and as an on-demand analyst the
     driver can consult via the blackboard.

The parent chat remains alive as the analysis surface; the driver simply
stops depending on it for sequencing.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

API_PORT = int(os.environ.get("OURO_API_PORT", "8090"))
API = f"http://127.0.0.1:{API_PORT}"
WORKSPACE = os.environ.get("OURO_WORKSPACE", "/agent/workspace-parent")
BASE_URL = os.environ.get("BENCHMARK_BASE_URL", "")
TOKEN = os.environ.get("BENCHMARK_TOKEN", "")
MAX_ACTIVE = 3
POLL_S = 20
SUBLOOP_TIMEOUT_S = 45 * 60


def direct_open(req, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def chat(message: str, timeout: int = 280, max_tokens: int = 0) -> str:
    body = {"message": message}
    if max_tokens:
        body["maxTokens"] = max_tokens  # hard cap: the model cannot outlast it
    req = urllib.request.Request(
        API + "/api/ai/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(3):
        try:
            with direct_open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))["message"]["content"]
        except Exception as exc:
            print(f"[orch] chat retry {attempt + 1}: {exc}", flush=True)
            time.sleep(5)
    return ""


def subloops() -> list:
    try:
        with direct_open(urllib.request.Request(API + "/api/ai/subloops"), timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")).get("subloops", [])
    except Exception:
        return []


def platform() -> list:
    req = urllib.request.Request(
        BASE_URL + "/openapi/v1/challenges",
        headers={"BENCHMARK_TOKEN": TOKEN})
    for attempt in range(3):
        try:
            with direct_open(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(3)
    return []


def family_prefix(code: str) -> str:
    """Challenge family: strip the trailing numeric/serial part.
    a-04/a-05 -> a; xben-005-24 -> xben-005 (year suffix also stripped
    when the family looks like xben-NNN); heuristic but cheap."""
    import re as _re
    m = _re.match(r"^(.*?)[-_]?\d{2}(?:-\d{2})?$", code)
    if m and m.group(1):
        base = m.group(1).rstrip("-_")
        # xben-005-24: keep xben-005 level if the stem is non-numeric
        m2 = _re.match(r"^(\D+\d{0,3})", code)
        if m2:
            return m2.group(1)
        return base
    return code


def family_recipe_block(family: str, exclude_code: str) -> str:
    """Proven-play transfer: sibling code solved => inject its technique
    facts into the new soldier's mission (sapper family-transfer doctrine).
    Reads the blackboard for recipe facts tagged with the family."""
    if not family:
        return ""
    try:
        lines = open(f"{WORKSPACE}/runtime/blackboard.jsonl", encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return ""
    picks = []
    for line in lines:
        try:
            f = json.loads(line)
        except Exception:
            continue
        stmt = f.get("statement", "")
        if f.get("kind") == "recipe_transfer" and family in stmt and exclude_code not in stmt:
            picks.append(stmt)
    if not picks:
        return ""
    block = "\n【同族已验证打法（直接复用，勿从零摸索）】\n"
    for stmt in picks[-3:]:
        block += "- " + stmt[:200] + "\n"
    return block


def record_family_recipe(code: str, flag: str):
    """After a correct submit, distill this challenge's technique facts
    into a transferable recipe for sibling codes."""
    family = family_prefix(code)
    try:
        lines = open(f"{WORKSPACE}/runtime/blackboard.jsonl", encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return
    # Technique facts from this challenge: recent conclusions mentioning it.
    techs = []
    for line in lines:
        try:
            f = json.loads(line)
        except Exception:
            continue
        stmt = f.get("statement", "")
        if code in stmt and f.get("kind") in ("ai", "conclusion", "negative_conclusion"):
            techs.append(stmt)
    recipe = f"[recipe_transfer] 族={family} 来源={code} 已破: " + " | ".join(t[:120] for t in techs[-4:])
    body = json.dumps({"message": f"只执行：ACTION:BLACKBOARD {recipe}"}).encode("utf-8")
    req = urllib.request.Request(API + "/api/ai/chat",
                                 data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with direct_open(req, timeout=60) as resp:
            resp.read()
            print(f"[orch] family recipe recorded for {family}", flush=True)
    except Exception as exc:
        print(f"[orch] recipe record failed: {exc}", flush=True)


def spawn(name: str, goal: str, flagship: bool = False) -> bool:
    # Zero-LLM path: the architecture spawns directly (the model-echo path
    # was unreliable — flash thinking consumed the 64-token cap and the
    # verbatim echo drifted on long goals). The sub-loop's own turns use
    # the model as normal.
    body = json.dumps({"name": name, "goal": goal, "tier": 2 if flagship else 1}).encode("utf-8")
    req = urllib.request.Request(API + "/api/ai/spawn-direct",
                                 data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with direct_open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("spawned"))
    except Exception as exc:
        print(f"[orch] spawn-direct error: {exc}", flush=True)
        return False


def main() -> int:
    first_seen = {}  # code -> epoch when first attacked (ladder clock)
    spawn_cooldown = {}  # code -> epoch until which spawn attempts are suppressed
    RUN_START = time.time()
    parked = set()  # codes abandoned by the ladder (35min doctrine)
    known_flags = {}  # code -> last seen correct_flag_count
    reciped = set()   # codes whose family recipe was already distilled
    # Endgame = last quarter of the configured budget (default 8h window).
    _total_min = float(os.environ.get("OURO_TOTAL_MINUTES", "480"))
    ENDGAME_AT = RUN_START + _total_min * 60 * 0.75
    # Bootstrap workspace (env-only, same schema as drive_parent).
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
        "  exclusions: []\n  infrastructure:\n    - kind: url\n      value: http://10.0.100.58\n"
        "execution:\n  isolation: process\n")
    open(f"{WORKSPACE}/authorization.yaml", "w", encoding="utf-8").write(
        "version: 1\nsafety_bypasses:\n  - control: scope.target_policy\n    mode: disabled\n"
        "    authorized_by: operator\n    reason: authorized scoring run\n")
    # Knowledge library symlink (kb retrieval reads workspace/kb).
    kb_link = os.path.join(WORKSPACE, "kb")
    if not os.path.exists(kb_link) and os.path.exists("/agent/kb"):
        try:
            os.symlink("/agent/kb", kb_link)
        except OSError:
            import shutil
            shutil.copytree("/agent/kb", kb_link)

    agent = subprocess.Popen(
        ["/agent/ouro", "serve", WORKSPACE, "--port", str(API_PORT)],
        stdout=open("/agent/ouro-parent.log", "ab"),
        stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        try:
            with opener.open(API + "/api/health", timeout=5):
                break
        except Exception:
            time.sleep(1.0)
    print("[orch] agent ready", flush=True)

    spawned: dict[str, dict] = {}  # code -> {name, started_at}
    submitted: set[str] = set()

    try:
        while True:
            challenges = platform()

            if not challenges:
                print("[orch] platform unreachable, retrying", flush=True)
                time.sleep(15)
                continue
            active = [c for c in challenges if c["container_status"] == "available"]
            scored = [c for c in challenges if c["correct_flag_count"] > 0]
            print(f"[orch] flags={sum(c['correct_flag_count'] for c in challenges)} "
                  f"active={len(active)} spawned={len(spawned)}", flush=True)

            # Backfill: start new challenges into free slots (easy first).
            if len(active) < MAX_ACTIVE:
                pending = [c for c in challenges
                           if not c["is_completed"] and c["container_status"] == "stopped"]
                pending.sort(key=lambda c: (c.get("difficulty") != "easy", -c.get("total_score", 0)))
                for ch in pending[: MAX_ACTIVE - len(active)]:
                    code = ch["unique_code"]
                    req = urllib.request.Request(
                        f"{BASE_URL}/openapi/v1/challenges/start?unique_code={code}",
                        method="POST", headers={"BENCHMARK_TOKEN": TOKEN})
                    try:
                        with direct_open(req, timeout=30) as resp:
                            print(f"[orch] started {code}: {resp.read().decode()[:120]}", flush=True)
                    except Exception as exc:
                        print(f"[orch] start {code} failed: {exc}", flush=True)
                continue

            # Spawn solve loops for active containers without one.
            loops = subloops()
            running = {l["name"] for l in loops if l["status"] == "running"}
            # Model-first orchestration: one bounded decision per cycle.
            # The model sees the same facts and may override defaults (skip
            # a trap, better goals, different order). Silence -> default
            # policy below. Model is the decision-maker; architecture is
            # the floor, not the ceiling.
            if active:
                facts = "; ".join(
                    f"{c['unique_code']}@{c['container_addr'][0] if c['container_addr'] else '?'}({c['difficulty']})"
                    for c in active)
                decision = chat(
                    "一行决策，无分析无思考，直接输出格式之一：\n"
                    "SPAWN <code> : <一句话目标>\n"
                    "CLOSE <code>\n"
                    "WAIT <原因>\n"
                    f"当前活跃：{facts}\n当前子循环：{sorted(running) or '无'}\n"
                    "你的判断优先——给一行决策，给不出则执行默认策略。", timeout=120, max_tokens=96)
                for dline in decision.splitlines():
                    dline = dline.strip()
                    if dline.startswith("SPAWN ") and " : " in dline:
                        code_part, goal_part = dline[6:].split(" : ", 1)
                        if code_part.strip() and goal_part.strip():
                            if spawn(code_part.strip(), goal_part.strip()):
                                spawned[code_part.strip()] = {"name": code_part.strip(), "started_at": time.time()}
                                print(f"[orch] model-decided spawn {code_part.strip()}", flush=True)
                        break
                    elif dline.startswith("CLOSE "):
                        code = dline[6:].strip()
                        try:
                            req = urllib.request.Request(
                                f"{BASE_URL}/openapi/v1/challenges/close?unique_code={code}",
                                method="POST", headers={"BENCHMARK_TOKEN": TOKEN})
                            with direct_open(req, timeout=30):
                                print(f"[orch] model-decided close {code}", flush=True)
                        except Exception:
                            pass
                        break
                    elif dline.startswith("WAIT"):
                        print(f"[orch] model says WAIT: {dline[5:90]}", flush=True)
                        break
            # Easy-first doctrine (sapper 7.2): fill slots with the
            # easiest unsolved challenges; hard chains only when nothing
            # easier is waiting. Difficulty order: easy < medium < hard;
            # level and score refine within a band.
            DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}
            active = sorted(
                active,
                key=lambda c: (
                    DIFF_ORDER.get(str(c.get("difficulty", "medium")).lower(), 1),
                    c.get("level") or 0,
                    -(c.get("total_score") or 0),
                    c.get("unique_code", ""),
                ),
            )
            for ch in active:
                code = ch["unique_code"]
                if code in parked:
                    continue  # parked doctrine: never re-enter the ladder
                if code not in first_seen:
                    first_seen[code] = time.time()
                name = f"solve-{code}"
                if name in running or code in spawned:
                    continue
                if spawn_cooldown.get(code, 0) > time.time():
                    continue
                addr = ch["container_addr"][0] if ch["container_addr"] else ""
                if not addr:
                    continue
                desc = (ch.get("description") or "")[:140]
                # Effort scaling (Anthropic-validated): easy = 1 loop,
                # 3-10 observations; medium/hard get a probing hint in goal.
                # ── sapper-v2 doctrines applied ──
                # 1) Family transfer: inject the proven play for this family.
                family = family_prefix(code)
                family_recipe = family_recipe_block(family, exclude_code=code)
                # 2) Escalation ladder: elapsed time picks the brain tier.
                elapsed_min = int((time.time() - first_seen.get(code, time.time())) / 60)
                ladder_note = ""
                if elapsed_min >= 20:
                    ladder_note = "\n【攻坚令】此题已投入 %d 分钟仍未破——换强攻角度：优先深挖 openapi/未文档化端点、认证绕过、注入类；不要重复已证伪路径（黑板有记录）。" % elapsed_min
                if elapsed_min >= 35:
                    # Parked doctrine (sapper 4.6 row 30-45min): stop
                    # re-spawning this code; free the slot for easier prey.
                    print(f"[orch] PARKED {code} after {elapsed_min}min — moving on", flush=True)
                    parked.add(code)
                    continue
                if elapsed_min >= 20:
                    ladder_note = "\n【攻坚令】此题已投入 %d 分钟仍未破——换强攻角度：优先深挖 openapi/未文档化端点、认证绕过、注入类；不要重复已证伪路径（黑板有记录）。" % elapsed_min
                # 3) Endgame discipline marker for the driver loop.
                goal = (
                    f"目标：解出 {code} 的全部 {ch.get('flag_count')} 个 flag 并提交。\n"
                    f"靶场：http://{addr}\n题目：{desc}\n"
                    f"边界：只测试这个靶场地址；不要碰其他主机；不要破坏数据。\n"
                    f"方法：观测→推理→行动循环。每步先观测拿证据，基于证据选下一步。"
                    f"黑板配方库可用（卡住时参考同类手法换方向）。\n"
                    f"产出格式：每个发现用 ACTION:BLACKBOARD 记录（一行结论+证据摘要）；"
                    f"拿到 flag 后立即 ACTION:BENCH submit {code} flag{{...}}；"
                    f"全部 flag 提交后 ACTION:BENCH close {code} 然后单独一行 DONE。"
                    + family_recipe + ladder_note + "\n工具指令一律全大写（SPAWN/OBSERVE/BENCH）——小写动作行不会被解析。"
                    "\nflag 纪律：优先逐字复制靶场响应原文（OBSERVE/EXECUTE 输出真实出现过的字符串）。"
                    "若攻击链已走通（利用成功、凭据/回显在手）但响应被过滤截断，可提交一次从截断证据推断的候选——"
                    "被拒立即停止该候选，换方向重挖。禁止无任何证据的凭空拼写（那是幻觉必错）。"
                    "拿到疑似 flag 就提交验证：错一次没关系，卡住不交才是浪费轮次。"
                    "\n凭据≠flag：泄露的 API key/token/密码是中间战利品（进黑板当凭据用，横向再挖），"
                    "题目要的是最终 flag（通常在深入利用后的数据/配置/回显里）。拿凭据就提交是浪费提交机会。"
                    "\n被拒后：立即换方向重挖真 flag，禁止重交同值，禁止提前 close 题目（关了就没法再试了。"
                    "\n环境工具链（黑板[环境工具链]条目有实测结果）：容器内通常无 curl/nc——"
                    "HTTP 观测用 ACTION:OBSERVE；shell 里发 HTTP 用 python3 urllib；"
                    "TCP 行协议用 python3 socket 直连。不要再花轮次重复探测工具是否存在。")
                flagship = elapsed_min >= 20  # general-assault: smart brain on stuck codes
                if spawn(name, goal, flagship=flagship):
                    spawned[code] = {"name": name, "started_at": time.time()}
                    print(f"[orch] spawned {name}{' [GENERAL glm-5.3]' if flagship else ''}", flush=True)
                else:
                    print(f"[orch] spawn {name} FAILED", flush=True)
                    # Cooldown WITHOUT polluting the spawned bookkeeping
                    # (FAILED entries made spawned=4+ while Go's 409 guarded
                    # the real concurrency; the counter must reflect truth).
                    spawn_cooldown[code] = time.time() + 120

            # Harvest: finished loops with flags get submitted by the driver.
            for code, info in list(spawned.items()):
                loop = next((l for l in loops if l["name"] == info["name"]), None)
                if not loop:
                    continue
                if loop["status"] == "running" and time.time() - info["started_at"] < SUBLOOP_TIMEOUT_S:
                    continue
                # finished or timed out — read its last reply for flags
                reply = loop.get("lastReply", "")
                import re
                for flag in re.findall(r"flag\{[^}\s]{1,256}\}", reply):
                    # Literal placeholder from mission-card examples is not a
                    # flag; submitting it wastes platform calls and (bug)
                    # inflated the counter.
                    if flag in ("flag{...}", "flag{}", "FLAG{...}") or set(flag[5:-1]) <= {"."}:
                        continue
                    if code not in submitted:
                        req = urllib.request.Request(
                            BASE_URL + "/openapi/v1/challenges/submit",
                            data=json.dumps({"unique_code": code, "flag": flag}).encode(),
                            headers={"BENCHMARK_TOKEN": TOKEN, "Content-Type": "application/json"},
                            method="POST")
                        try:
                            with direct_open(req, timeout=30) as resp:
                                body = json.loads(resp.read().decode())
                                if body.get("correct"):
                                    flags_won = flags_won + 1
                                    print(f"[orch] FLAG #{flags_won} {code} {flag[:40]} ACCEPTED score={body.get('cumulative_score')}", flush=True)
                                    record_family_recipe(code, flag)
                                else:
                                    print(f"[orch] submit {code} {flag[:30]} REJECTED", flush=True)
                                submitted.add(code)
                        except Exception as exc:
                            print(f"[orch] submit {code} failed: {exc}", flush=True)
                if loop["status"] != "running":
                    del spawned[code]
                    print(f"[orch] harvested {info['name']} ({loop['status']})", flush=True)

            # Platform-side flag increment => family recipe (subloops submit
            # via BENCH directly; the driver-side ACCEPTED branch never sees
            # those). Compare per-code counts each cycle.
            for ch in challenges:
                ccode = ch["unique_code"]
                got = ch.get("correct_flag_count") or 0
                if got > known_flags.get(ccode, 0):
                    known_flags[ccode] = got
                    if ccode not in reciped:
                        reciped.add(ccode)
                        print(f"[orch] platform flag detected on {ccode} — recording family recipe", flush=True)
                        record_family_recipe(ccode, "flag")

            # Endgame discipline (sapper doctrine): last quarter of the
            # run = reconcile captured-but-unsubmitted flags, stop new spawns.
            import re as _re_flag
            elapsed_total = time.time() - RUN_START
            if ENDGAME_AT and time.time() >= ENDGAME_AT:
                for line in open(f"{WORKSPACE}/runtime/blackboard.jsonl", encoding="utf-8").read().splitlines():
                    try:
                        f = json.loads(line)
                    except Exception:
                        continue
                    stmt = f.get("statement", "")
                    m = _re_flag.search(r"flag\{[a-zA-Z0-9_]{4,}\}", stmt)
                    if not m:
                        continue
                    flag = m.group(0)
                    if flag in ("flag{...}", "flag{}"):
                        continue
                    # find which code this flag belongs to
                    for ch in challenges:
                        ccode = ch["unique_code"]
                        if ccode in stmt and not ch.get("is_completed"):
                            if ccode not in submitted:
                                req = urllib.request.Request(
                                    BASE_URL + "/openapi/v1/challenges/submit",
                                    data=json.dumps({"unique_code": ccode, "flag": flag}).encode(),
                                    headers={"BENCHMARK_TOKEN": TOKEN, "Content-Type": "application/json"},
                                    method="POST")
                                try:
                                    with direct_open(req, timeout=30) as resp:
                                        body = json.loads(resp.read().decode())
                                        tag = "ACCEPTED" if body.get("correct") else "REJECTED"
                                        print(f"[orch] endgame submit {ccode} {flag[:36]} {tag}", flush=True)
                                        submitted.add(ccode)
                                except Exception as exc:
                                    print(f"[orch] endgame submit {ccode} failed: {exc}", flush=True)
                            break

            # Completion check.
            if all(c["is_completed"] for c in challenges):
                print("[orch] ALL CHALLENGES COMPLETE", flush=True)
                break
            time.sleep(POLL_S)
    finally:
        agent.terminate()
        try:
            agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            agent.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
