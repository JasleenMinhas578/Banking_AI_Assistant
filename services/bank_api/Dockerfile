# Bank API image. Built by `make up` (docker compose) from the repo root.
FROM python:3.12-slim

# uv installs the exact package versions pinned in uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Packages first: Docker caches this layer until pyproject.toml or uv.lock change,
# so editing code doesn't reinstall everything.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# Never run as root inside the container.
RUN useradd --create-home bank
USER bank

EXPOSE 8000

# Uses our own /health endpoint: 200 = ready, 503 = database unreachable.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
