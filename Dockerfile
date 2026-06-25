# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Persisted chain data (SQLite by default).
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# Runs the P2P server + Orion monitoring loop.
ENTRYPOINT ["helix-node"]
