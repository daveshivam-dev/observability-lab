# Clock skew

**Alerts:** MacClockSkew

## What fired

`abs(node_time_seconds - time()) > 5` for 10 minutes. The host clock disagrees
with Prometheus by more than 5 seconds.

## Why this matters more than it looks

Clock drift breaks things in ways that never point at the clock:

- **TLS validation fails** on certificates that are valid, because the
  not-before or not-after check uses local time
- **Tokens expire early or appear not yet valid.** OAuth, JWT, Kerberos
- **Log correlation becomes impossible** across hosts
- **Prometheus rejects samples** that appear to be from the future
- **Scheduled jobs** run at the wrong time or twice

The symptoms look like authentication failures, certificate errors or
intermittent application bugs. Nobody suspects the clock.

## Diagnosis

    date
    sntp -sS time.apple.com
    systemsetup -getusingnetworktime
    systemsetup -getnetworktimeserver

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=node_time_seconds - time()'

A positive value means the host is ahead of Prometheus; negative means behind.

Check the direction of the problem. Prometheus runs in a container whose clock
comes from the Docker VM, so either side could be the one that drifted:

    docker run --rm alpine date -u
    date -u

## Resolution

| Cause | Fix |
|---|---|
| Network time disabled | `sudo systemsetup -setusingnetworktime on` |
| NTP server unreachable | `sudo systemsetup -setnetworktimeserver time.apple.com` |
| Drift after sleep | Usually self-corrects. Force with `sudo sntp -sS time.apple.com` |
| The Docker VM clock drifted | Restart Docker Desktop. The VM clock drifts across host sleep |
| Hardware RTC battery | Very rare on modern Macs. Suspect only if the clock resets on every boot |

## Known false positives

- **After waking from sleep**, both the host and the Docker VM can be briefly
  out of sync before NTP corrects. The 10 minute `for` clause covers most of
  this.
- **The Docker VM is the usual culprit**, not the Mac. Check both before
  changing time settings on the host.

## Escalation

- **Drift returns after correction:** NTP is not reaching a server. Check
  whether outbound UDP 123 is blocked.
- **Clock resets on every boot:** hardware, and worth a service appointment.
