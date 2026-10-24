#!/usr/bin/env python3
"""Fails if a tracked file contains a public IP address or a real MAC address.

Enforces docs/sanitisation.md mechanically. Runs in CI on every push and pull
request, and can be run locally before pushing:

    python3 scripts/check-sanitisation.py

Only the current tree is checked. History is covered by the one-off greps in
docs/sanitisation.md, which must be run before the repo is made public.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys

IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
MAC_RE = re.compile(r"(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])", re.I)

# Well-known public resolvers used as probe targets. They identify nothing
# about this network.
ALLOWED_PUBLIC_IPS = {"1.1.1.1", "8.8.8.8", "9.9.9.9"}

# RFC 7042 reserves 00:00:5e:00:53:00-ff for documentation. The others are
# broadcast, all-zero placeholders and an obviously fake test value.
ALLOWED_MAC_PREFIXES = ("00:00:5e:00:53:", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:", "de:ad:be:ef:")

# Screenshots are redacted by hand (see docs/sanitisation.md); binary files
# are not scanned.
SKIP_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif")


def ip_allowed(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return True  # not an address, e.g. a four-part version string
    if text in ALLOWED_PUBLIC_IPS:
        return True
    # Multicast groups (mDNS, SSDP) are protocol constants, not hosts.
    return ip.is_multicast or not ip.is_global


def mac_allowed(text: str) -> bool:
    return text.lower().startswith(ALLOWED_MAC_PREFIXES)


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if not f.lower().endswith(SKIP_SUFFIXES)]


def main() -> int:
    failures = []
    for path in tracked_files():
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for lineno, line in enumerate(lines, 1):
            for m in IP_RE.findall(line):
                if not ip_allowed(m):
                    failures.append(f"{path}:{lineno}: public IP {m}")
            for m in MAC_RE.findall(line):
                if not mac_allowed(m):
                    failures.append(f"{path}:{lineno}: MAC address {m}")

    if failures:
        print("Sanitisation check failed (see docs/sanitisation.md):")
        print("\n".join(failures))
        return 1
    print("Sanitisation check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
