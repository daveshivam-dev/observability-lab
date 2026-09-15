#!/bin/bash
# Renders a ConfigMap manifest from a plain config file.
# The config file is the source of truth: it is what promtool and friends lint.
# Usage: scripts/render-configmap.sh <source> <name> <key> <output>
set -euo pipefail
cd "$(dirname "$0")/.."

src="$1"; name="$2"; key="$3"; out="$4"
[[ -f "$src" ]] || { echo "missing source: $src" >&2; exit 1; }

{
  echo "apiVersion: v1"
  echo "kind: ConfigMap"
  echo "metadata:"
  echo "  name: ${name}"
  echo "  namespace: observability"
  echo "  labels:"
  echo "    app.kubernetes.io/name: ${name%-config}"
  echo "data:"
  echo "  ${key}: |"
  awk '{ if (length($0)) print "    " $0; else print "" }' "$src"
} > "$out"

echo "Rendered ${out} from ${src}"
