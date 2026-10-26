# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 silverpool \
    && useradd --system --uid 10001 --gid silverpool --home-dir /nonexistent --shell /usr/sbin/nologin silverpool

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt

COPY src /app/src
COPY deploy/pool/wait-for-node.py /app/wait-for-node.py
COPY deploy/pool/entrypoint.sh /usr/local/bin/silver-pool-entrypoint

RUN chmod 0755 /usr/local/bin/silver-pool-entrypoint \
    && mkdir -p /data \
    && chown -R silverpool:silverpool /app /data

USER 10001:10001

EXPOSE 8765 3333

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).read()"]

ENTRYPOINT ["/usr/local/bin/silver-pool-entrypoint"]
CMD ["python", "-m", "btcs_pool.server"]
