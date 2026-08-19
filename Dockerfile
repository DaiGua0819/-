FROM mcr.microsoft.com/playwright/python:v1.54.0-noble AS builder

WORKDIR /build
RUN python -m pip install --no-cache-dir uv==0.7.20 \
    && uv venv /opt/venv --python python

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --python /opt/venv/bin/python . \
    && uv pip install --python /opt/venv/bin/python \
        mypy==1.17.1 \
        pytest==8.4.1 \
        pytest-asyncio==1.1.0 \
        ruff==0.12.8

FROM mcr.microsoft.com/playwright/python:v1.54.0-noble AS runtime

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        postgresql-16 \
        redis-server \
        supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin xvi \
    && mkdir -p \
        /data/postgres \
        /data/redis \
        /data/profiles \
        /data/artifacts \
        /data/assets \
        /data/feishu-cli \
    && chown -R xvi:xvi /data /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=xvi:xvi pyproject.toml ./pyproject.toml
COPY --chown=xvi:xvi src ./src
COPY --chown=xvi:xvi apps ./apps
COPY --chown=xvi:xvi tests ./tests
COPY --chown=xvi:xvi scripts ./scripts
COPY --chown=xvi:xvi config.yml ./config.yml
COPY --chown=xvi:xvi configs ./configs
COPY --chown=xvi:xvi docker/single-container ./docker/single-container

RUN chmod 0755 /app/docker/single-container/entrypoint.sh \
    && rm -f /etc/supervisor/supervisord.conf \
    && ln -s /app/docker/single-container/supervisord.conf /etc/supervisor/supervisord.conf \
    && chown -R xvi:xvi /app/docker/single-container

USER xvi
EXPOSE 8000
ENTRYPOINT ["/app/docker/single-container/entrypoint.sh"]
