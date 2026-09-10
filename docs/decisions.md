# Decisions

## ARM64 image verification

Host is an Apple Silicon Mac (M4, arm64). Every image is checked for a
`linux/arm64` variant before it enters a manifest:

```bash
docker buildx imagetools inspect prom/prometheus:v3.13.1 | grep -i 'linux/arm64'
docker buildx imagetools inspect grafana/grafana:12.4.4 | grep -i 'linux/arm64'
```

| Image | Tag | linux/arm64 | Verified on |
|---|---|---|---|
| prom/prometheus | v3.13.1 | yes | 2026-09-10 |
| grafana/grafana | 12.4.4 | yes | 2026-09-10 |
| kindest/node | v1.37.0 | yes | 2026-09-10 |

Fill in the result column after running the commands above. If an image has no
`linux/arm64` variant, record it below with the workaround chosen (alternative
image, `--platform linux/amd64` under emulation, or build from source) and the
cost of that workaround.

### Images without an arm64 variant

None so far.

## D-001: kind instead of k3d

kind runs each node as a container and supports multi-node clusters with a
single config file. It is also what most CI examples use, so the same config is
reusable in GitHub Actions later.

## D-002: NodePort instead of an ingress controller

The stack needs both UIs reachable from the host with the least moving parts.
kind `extraPortMappings` forwards host 9090 and 3000 to NodePorts 30090 and
30000 on the control plane node. NodePorts are open on every node, so it does
not matter which node the pods land on. An ingress controller can replace this
later without touching the Deployments.

## D-003: emptyDir instead of PersistentVolumeClaims

The cluster is disposable and recreated with one command. Prometheus retention
is set to 6h. Persistence would add a storage class and a restore story that
this stage does not need. Revisit if the lab starts holding data worth keeping.

## D-004: Prometheus RBAC is read-only and cluster-scoped

Service discovery for nodes, pods, services and endpoints needs cluster scope.
The ClusterRole grants only `get`, `list`, `watch`, plus `get` on `nodes/proxy`
for kubelet and cAdvisor scraping. No create, update, delete or patch anywhere.

## D-005: Grafana admin password in plain text

Acceptable only because the cluster is local and never exposed. Before the repo
is published, this moves to a Kubernetes Secret, and ideally to a Secret
generated at bootstrap time so no credential is committed.
