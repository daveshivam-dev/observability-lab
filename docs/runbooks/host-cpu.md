# Host CPU

**Alerts:** MacCPUSaturated, MacLoadHigh

## What fired

| Alert | Expression | for | Why |
|---|---|---|---|
| MacCPUSaturated | busy above 90 percent | 30m | A long `for` deliberately ignores builds and exports |
| MacLoadHigh | load5 above 2x core count | 15m | Threshold derived from `count(count by (cpu) (...))`, so it survives a hardware change |

## Load average is not CPU percent

Load is the number of runnable processes, so it must be read against the core
count. On a 10 core M4, a load of 5 is half capacity and a load of 20 is
genuinely saturated. That is why the rule computes the threshold rather than
hardcoding a number.

## Darwin has no iowait

On Linux, time blocked on disk shows as `iowait`. macOS does not report it, so
disk waits are hidden inside `system` time. High system time with low user
time on this host usually means IO, not computation. Check the disk latency
panel before concluding it is CPU.

## Diagnosis

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'

    top -o cpu -l 1 -n 15 | tail -18
    ps aux --sort=-%cpu | head -15
    uptime

Is one core pinned or all of them. The CPU per core panel answers this. A
single pinned core is a single-threaded process; all cores busy is real
saturation.

Is it actually disk:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=rate(node_disk_read_time_seconds_total[5m]) / clamp_min(rate(node_disk_reads_completed_total[5m]), 1)'

Check the kind cluster, which is a common cause on this machine:

    docker stats --no-stream
    kubectl top pods -A --sort-by=cpu

## Resolution

| Cause | Fix |
|---|---|
| A build, export or render | Nothing. This is the machine doing its job |
| Runaway process | Identify with `top`, then `kill -TERM`. Note what it was |
| Docker consuming everything | Lower the CPU allocation in Docker Desktop settings |
| Spotlight reindexing | `mdutil -s /` to check. It finishes on its own |
| A kind pod in a crash loop | `kubectl -n observability get pods` and look at restart counts |

## Known false positives

- **After a large file move or a cleanup**, Spotlight reindexes and can run hot
  for an hour.
- **Time Machine backups** produce sustained load.
- **The efficiency and performance cores on Apple Silicon** load unevenly by
  design. An uneven per-core panel is not a fault.

## Escalation

- **Sustained saturation with no identifiable process:** check for a kernel
  task consuming CPU, which usually points at a driver.
- **Recurring at a fixed time:** something scheduled. `launchctl list`.
- **High load with low CPU:** processes are blocked, not computing. Look at
  disk latency and memory pressure instead.
