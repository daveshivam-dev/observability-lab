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
## D-009: Network segmentation limits what can be probed

The network runs three SSIDs on one subnet: a hidden main network, an IoT
network, and a guest network. Client isolation is enabled per device on the
router, and eight of the nine IoT devices have it applied.

Isolation stops client to client traffic, which is exactly what an ICMP or TCP
probe is. Those eight devices are therefore unreachable from the cluster and
cannot be probed, even though they sit in the same address range.

Options considered:

- Remove isolation from the devices to be monitored. Rejected: monitoring is a
  poor reason to weaken a security control.
- Run a second blackbox exporter inside the isolated segment and scrape it
  remotely. Correct at scale, rejected here as it needs additional hardware for
  a two hour session.
- Monitor from the router, which sees every segment. Rejected because the
  hardware does not support it, see D-011.

Decision: probe what the monitoring host can reach, and state the gap rather
than hide it. One IoT device is deliberately left unisolated so the probe set
includes a real embedded device. That mirrors how monitoring works in a
segmented production network: a narrow, documented exception for a trusted
observer rather than a hole in the boundary.

Isolation is confirmable rather than inferred. ARP still resolves the MAC for
an isolated device, because address resolution happens at layer 2 before the
router filters forwarding, while ICMP gets no reply. An ARP entry proves the
device is present on the segment; it does not prove it is reachable. That
distinguishes an isolated device from an absent one, which matters when
interpreting a failed probe.

Coverage is therefore the main segment plus one IoT device, not the whole
estate. Anyone reading a dashboard needs to know that, which is why it is
written here rather than assumed.

## D-010: NET_RAW granted to the blackbox exporter

Every other container in this repo drops all capabilities. The blackbox
exporter is the exception: it is granted `NET_RAW`.

ICMP requires raw sockets, and a process without `CAP_NET_RAW` cannot open
one. Without the capability the icmp module fails every probe with a
permissions error while the exporter itself stays healthy, which is a
misleading failure mode.

The alternative was to drop ICMP entirely and probe with `tcp_connect` against
a known open port. Rejected because several targets, including the embedded IoT
device, expose no open ports at all. ICMP is the only signal available for
them.

Everything else is retained: non-root user 65534, `allowPrivilegeEscalation:
false`, read only root filesystem, `seccompProfile: RuntimeDefault`, and all
other capabilities dropped. The exception is one capability, granted for a
stated reason, rather than a relaxed security context.

## D-011: SNMP dropped, the router does not support it

The original plan included `snmp-exporter` against the router, which would have
given a cross-segment view without traversing the isolation boundary.

The router is a TP-Link Archer AX53. It exposes no SNMP agent: there is no SNMP
section in the web administration interface, and `snmpwalk` against it times out
with both v1 and v2c using the default community string. TP-Link reserves SNMP
for its business and Omada product lines.

This is a hardware constraint rather than a configuration one, and it is worth
recording because it is a real limit of consumer equipment. A privileged
vantage point onto every network segment is not available at this price point.

Consequences:

- `snmp-exporter` is not deployed, and `config/snmp/` does not exist
- The isolated IoT devices have no monitoring route at all, see D-009
- Per interface traffic counters and the DHCP lease table are unavailable, so
  any later work needing that data has to source it from the router web
  interface instead

## D-012: Scrape interval sets the detection floor

The scrape interval is 15s and the ICMP probe timeout is 5s. An outage shorter
than roughly 30 seconds may produce one failed sample or none at all.

This was observed rather than assumed. During testing, one device flapped for
about 30 seconds and a deliberate outage lasted six minutes. At a 15 minute
graph range both appeared as near identical vertical lines, and only the
narrower range distinguished them.

Two consequences carried into the alerting work:

- Alert rules need a `for` clause long enough to survive a normal blip.
  Detection and alerting are separate thresholds.
- A device that is intermittently unreachable by design is a dashboard
  candidate, not a paging candidate. The test is whether a human would take
  action, and for a device that sleeps there is no action to take.

Shortening the scrape interval would lower the detection floor at the cost of
more samples, more storage and more load on the probed devices. Not worth it
here, where nothing depends on sub minute detection.
