#!/bin/bash
# Regenerates every generated ConfigMap manifest.
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/render-configmap.sh config/prometheus/prometheus.yml \
  prometheus-config prometheus.yml manifests/11-prometheus-config.yaml

./scripts/render-configmap.sh config/blackbox/blackbox.yml \
  blackbox-config blackbox.yml manifests/40-blackbox-configmap.yaml
