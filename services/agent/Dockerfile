# Agent + gateway + web app image. Built by `make up` from the repo root
# (the build context is the repo, so data/, ml/ and services/web are included).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /repo/services/agent
COPY services/agent/pyproject.toml services/agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/agent/app ./app
COPY services/web /repo/services/web
COPY data /repo/data
COPY ml/moderation_classifier/model /repo/ml/moderation_classifier/model

RUN useradd --create-home agent && mkdir -p /repo/traces && chown -R agent /repo
USER agent

EXPOSE 8200
CMD ["uvicorn", "app.gateway.main:app", "--host", "0.0.0.0", "--port", "8200"]
