#!/bin/bash
# Regenerates the Prometheus ConfigMap from config/prometheus/prometheus.yml.
# That file is the source of truth: it is what promtool lints in CI.
# Blank lines are left unindented so the output has no trailing whitespace.
set -euo pipefail
cd "$(dirname "$0")/.."

{
  echo "apiVersion: v1"
  echo "kind: ConfigMap"
  echo "metadata:"
  echo "  name: prometheus-config"
  echo "  namespace: observability"
  echo "  labels:"
  echo "    app.kubernetes.io/name: prometheus"
  echo "data:"
  echo "  prometheus.yml: |"
  awk '{ if (length($0)) print "    " $0; else print "" }' config/prometheus/prometheus.yml
} > manifests/11-prometheus-config.yaml

echo "Rendered manifests/11-prometheus-config.yaml"
