# Sanitisation rules

This repo monitors a real home network. These rules apply to every commit,
every screenshot and every dashboard export.

## Never commit

- Public IP addresses, including in screenshots and dashboard JSON
- MAC addresses, in configs, metrics, labels or dashboards
- SSID, router model with firmware version, ISP name
- Hostnames identifying the household or its occupants
- Real device names from the network

## Use instead

- Generic labels: `mac-mini-01`, `workstation-01`, `iot-camera-01`, `router-01`
- Private range addresses only in committed config
- Real values through a gitignored `config/local/` directory

## Before every push

- Redact screenshots before adding them to `docs/images/`
- Check dashboard JSON exports, which embed queries containing labels
- Read `git diff --staged` once, looking for addresses and identifiers

## Before making the repo public

    git log -p | grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}'
    git log -p | grep -niE '([0-9a-f]{2}:){5}[0-9a-f]{2}'

Deleted secrets stay in history. If either search hits, the history needs
rewriting, not a follow-up commit.
