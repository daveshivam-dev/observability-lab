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

## D-006: Reaching host processes from inside the cluster

Two hosts, two different solutions, because they are two different problems.

**Mac (node_exporter on the host):** target is `host.docker.internal:9100`.
Each pod runs in its own network namespace, so `localhost` and `127.0.0.1`
resolve to the pod itself, not the machine the cluster runs on. A process
bound to port 9100 on the Mac is unreachable that way. Docker Desktop
provides `host.docker.internal` as a DNS alias for the host, which the kind
node container inherits.

Rejected alternative: the Mac's LAN IP, which also worked when tested. Chose
the DNS name because it survives DHCP reassignment, and because it states the
intent directly. A reader sees "the Docker host" rather than an IP address
they have to look up.

**Windows (windows_exporter):** target is the LAN IP `192.168.0.2:9182`.
`host.docker.internal` resolves specifically to the machine running Docker,
which is the Mac. The Windows box is a separate machine on the LAN, so it is
reached over the network like any other host.

Both routes were tested from inside the cluster with a throwaway busybox pod
before being committed.

**Risk:** the Windows target is a DHCP-assigned address. If the lease changes,
the scrape breaks silently and the only symptom is a target going down.
Mitigation: reserve the address on the router by MAC, so DHCP always hands out
the same one. A service-discovery mechanism would remove the static entry
entirely, but that is heavier than a two-host lab justifies.

## D-007: Exporter differences across operating systems

node_exporter on darwin exposes around 597 metrics against several thousand on
Linux. Most node_exporter collectors read from Linux-specific interfaces:
`/proc`, `/sys`, cgroups and systemd. macOS has none of these, so those
collectors are unavailable rather than merely empty.

Metric names do not match across exporters:

| Concept | darwin/Linux | Windows |
|---|---|---|
| Total memory | `node_memory_total_bytes` | `windows_memory_physical_total_bytes` |
| CPU time | `node_cpu_seconds_total` | `windows_cpu_time_total` |

Consequence for dashboards: a panel covering both hosts needs one query per
operating system, which does not scale as host types are added. The fix is
recording rules that map each exporter's metric onto a shared name, so panels
and alert rules query one series regardless of the underlying OS.

## D-008: Windows firewall profile

The inbound rule for TCP 9182 was scoped to the Private profile, but the Wi-Fi
connection was categorised as Public, so the rule never applied and the
traffic was dropped. Outbound still worked, which made the failure look
one-directional and misleading.

Fixed by setting the network category to Private. The Public profile is
designed for untrusted networks such as cafes and airports, where blocking
inbound connections and local discovery is the right default. On a home
network it blocks exactly the traffic this project depends on.