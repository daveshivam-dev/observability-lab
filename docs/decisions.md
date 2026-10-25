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

| homelab-exporter | 0.1.0 (python:3.12-slim base) | yes | 2026-10-19 |

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

## D-013: The custom exporter runs on the host, not in the cluster

Every other component in this repo is deployed to Kubernetes. The homelab
exporter is not, and the reason is not convenience.

A container has its own network namespace, and therefore its own ARP table.
A pod's ARP table contains other pods and the cluster gateway. It contains
nothing about the LAN. An ARP-based presence exporter running in a pod would
start cleanly, report confidently, and be measuring the wrong network
entirely, which is worse than not running at all.

The same reasoning already applies to node_exporter and windows_exporter:
both report on a host, so both run on that host. This exporter joins them.

A Dockerfile is still written and can be built in CI. The image is correct for
a Linux host on the monitored segment run with `--network=host`, which is how
this would be deployed if the segment had one. Building it also keeps the
supply-chain scanning in the pipeline honest.

Deviation from the original plan: the spec called for
`manifests/50-iot-exporter-*.yaml`. No such manifest exists. What replaced it
is a scrape job pointing at `host.docker.internal:9220` and a launchd agent.

## D-014: Cardinality is bounded by the device map, not by what is on the network

The obvious implementation labels each series with the device's MAC address.
That is wrong twice over.

It creates an unbounded label. Every phone, every guest device, every
randomised MAC from a passing laptop becomes a permanent new time series.
Unbounded cardinality is the most common way people take down a Prometheus
server, and a home network with visitors generates new MACs continuously.

It also puts hardware identifiers into the metric store, into every dashboard
built on it, and into any exported dashboard JSON. `docs/sanitisation.md`
forbids committing MAC addresses, and a metric label is a worse place for one
than a config file.

The exporter therefore labels only devices present in a map it is given.
Anything else increments `homelab_arp_unmapped_devices` and creates no series.
The cardinality ceiling is the length of the map: a number chosen by a human
rather than discovered at runtime. One unit test asserts that no label value
anywhere in the registry looks like a MAC address.

That counter turned out to be useful in its own right. A rise means something
new joined the network, which nothing else in the stack reports.

The map lives in `config/local/devices.yaml`, which is gitignored.
`devices.example.yaml` is committed with placeholder addresses.

## D-015: Absence is represented explicitly

Two metrics exist only to make absence visible.

`homelab_device_present` emits a zero for every known device at startup,
before any collection runs. Without that, a device absent since the exporter
started would have no series at all, and `homelab_device_present == 0` could
never match. The alert would be permanently silent and permanently green.

`homelab_directory_present` exists so a missing directory does not report size
zero. The watched directories include paths on the external SSD. "The drive is
unmounted" and "the cache was cleaned up" produce the same number if size is
the only metric, and they call for opposite responses.

This is the same reasoning behind `absent()` in the exporter-down rules. In
Prometheus a thing that stops existing is invisible unless you arrange
otherwise, and silence reads as health.

## D-016: macOS Local Network privacy, and why an empty result is an error

Building this exporter surfaced a platform constraint worth recording.

On macOS 15 and later, reading the kernel neighbour table requires Local
Network permission, and that permission is granted **per binary**. Running
`arp -an` in Terminal returned 15 entries. The identical call made by
Homebrew's `python3` returned **exit code 0, no stderr, and zero bytes**.

That is the worst failure mode available. The command succeeded. There was no
error to catch, no non-zero exit, nothing in stderr. An exporter trusting that
result would report every device absent, the error counter would stay at zero,
and the dashboard would show a network with no devices on it: a confident,
precise, entirely wrong answer.

Two changes came out of it:

**The venv is built from `/usr/bin/python3`**, the system interpreter, which
has the permission. The launchd plist points at that venv. A service started
with the wrong interpreter would exhibit the same silent failure.

**An empty ARP table now raises rather than returning an empty list.** A live
network segment always contains at least a gateway, so zero entries is a
malfunction, not a finding. The exception is caught by the collector, which
increments `homelab_collector_errors_total`, so the failure becomes visible
instead of silent.

The general lesson is worth more than the specific fix: when a check can fail
in a way that looks like a healthy answer, the check has to distinguish the
two itself. Nothing downstream can.

## D-017: ARP is a cache of conversations, not an inventory

The first version of this exporter read the ARP table passively and would have
reported devices absent simply because nothing had spoken to them recently.
ARP entries expire after roughly twenty minutes of silence.

The exporter now sends one ICMP packet to each known address before reading
the table, from `prime_addresses` in the config. Isolated devices never reply,
and that does not matter: ARP resolution happens at layer 2, before the router
drops the forwarded packet, so the entry appears regardless.

That distinction is the whole premise of the exporter and it is directly
observable:

    $ arp -a | grep 192.168.0.48
    ? (192.168.0.48) at 00:00:5e:00:53:05 on en1 ifscope [ethernet]
    $ ping -c 2 192.168.0.48
    2 packets transmitted, 0 packets received, 100.0% packet loss

An ARP entry proves the device is on the segment. It does not prove it is
reachable. Monitoring built on the first fact works where monitoring built on
the second cannot.

## D-018: Multicast addresses are not devices

`homelab_arp_devices_total` initially counted `224.0.0.0/4` multicast groups
alongside real hosts, inflating the figure by a constant few on any network
running Bonjour or SSDP. `homelab_arp_unmapped_devices` had the same problem,
which would have left it permanently above zero and therefore useless as a
signal that something new had joined.

Both now exclude non-unicast addresses. The bug is worth recording because of
how it was found: a unit test asserting the unmapped count disagreed after the
filter was added. A metric that is wrong by a small constant looks entirely
plausible and can survive indefinitely without something mechanical checking
it.

## D-019: Checks run in CI from pinned container images

Every check in this repo was a manual step before pushing: the sanitisation
greps, `ruff` and `pytest`, `promtool`, and re-rendering ConfigMaps. Manual
steps are skipped exactly when they matter, late and in a hurry, and the
README already claimed the exporter image was built in CI before any CI
existed. `.github/workflows/ci.yml` now runs all of them on every push and
pull request.

The tools run from pinned container images (`prom/prometheus`,
`prom/alertmanager`, `kubeconform`, `trivy`) rather than marketplace
actions, for two reasons. The same command works on this Mac with Docker, so
a CI failure can be reproduced locally without guessing what an action does
internally. And a third-party action runs with the workflow's token, so
every one added is code to trust; the only actions used are GitHub's own
`checkout` and `setup-python`. The workflow token is read-only.

Two checks are deliberately narrower than they could be:

- `promtool check config` runs with `--syntax-only`. The full check resolves
  the Kubernetes service-account token path, which exists only inside the
  cluster.
- Trivy fails only on high or critical vulnerabilities that have a fix
  available. An unfixable CVE in the base image would block every build
  with nothing to do about it, which trains people to ignore the job.

The ConfigMap check re-renders every manifest and fails if `git diff` shows a
change. That turns "never edit a rendered ConfigMap directly" from a rule in
the README into something a pull request cannot get past.

## D-020: Hardening pass before sharing the repo

D-005 accepted a plain-text Grafana password only until the repo was
published. The repo went public before that happened, with the comment
promising the fix still sitting next to `admin/admin`. Fixed now:

- **Grafana credentials** come from a `grafana-admin` Secret created by
  `scripts/bootstrap-secrets.sh` with a random password. The Deployment reads
  it through `secretKeyRef`. Nothing credentialed is committed, and the
  script leaves an existing Secret alone so re-running it is safe.
- **A duplicate ConfigMap was removed.** `30-alertmanager-configmap.yaml` and
  `33-alertmanager-configmap.yaml` both defined `alertmanager-config`. Only
  33 is rendered by `render-all.sh` and covered by the CI drift check, so 30
  was an unchecked copy that would have silently lost to 33 the first time
  someone edited it.
- **The Prometheus ClusterRole lost `configmaps` and `ingresses`.** Nothing in
  `prometheus.yml` uses them: the service discovery roles are `endpoints`,
  `node` and `pod`. A read-only role is not the same as a minimal one.


`endpointslices` and `nodes/metrics` were removed alongside `configmaps` and
`ingresses`. The endpoints role reads the old Endpoints API, which the live
targets confirm by carrying `__meta_kubernetes_endpoint_*` labels;
`role: endpointslice` is a separate role nothing in `prometheus.yml` uses.
Node and cAdvisor metrics are scraped through the API server proxy, which
needs `nodes/proxy` rather than `nodes/metrics`. Both were removed, the
manifest reapplied and Prometheus restarted, and all 15 targets stayed up, so
neither was load-bearing. Prometheus does log that v1 Endpoints is deprecated
in 1.33+, so moving to `role: endpointslice` later means adding that
permission back.

## D-021: CI deploys the stack, not just the manifests

`kubeconform` proves a manifest matches its schema and `promtool` proves a
config parses. Neither proves the stack starts. This repo already shipped the
counterexample: `manifests/33-alertmanager-configmap.yaml` was never
committed, every schema check passed, and a fresh clone would have left
Alertmanager waiting on a ConfigMap that did not exist. A missing Secret, a
wrong image tag and a bad volume mount all fail the same way, as valid YAML
and a broken cluster.

The `deploy` job creates a kind cluster inside the runner, applies the
namespace, runs `scripts/bootstrap-secrets.sh`, applies every manifest and
waits for each Deployment to report Available. Running the bootstrap script
there, rather than inlining a `kubectl create secret` command, also tests that
the run order documented in the README is correct.

It then asserts four things that only a running stack can show: every
Deployment reaches Available, Prometheus serves `/-/ready`, more than zero
rule groups are loaded (which proves the mounted ConfigMap arrived), and both
`up{job="prometheus"}` is 1 and Alertmanager was discovered.

It deliberately does not assert a target count. The Mac, the Windows host and
the IoT devices do not exist on a GitHub runner, so those targets are
legitimately down there, and asserting 15 would fail every run for a reason
unrelated to the change under test.

kind is installed from a pinned release binary rather than a marketplace
action, for the reason already given in D-019.

The first run failed, and the failure is worth recording. The PromQL
assertion went into the URL unencoded, so the braces and quotes reached
Prometheus raw. It answered with an error object containing no `data` key,
and the parser tripped on that rather than on anything real. The fix was
`curl -G --data-urlencode`. The same trap is written down in the Session 2
notes from the first time it happened, which is a fair argument that a check
written down and never re-read is not a check.
