# Software updates

**Alerts:** MacUpdatesPending, MacUpdateCheckStale

## What fired

| Alert | Expression | for | Severity |
|---|---|---|---|
| MacUpdatesPending | `node_custom_pending_updates > 0` | 24h | info |
| MacUpdateCheckStale | check older than 7 days | 1h | warning |

The 24 hour `for` clause is deliberate. Updates appear constantly and most are
not urgent. The alert only fires if they are being genuinely ignored.

**MacUpdateCheckStale is the more important of the two.** If the script stops
running, the pending count freezes at whatever it last reported. Zero pending
then looks identical to healthy, which is the worst kind of monitoring
failure: the dashboard is green because nothing is being measured.

## These metrics are not from node_exporter

No exporter reports pending macOS updates. Both metrics come from a textfile
collector script. If they show No data, the script is not set up.

The textfile collector itself is already enabled on this host. What is needed
is a directory, a script and a schedule.

## Diagnosis

Are the metrics arriving at all:

    curl -s localhost:9100/metrics | grep node_custom_
    curl -s localhost:9100/metrics | grep node_textfile_scrape_error

What the system actually reports:

    softwareupdate -l --no-scan
    softwareupdate --history | head -10

Is the collector configured:

    ps aux | grep node_exporter | grep -o 'collector.textfile.directory=[^ ]*'
    ls -la /Volumes/DD/portfolio/textfile/

## Setting up the exporter script

The directory lives on the external SSD, so the script must handle the drive
being unmounted. `node_textfile_scrape_error` going to 1 catches that case.

1. `mkdir -p /Volumes/DD/portfolio/textfile`
2. Add `--collector.textfile.directory=/Volumes/DD/portfolio/textfile` to the
   node_exporter launch arguments and restart it
3. Write the script, emitting `node_custom_pending_updates` and
   `node_custom_update_check_timestamp` with HELP and TYPE lines
4. **Write atomically.** Write to a `.tmp` file in the same directory then
   `mv` it into place. node_exporter reading a half-written file drops every
   metric in it
5. Schedule it every 30 minutes with launchd. Do not run it per scrape:
   `softwareupdate` is slow and contacts Apple's servers
6. Verify with the diagnosis commands above

## Resolution

| Alert | Action |
|---|---|
| MacUpdatesPending | Install the updates, or decide not to and note why. Security updates should not sit for weeks |
| MacUpdateCheckStale | Fix the script. Check the SSD is mounted, the script is scheduled, and the output file is being written |

## Known false positives

- **Major macOS version upgrades** show as pending indefinitely if you are
  deliberately not upgrading. Consider filtering those out of the count rather
  than living with a permanently firing alert.
- **The SSD being unmounted** makes both metrics stale. That is the textfile
  collector alert doing its job, not an update problem.

## Escalation

Rarely needed. Updates are a maintenance task, not an incident. The exception
is a security update addressing an actively exploited vulnerability, which
should be treated as urgent regardless of the alert severity.
