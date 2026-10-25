#!/bin/bash
# Creates the Grafana admin Secret with a random password, if it does not
# already exist. No credential is ever committed (D-005, D-020).
# Run after the namespace exists and before applying the rest of manifests/.
set -euo pipefail

ns=observability
name=grafana-admin

if kubectl -n "$ns" get secret "$name" >/dev/null 2>&1; then
  echo "Secret ${ns}/${name} already exists, leaving it unchanged"
  exit 0
fi

kubectl -n "$ns" create secret generic "$name" \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$(openssl rand -base64 24)"

echo "Created ${ns}/${name}. Read the password with:"
echo "  kubectl -n ${ns} get secret ${name} -o jsonpath='{.data.admin-password}' | base64 -d; echo"
