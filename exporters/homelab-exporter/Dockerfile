# syntax=docker/dockerfile:1
#
# This image is built and scanned in CI, but on the current setup the
# exporter runs directly on the macOS host rather than in the cluster.
# See docs/decisions.md D-013: a container has its own network namespace and
# therefore its own ARP table, which contains cluster addresses rather than
# LAN devices. The image is useful on a Linux host on the monitored segment,
# run with --network=host.

FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# iproute2 provides `ip neigh`; coreutils provides `du`. Both are read-only
# operations, so no additional capabilities are required.
RUN apt-get update \
 && apt-get install -y --no-install-recommends iproute2 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=deps /install /usr/local
COPY main.py .

RUN useradd --system --uid 10001 --no-create-home exporter
USER 10001

EXPOSE 9220
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:9220/metrics')"

ENTRYPOINT ["python", "main.py"]
CMD ["--config", "/etc/homelab-exporter/devices.yaml"]
