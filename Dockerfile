# Ouroboros Agent — TSec Benchmark runner image
# Two layers:
#   1. ouro (static linux binary) — the security-workbench agent
#   2. tsec-benchmark SDK driver — orchestrates list/start/submit/close
#
# Runtime contract (all via env, nothing on disk):
#   BENCHMARK_BASE_URL  platform API base (e.g. https://benchmark.example.com)
#   BENCHMARK_TOKEN    task token (UUID) issued by the platform
#   OURO_PROVIDER_*    provider config for the agent's model calls
#   OURO_API_BIND      default 127.0.0.1 (loopback-only by design)
FROM python:3.12-slim
# python:3.12-slim ships ca-certificates; no apt layer (China-network
# Docker Hub pulls of deb.debian.org are unreliable — keep the image apt-free).
WORKDIR /agent


# Static Go binary cross-compiled on the host (no toolchain in image).
COPY docker-build/ouro-linux /agent/ouro
RUN chmod +x /agent/ouro

# Python driver with the official SDK.
COPY docker-build/pip-cache/ /tmp/wheels/
RUN pip install --no-index --find-links=/tmp/wheels tsec-benchmark

# Driver sources.
COPY benchmark/driver.py /agent/driver.py
COPY benchmark/agent_bridge.py /agent/agent_bridge.py

# official_prompt.txt not shipped in the standalone agent package
COPY benchmark/drive_autonomous.py /agent/drive_autonomous.py
COPY benchmark/drive_parent.py /agent/drive_parent.py
COPY benchmark/drive_orchestrated.py /agent/drive_orchestrated.py
COPY benchmark/drive_single.py /agent/drive_single.py
COPY benchmark/parallel_entry.py /agent/parallel_entry.py
# Workspace bootstrap: scope.yaml/providers.yaml are generated at runtime
# from env (URLs/keys never baked into the image).
COPY benchmark/bootstrap_workspace.py /agent/bootstrap_workspace.py

# Knowledge library: distilled recipe index (139KB) + full SKILL.md files.
COPY kb /agent/kb

# Workspace bootstrap: scope.yaml/providers.yaml are generated at runtime
# from env (URLs/keys never baked into the image).
COPY benchmark/bootstrap_workspace.py /agent/bootstrap_workspace.py

# Non-root.
RUN useradd -m agent && chown -R agent:agent /agent
USER agent

# Entrypoint: agent stays resident; the loop driver injects the official
# prompt and keeps the turn-based conversation going.
CMD ["python", "-u", "/agent/parallel_entry.py"]
