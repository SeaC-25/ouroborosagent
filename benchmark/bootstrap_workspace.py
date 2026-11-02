"""bootstrap_workspace.py — generate the agent workspace from env vars.

Everything externally observable comes from the environment (AGENTS.md rule):
provider URLs/keys, scope targets, benchmark coordinates. The workspace is
created fresh under /agent/workspace at container start; nothing is baked
into the image.
"""
import os
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("OURO_WORKSPACE", "/agent/workspace"))


def write_providers() -> None:
    """providers.yaml: one active provider, URL and key fully env-driven.

    base_url_env / api_key_env name the variables the agent reads at call
    time — the yaml carries only variable NAMES, never values.
    """
    name = os.environ.get("OURO_PROVIDER_NAME", "benchmark-provider")
    model = os.environ.get("OURO_PROVIDER_MODEL", "")
    base_env = os.environ.get("OURO_PROVIDER_BASE_URL_ENV", "OURO_PROVIDER_BASE_URL")
    key_env = os.environ.get("OURO_PROVIDER_KEY_ENV", "OURO_PROVIDER_API_KEY")
    timeout_ms = os.environ.get("OURO_PROVIDER_TIMEOUT_MS", "120000")
    if not model:
        sys.exit("OURO_PROVIDER_MODEL is required (e.g. glm-5.3)")
    if not os.environ.get(base_env):
        sys.exit(f"{base_env} is required (provider base URL via env)")
    if not os.environ.get(key_env):
        sys.exit(f"{key_env} is required (provider api key via env)")

    yaml = f"""version: 1
providers:
    - name: {name}
      type: openai_compatible
      model: {model}
      base_url_env: {base_env}
      api_key_env: {key_env}
      timeout_ms: {timeout_ms}
      context_window_tokens: 131072
      capabilities:
        - chat
        - code
        - reasoning
      enabled: true
"""
    (WORKSPACE / "providers.yaml").write_text(yaml, encoding="utf-8")


def write_scope(targets: list[str]) -> None:
    """scope.yaml: enforce policy; challenge targets are injected per-round
    by the driver (start_challenge returns their addresses)."""
    lines = ["version: 1", "scope:", "  target_policy: enforce", "  targets:"]
    if targets:
        lines += [f"    - kind: url\n      value: {t}" for t in targets]
    else:
        lines.append("    []")
    lines += ["  exclusions: []", "execution:", "  isolation: process"]
    (WORKSPACE / "scope.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "runtime").mkdir(exist_ok=True)
    (WORKSPACE / "replay").mkdir(exist_ok=True)
    write_providers()
    # Benchmark mode: challenge container IPs are platform-assigned, so the
    # scope gate is disabled by operator decision (the driver writes the
    # matching authorization.yaml for the safety gate).
    (WORKSPACE / "scope.yaml").write_text(
        "version: 1\nscope:\n  target_policy: disabled\n  targets: []\n"
        "  exclusions: []\nexecution:\n  isolation: process\n",
        encoding="utf-8")
    print(f"workspace ready at {WORKSPACE}", flush=True)


if __name__ == "__main__":
    main()
