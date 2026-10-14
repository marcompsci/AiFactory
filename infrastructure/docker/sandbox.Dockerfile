# Image for DockerSandbox (AICIV_SANDBOX=docker): what agents' tools run inside.
#   docker build -f infrastructure/docker/sandbox.Dockerfile -t aiciv-sandbox:latest .
# Only python -m pytest / compileall and a fixed set of git subcommands are ever invoked (services/tools/sandbox.py).
# Containers start with --network none --read-only --cap-drop ALL and the worker's uid, so nothing here needs root.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "pytest>=9.1,<10"
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_INPUT=1
WORKDIR /tmp
