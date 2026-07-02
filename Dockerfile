FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SELF_CORRECTING_SERVICE_HOST=0.0.0.0 \
    SELF_CORRECTING_SERVICE_PORT=8000 \
    SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS=4096 \
    SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=10 \
    SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
    SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS=30 \
    SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS=10

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 agent

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir .

USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"

CMD ["self-correcting-agent-serve", "--host", "0.0.0.0", "--port", "8000"]
