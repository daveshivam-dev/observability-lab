"""Unit tests for the homelab exporter.

Parsing and label logic are tested without touching the network or the
filesystem, so the suite runs in CI on any platform.
"""

from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

import main

DARWIN_ARP = """\
? (169.254.234.125) at 0:0:5e:0:53:2 on en1 [ethernet]
? (192.168.0.1) at 00:00:5e:00:53:01 on en1 ifscope [ethernet]
? (192.168.0.2) at 00:00:5e:00:53:02 on en1 ifscope [ethernet]
? (192.168.0.63) at 00:00:5e:00:53:03 on en1 ifscope [ethernet]
? (192.168.0.255) at ff:ff:ff:ff:ff:ff on en1 ifscope [ethernet]
mdns.mcast.net (224.0.0.251) at 1:0:5e:0:0:fb on en1 ifscope permanent [ethernet]
"""

LINUX_ARP = """\
192.168.0.1 dev eth0 lladdr 00:00:5e:00:53:01 REACHABLE
192.168.0.63 dev eth0 lladdr 00:00:5e:00:53:03 STALE
"""


def test_normalise_mac_pads_single_digit_octets():
    # macOS prints 8:f1:b5, Linux prints 08:f1:b5, for the same device.
    assert main.normalise_mac("0:0:5e:0:53:2") == "00:00:5e:00:53:02"
    assert main.normalise_mac("00:00:5E:00:53:02") == "00:00:5e:00:53:02"


def test_parse_darwin_drops_broadcast_and_duplicates():
    entries = main.parse_arp(DARWIN_ARP, "Darwin")
    macs = [e.mac for e in entries]
    assert "ff:ff:ff:ff:ff:ff" not in macs
    # The link-local entry and 192.168.0.2 are the same normalised MAC, so
    # the duplicate must be dropped rather than counted twice.
    assert macs.count("00:00:5e:00:53:02") == 1


def test_parse_linux():
    entries = main.parse_arp(LINUX_ARP, "Linux")
    assert len(entries) == 2
    assert entries[0].ip == "192.168.0.1"


@pytest.mark.parametrize(
    "ip,expected",
    [("192.168.0.63", "192.168.0.0/24"), ("10.244.1.4", "10.244.1.0/24"), ("x", "unknown")],
)
def test_subnet_of(ip, expected):
    assert main.subnet_of(ip) == expected


def _collector(tmp_path: Path, monkeypatch, arp_output: str):
    config_file = tmp_path / "devices.yaml"
    config_file.write_text(
        """
devices:
  "00:00:5e:00:53:01": {name: router-01, type: network}
  "00:00:5e:00:53:03": {name: iot-01, type: iot}
  "de:ad:be:ef:00:01": {name: absent-01, type: iot}
directories: {}
"""
    )
    monkeypatch.setattr(main, "read_arp_table", lambda: main.parse_arp(arp_output, "Darwin"))
    registry = CollectorRegistry()
    return main.Collector(main.load_config(config_file), main.Metrics(registry)), registry


def test_absent_device_reports_zero_rather_than_vanishing(tmp_path, monkeypatch):
    collector, registry = _collector(tmp_path, monkeypatch, DARWIN_ARP)
    collector.collect_arp()
    value = registry.get_sample_value(
        "homelab_device_present", {"device": "absent-01", "type": "iot"}
    )
    # The series must exist at 0. If it vanished, an alert on == 0 could
    # never fire, which is the silent-failure mode this guards against.
    assert value == 0.0


def test_present_device_reports_one(tmp_path, monkeypatch):
    collector, registry = _collector(tmp_path, monkeypatch, DARWIN_ARP)
    collector.collect_arp()
    assert registry.get_sample_value(
        "homelab_device_present", {"device": "iot-01", "type": "iot"}
    ) == 1.0


def test_unmapped_devices_are_counted_not_labelled(tmp_path, monkeypatch):
    collector, registry = _collector(tmp_path, monkeypatch, DARWIN_ARP)
    collector.collect_arp()
    # Only 00:00:5e:00:53:02. The mDNS multicast entry is excluded, because
    # "unmapped device" must mean an unrecognised device, not any unmapped
    # address. Counting multicast would make this metric read at least 1 on
    # every network running Bonjour, which would make it useless as a signal.
    assert registry.get_sample_value("homelab_arp_unmapped_devices") == 1.0
    # No metric anywhere may carry a MAC address as a label value.
    for metric in registry.collect():
        for sample in metric.samples:
            for value in sample.labels.values():
                assert ":" not in value or value.count(":") != 5


def test_collection_failure_increments_error_counter(tmp_path, monkeypatch):
    collector, registry = _collector(tmp_path, monkeypatch, DARWIN_ARP)

    def boom():
        raise OSError("arp unavailable")

    monkeypatch.setattr(main, "read_arp_table", boom)
    collector.collect_arp()
    assert registry.get_sample_value(
        "homelab_collector_errors_total", {"collector": "arp"}
    ) == 1.0


def test_missing_directory_reports_absent_not_zero_size(tmp_path):
    registry = CollectorRegistry()
    metrics = main.Metrics(registry)
    collector = main.Collector(
        {"devices": {}, "directories": {"gone": Path("/nonexistent/path")}}, metrics
    )
    collector.collect_directories()
    assert registry.get_sample_value("homelab_directory_present", {"name": "gone"}) == 0.0
    # Reporting size 0 for a missing directory would look like a successful
    # cleanup. Absence and emptiness are different states.
    assert registry.get_sample_value("homelab_directory_size_bytes", {"name": "gone"}) is None


def test_real_directory_is_measured(tmp_path):
    (tmp_path / "f").write_bytes(b"x" * 4096)
    registry = CollectorRegistry()
    collector = main.Collector(
        {"devices": {}, "directories": {"tmp": tmp_path}}, main.Metrics(registry)
    )
    collector.collect_directories()
    assert registry.get_sample_value("homelab_directory_present", {"name": "tmp"}) == 1.0
    assert registry.get_sample_value("homelab_directory_size_bytes", {"name": "tmp"}) > 0


def test_empty_arp_table_raises_rather_than_reporting_an_empty_network(monkeypatch):
    """A silent empty result must be an error, not a finding.

    macOS Local Network permission is granted per binary. Without it, arp
    exits 0 with no output, and an exporter that trusted that would report
    every device absent while the error counter stayed at zero.
    """

    class FakeResult:
        stdout = ""

    monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: FakeResult())
    with pytest.raises(main.EmptyArpTable):
        main.read_arp_table(system="Darwin")


def test_multicast_excluded_from_device_count(tmp_path, monkeypatch):
    collector, registry = _collector(tmp_path, monkeypatch, DARWIN_ARP)
    collector.collect_arp()
    # 224.0.0.251 is mDNS multicast, not a device on the network.
    assert registry.get_sample_value(
        "homelab_arp_devices_total", {"subnet": "224.0.0.0/24"}
    ) is None
