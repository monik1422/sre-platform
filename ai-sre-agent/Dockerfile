# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Non-root, no bytecode surprises, unbuffered logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src:/app"

WORKDIR /app

RUN python -m venv /opt/venv
COPY requirements.txt .
RUN pip install --require-virtualenv -r requirements.txt

COPY src ./src
COPY temporal ./temporal
COPY pyproject.toml .

# Drop privileges.
RUN useradd --uid 65532 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 65532:65532

# Default: run the Temporal worker. The RCA Job/CronJob overrides the command.
ENTRYPOINT ["python", "-m", "temporal.worker"]
