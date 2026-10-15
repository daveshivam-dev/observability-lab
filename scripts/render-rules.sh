#!/bin/bash
# Renders config/prometheus/rules/*.yaml into a single ConfigMap manifest.
set -euo pipefail
cd "$(dirname "$0")/.."

out=manifests/14-prometheus-rules.yaml

{
  echo "apiVersion: v1"
  echo "kind: ConfigMap"
  echo "metadata:"
  echo "  name: prometheus-rules"
  echo "  namespace: observability"
  echo "  labels:"
  echo "    app.kubernetes.io/name: prometheus"
  echo "data:"
  for f in config/prometheus/rules/*.yaml; do
    echo "  $(basename "$f"): |"
    awk '{ if (length($0)) print "    " $0; else print "" }' "$f"
  done
} > "$out"

echo "Rendered ${out}"
