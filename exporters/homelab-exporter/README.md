# Homelab exporter

A Prometheus exporter for two things nothing else in this stack can see.

## Why it exists

**Isolated devices.** Eight IoT devices on this network have client isolation
enabled on the router. Blackbox cannot probe them: ICMP is dropped. But ARP
resolution happens at layer 2, before the router filters forwarding, so those
devices still appear in the ARP table. Presence detection works where probing
does not.

The distinction is observable:

    $ arp -a | grep 192.168.0.48
    ? (192.168.0.48) at 00:00:5e:00:53:04 on en1 ifscope [ethernet]
    $ ping -c 2 192.168.0.48
    2 packets transmitted, 0 packets received, 100.0% packet loss

An ARP entry proves the device is on the segment. It does not prove it is
reachable. That gap is what this exporter fills.

**Directory sizes.** node_exporter reports filesystem usage but has no concept
of which directory is consuming it. In October 2026 a single application cache
reached 127 GB, 55 percent of the disk, with no metric moving until the volume
alert fired at 85 percent. Documented in `docs/runbooks/host-disk.md`.

## Metrics

| Metric | Type | Labels | Notes |
|---|---|---|---|
| `homelab_device_present` | gauge | device, type | 1 or 0. Every known device reports every cycle |
| `homelab_device_last_seen_timestamp_seconds` | gauge | device, type | Only updated when present |
| `homelab_arp_devices_total` | gauge | subnet | Distinct devices per /24 |
| `homelab_arp_unmapped_devices` | gauge | none | Devices seen but not in the map |
| `homelab_directory_size_bytes` | gauge | name | Not emitted when the directory is absent |
| `homelab_directory_present` | gauge | name | Distinguishes absent from empty |
| `homelab_collector_last_run_timestamp_seconds` | gauge | none | Staleness detection |
| `homelab_collector_duration_seconds` | gauge | collector | |
| `homelab_collector_errors_total` | counter | collector | |

## Three design decisions worth defending

**Cardinality is bounded by construction.** Devices are labelled by a name
from a config file, never by MAC address. A MAC label would be unbounded, and
it would put hardware identifiers into the metric store, which
`docs/sanitisation.md` forbids. An unmapped device increments
`homelab_arp_unmapped_devices` and creates no series. That counter is also a
useful signal in its own right: a rise means something new joined the network.

**Absence is represented, not implied.** Every known device emits a series at
startup, set to 0. Without that, a device absent since boot would have no
series at all, and an alert on `== 0` could never fire. The same reasoning
drives `homelab_directory_present`: a missing directory reports absent rather
than size 0, because "the drive is unmounted" and "the directory was cleaned
up" are different states that must not look identical.

**The two collectors run on different schedules in different threads.** ARP is
cheap and runs every 30 seconds. `du` over a tree with 300,000 files takes
tens of seconds, so it runs every 30 minutes. Sharing one loop would make
every ARP sample as slow as the slowest `du`.

## Configuration

    cp devices.example.yaml ../../config/local/devices.yaml

`config/local/` is gitignored. The real file contains MAC addresses; the
committed example contains placeholders.

Find the MACs to fill in:

    arp -an | grep -v 'ff:ff:ff' | grep '192.168'

## Running

On the host, which is where it belongs (see below):

    python3 main.py --config ../../config/local/devices.yaml --listen 127.0.0.1

As a launchd service:

    mkdir -p /Volumes/DD/portfolio/logs
    cp com.homelab.exporter.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.homelab.exporter.plist
    curl -s localhost:9220/metrics | grep homelab_

## Why it does not run in the cluster

A container has its own network namespace and therefore its own ARP table,
containing cluster addresses rather than LAN devices. Running this in a pod
would produce an exporter that reports confidently on the wrong network.

The Dockerfile exists and is built in CI, because the image is correct for a
Linux host on the monitored segment running with `--network=host`. On this
setup the exporter runs on the Mac alongside node_exporter, and Prometheus
scrapes it through `host.docker.internal`, exactly as it scrapes node_exporter.

Recorded as D-013 in `docs/decisions.md`.

## Tests

    pip install -r requirements-dev.txt
    pytest -q
    ruff check .

Twelve tests covering MAC normalisation across platforms, ARP parsing for both
macOS and Linux output, broadcast and duplicate filtering, the absence-is-zero
guarantee, the cardinality guarantee (asserting no label value anywhere looks
like a MAC address), error counting, and the absent-versus-empty distinction
for directories.

None of them touch the network or require a specific platform.
