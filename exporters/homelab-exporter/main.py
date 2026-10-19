"""Homelab exporter.

Exports two things Prometheus cannot otherwise see on this network:

1. Presence of devices that client isolation makes unprobeable. ARP resolution
   happens at layer 2, before the router filters forwarding, so an isolated
   device still appears in the ARP table even though ICMP to it fails. That
   gives presence detection where blackbox probing cannot reach.

2. Directory sizes. node_exporter reports filesystem usage but has no concept
   of which directory is consuming it, so a single application cache can take
   half a disk without any metric moving until the volume alert fires.

Cardinality is bounded deliberately: devices are labelled by a name from a
map, never by MAC address. An unmapped device increments a counter rather
than creating a new series.
"""

from __future__ import annotations

import argparse
import logging
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Info,
    start_http_server,
)

log = logging.getLogger("homelab_exporter")

# macOS:  ? (192.168.0.1) at 00:00:5e:00:53:01 on en1 ifscope [ethernet]
# Linux:  192.168.0.1 dev eth0 lladdr 00:00:5e:00:53:01 REACHABLE
_MAC = r"[0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5}"
ARP_DARWIN = re.compile(rf"\((?P<ip>[\d.]+)\) at (?P<mac>{_MAC})", re.I)
ARP_LINUX = re.compile(rf"(?P<ip>[\d.]+) .*lladdr (?P<mac>{_MAC})", re.I)


@dataclass(frozen=True)
class Device:
    """A device we have chosen to track, keyed by MAC in the config file."""

    name: str
    type: str


class EmptyArpTable(RuntimeError):
    """Raised when arp succeeds but returns nothing.

    On macOS 15 and later, reading the neighbour table requires Local Network
    permission, granted per binary. A process without it gets exit code 0, no
    stderr and an empty table: success that reports nothing. Without this
    guard the exporter would confidently report every device absent and the
    error counter would stay at zero, which is the worst failure mode
    available. A live segment always has at least a gateway.
    """


@dataclass(frozen=True)
class ArpEntry:
    ip: str
    mac: str


def normalise_mac(mac: str) -> str:
    """Pad single-digit octets and lowercase.

    macOS prints 8:f1:b5:... where Linux prints 08:f1:b5:..., so the same
    device would otherwise fail to match the config map depending on platform.
    """
    return ":".join(part.zfill(2) for part in mac.lower().split(":"))


def parse_arp(output: str, system: str) -> list[ArpEntry]:
    pattern = ARP_LINUX if system == "Linux" else ARP_DARWIN
    seen: set[str] = set()
    entries: list[ArpEntry] = []
    for match in pattern.finditer(output):
        mac = normalise_mac(match.group("mac"))
        if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or mac in seen:
            continue
        seen.add(mac)
        entries.append(ArpEntry(ip=match.group("ip"), mac=mac))
    return entries


def prime_arp_cache(addresses: list[str], timeout: float = 2.0) -> None:
    """Send one packet to each address so the kernel resolves its MAC.

    The ARP table is a cache of recent conversations, not a device inventory.
    Entries expire after roughly 20 minutes of silence, so a passive read
    reports idle devices as absent. Priming makes the reading mean "is this
    device on the segment" rather than "has something talked to it lately".

    Isolated devices never answer the ping. That does not matter: ARP
    resolution happens at layer 2, before the router drops the forwarded
    packet, so the entry appears regardless.
    """
    procs = [
        subprocess.Popen(
            ["ping", "-c", "1", "-t", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for ip in addresses
    ]
    deadline = time.monotonic() + timeout
    for proc in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()


def read_arp_table(system: str | None = None, timeout: int = 10) -> list[ArpEntry]:
    system = system or platform.system()
    cmd = ["ip", "neigh", "show"] if system == "Linux" else ["arp", "-an"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=True
    )
    entries = parse_arp(result.stdout, system)
    if not entries:
        raise EmptyArpTable(
            f"{cmd[0]} exited 0 but returned no entries. On macOS this usually "
            "means the running binary lacks Local Network permission. See D-016."
        )
    return entries


def is_unicast(ip: str) -> bool:
    """Exclude multicast and broadcast from the device count.

    224.0.0.0/4 is multicast and 255.x is broadcast. Both appear in the ARP
    table as resolved entries, but neither is a device, and counting them
    makes the per-subnet totals wrong in a way that looks plausible.
    """
    try:
        first = int(ip.split(".")[0])
    except (ValueError, IndexError):
        return False
    return first < 224


def subnet_of(ip: str) -> str:
    """Return the /24 an address belongs to, as a bounded label value."""
    parts = ip.split(".")
    return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else "unknown"


def directory_size_bytes(path: Path, timeout: int = 120) -> int | None:
    """Size of a directory via du.

    du is used rather than walking in Python because it is an order of
    magnitude faster on directories with hundreds of thousands of files, which
    is the case this exporter exists to catch. Returns None when the path is
    absent, which is a normal state for a directory on a removable drive.
    """
    if not path.is_dir():
        return None
    try:
        result = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("du failed for %s: %s", path, exc)
        return None
    return int(result.stdout.split()[0]) * 1024


def load_config(path: Path) -> dict:
    with path.open() as handle:
        config = yaml.safe_load(handle) or {}
    devices = {
        normalise_mac(mac): Device(
            name=entry["name"], type=entry.get("type", "unknown")
        )
        for mac, entry in (config.get("devices") or {}).items()
    }
    directories = {
        name: Path(p).expanduser() for name, p in (config.get("directories") or {}).items()
    }
    # Addresses to prime before each read. Without these the exporter only
    # sees devices something else happened to talk to recently.
    prime = list(config.get("prime_addresses") or [])
    return {"devices": devices, "directories": directories, "prime": prime}


class Metrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        # Presence is a gauge rather than a counter because the question is
        # "is it here now", and every known device reports every cycle so a
        # device going away shows as 0 rather than a vanishing series.
        self.present = Gauge(
            "homelab_device_present",
            "1 when the device is in the ARP table, 0 when it is not.",
            ["device", "type"],
            registry=registry,
        )
        self.last_seen = Gauge(
            "homelab_device_last_seen_timestamp_seconds",
            "Unix time the device was last present in the ARP table.",
            ["device", "type"],
            registry=registry,
        )
        self.devices_total = Gauge(
            "homelab_arp_devices_total",
            "Count of distinct devices in the ARP table, per subnet.",
            ["subnet"],
            registry=registry,
        )
        # Unmapped devices are counted, never labelled. Labelling by MAC would
        # create an unbounded label and would put hardware identifiers into
        # the metric store, which the repo's sanitisation rules forbid.
        self.unmapped = Gauge(
            "homelab_arp_unmapped_devices",
            "Devices present in ARP but absent from the device map. A rise "
            "means something new joined the network.",
            registry=registry,
        )
        self.directory_size = Gauge(
            "homelab_directory_size_bytes",
            "Size of a watched directory in bytes.",
            ["name"],
            registry=registry,
        )
        self.directory_present = Gauge(
            "homelab_directory_present",
            "1 when the watched directory exists, 0 when it does not. A "
            "directory on a removable drive reports 0 while unmounted.",
            ["name"],
            registry=registry,
        )
        self.last_run = Gauge(
            "homelab_collector_last_run_timestamp_seconds",
            "Unix time of the last completed collection cycle.",
            registry=registry,
        )
        self.duration = Gauge(
            "homelab_collector_duration_seconds",
            "Duration of the last collection cycle.",
            ["collector"],
            registry=registry,
        )
        self.errors = Counter(
            "homelab_collector_errors_total",
            "Collection failures, by collector.",
            ["collector"],
            registry=registry,
        )
        self.build = Info(
            "homelab_exporter_build", "Exporter build information.", registry=registry
        )


class Collector:
    def __init__(self, config: dict, metrics: Metrics) -> None:
        self.devices: dict[str, Device] = config["devices"]
        self.directories: dict[str, Path] = config["directories"]
        self.prime: list[str] = config.get("prime", [])
        self.metrics = metrics
        self._seed_known_devices()

    def _seed_known_devices(self) -> None:
        """Emit every known device at zero before the first collection.

        Without this, a device that is absent at startup has no series at all,
        and an alert on `== 0` would never fire because there is nothing to
        compare. Absence has to be represented, not implied.
        """
        for device in self.devices.values():
            self.metrics.present.labels(device.name, device.type).set(0)

    def collect_arp(self) -> None:
        started = time.monotonic()
        try:
            if self.prime:
                prime_arp_cache(self.prime)
            entries = read_arp_table()
        except Exception:
            log.exception("ARP collection failed")
            self.metrics.errors.labels("arp").inc()
            return

        now = time.time()
        present_macs = {entry.mac for entry in entries}
        unmapped = 0
        per_subnet: dict[str, int] = {}

        for entry in entries:
            if not is_unicast(entry.ip):
                continue
            per_subnet[subnet_of(entry.ip)] = per_subnet.get(subnet_of(entry.ip), 0) + 1
            if entry.mac not in self.devices:
                unmapped += 1

        for mac, device in self.devices.items():
            is_present = mac in present_macs
            self.metrics.present.labels(device.name, device.type).set(int(is_present))
            if is_present:
                self.metrics.last_seen.labels(device.name, device.type).set(now)

        for subnet, count in per_subnet.items():
            self.metrics.devices_total.labels(subnet).set(count)

        self.metrics.unmapped.set(unmapped)
        self.metrics.duration.labels("arp").set(time.monotonic() - started)
        log.debug("arp: %d entries, %d unmapped", len(entries), unmapped)

    def collect_directories(self) -> None:
        started = time.monotonic()
        for name, path in self.directories.items():
            size = directory_size_bytes(path)
            if size is None:
                self.metrics.directory_present.labels(name).set(0)
                continue
            self.metrics.directory_present.labels(name).set(1)
            self.metrics.directory_size.labels(name).set(size)
        self.metrics.duration.labels("directory").set(time.monotonic() - started)

    def run_once(self, with_directories: bool = True) -> None:
        self.collect_arp()
        if with_directories:
            self.collect_directories()
        self.metrics.last_run.set(time.time())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9220)
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument(
        "--arp-interval",
        type=int,
        default=30,
        help="Seconds between ARP collections. Cheap, so this can be frequent.",
    )
    parser.add_argument(
        "--directory-interval",
        type=int,
        default=1800,
        help="Seconds between directory size collections. du over a large tree "
        "is expensive, so this is deliberately infrequent.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    try:
        config = load_config(args.config)
    except Exception:
        log.exception("could not load config from %s", args.config)
        return 1

    registry = CollectorRegistry()
    metrics = Metrics(registry)
    metrics.build.info({"version": "0.1.0", "platform": platform.system()})
    collector = Collector(config, metrics)

    log.info(
        "tracking %d devices and %d directories, listening on %s:%d",
        len(config["devices"]),
        len(config["directories"]),
        args.listen,
        args.port,
    )

    start_http_server(args.port, addr=args.listen, registry=registry)

    # Directory collection runs on its own slower schedule in a separate
    # thread so a slow du never delays or blocks ARP collection.
    def directory_loop() -> None:
        while True:
            collector.collect_directories()
            time.sleep(args.directory_interval)

    threading.Thread(target=directory_loop, daemon=True, name="directories").start()

    try:
        while True:
            collector.collect_arp()
            collector.metrics.last_run.set(time.time())
            time.sleep(args.arp_interval)
    except KeyboardInterrupt:
        log.info("shutting down")
        return 0


if __name__ == "__main__":
    sys.exit(main())
