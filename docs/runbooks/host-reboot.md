# Unexpected reboot

**Alerts:** MacHostRebooted

## What fired

`time() - node_boot_time_seconds < 600` for 1 minute. The host booted within
the last 10 minutes.

This is informational by design. It fires on every reboot, planned or not.
The question it exists to answer is whether you intended it.

## First question

**Was this reboot planned?** A software update, a manual restart or a shutdown
you performed. If so, close the alert and move on.

If not, something crashed, lost power, or was shut down by something other
than you.

## Diagnosis

What happened and when:

    last reboot | head -5
    uptime
    log show --predicate 'eventMessage contains "shutdown cause"' --last 24h | tail -20

Crash reports:

    ls -lt /Library/Logs/DiagnosticReports/*.panic 2>/dev/null | head -5
    ls -lt ~/Library/Logs/DiagnosticReports/ 2>/dev/null | head -10

Shutdown cause codes worth knowing: **5** is a clean shutdown, **3** is a hard
power loss, **-128** is an unknown kernel panic, **-62** is a watchdog timeout
(usually a driver), **-20** is a forced power button hold.

Was anything running hot before it:

    curl -sG 'http://localhost:9090/api/v1/query_range' \
      --data-urlencode 'query=node_memory_compressed_bytes' \
      --data-urlencode "start=$(date -u -v-2H +%s)" \
      --data-urlencode "end=$(date -u +%s)" --data-urlencode 'step=60' | head -c 400

With 6 hour retention you usually will not have history from before the crash.
That is a real limitation of `emptyDir` storage and worth noting.

## Related finding: the Windows host

The Windows machine on this network has a documented pattern worth comparing
against, because the investigation method transfers:

- **Eleven Event 41 crashes** between 12 September and 12 October
- **`volmgr` event 161 immediately before every one**, meaning crash dump
  creation failed, which is why no stop code was ever recorded
- The crashes **predated** the windows_exporter install by two days, so the
  monitoring agent was cleared as a cause on evidence rather than assumption

The lesson: when a machine crashes without a dump, fix the dump mechanism
first. Without it every crash is unexplainable, and you are guessing forever.

## Resolution

| Cause | Action |
|---|---|
| Planned | Nothing |
| Kernel panic with a report | Read the panic log. It names the offending kext |
| Power loss | Check the supply. A UPS if it recurs |
| Thermal | Check for dust and fan behaviour. macOS shuts down before damage |
| Watchdog timeout | A driver hung. Usually third-party kernel extensions |
| No dump, no cause | Fix dump collection first, then wait for the next one |

## Escalation

- **More than two unexplained reboots in a month:** this is a hardware or
  driver investigation, not a monitoring one.
- **Crashes cluster under load:** suspect thermal or power delivery.
- **Crashes with no dump:** nothing can be diagnosed until that is fixed.
