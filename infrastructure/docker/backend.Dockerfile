# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM ghcr.io/astral-sh/uv:0.12.5-python3.12-trixie@sha256:64165e61dd5fed90daa14ba2d17cdb5a49964837ff85431a3b8199d7a9aa98c0 AS build
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps/backend/pyproject.toml apps/backend/pyproject.toml
COPY workers/agent-worker/pyproject.toml workers/agent-worker/pyproject.toml
COPY workers/knowledge-worker/pyproject.toml workers/knowledge-worker/pyproject.toml
COPY workers/outbound-worker/pyproject.toml workers/outbound-worker/pyproject.toml
COPY workers/scheduler/pyproject.toml workers/scheduler/pyproject.toml
RUN uv sync --locked --all-packages --no-dev
COPY apps/backend/src apps/backend/src
COPY workers workers
COPY evals evals

FROM python:3.12.11-slim-trixie@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/ZuvelAI/agents-factory" \
    org.opencontainers.image.revision="$SOURCE_REVISION" \
    org.opencontainers.image.title="Agents Factory backend and workers"
ENV PATH=/workspace/.venv/bin:$PATH \
    PYTHONPATH=/workspace/apps/backend/src:/workspace/workers/agent-worker/src:/workspace/workers/knowledge-worker/src:/workspace/workers/outbound-worker/src:/workspace/workers/scheduler/src:/workspace \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system agents && useradd --system --gid agents --home /nonexistent agents
WORKDIR /workspace
COPY --from=build --chown=agents:agents /workspace/.venv /workspace/.venv
COPY --from=build --chown=agents:agents /workspace/apps/backend/src /workspace/apps/backend/src
COPY --from=build --chown=agents:agents /workspace/workers /workspace/workers
COPY --from=build --chown=agents:agents /workspace/evals /workspace/evals
USER agents:agents
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["uvicorn", "agents_factory.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
