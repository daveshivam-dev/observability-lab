# Host memory

**Alerts:** MacMemoryPressure, MacSwapping, MacSwapFileGrowing, MacWiredMemoryHigh

## What fired

| Alert | Expression | for |
|---|---|---|
| MacMemoryPressure | `node_memory_compressed_bytes > 4e9` | 15m |
| MacSwapping | `rate(node_memory_swapped_out_bytes_total[15m]) > 1e6` | 15m |
| MacSwapFileGrowing | `node_memory_swap_total_bytes > 4e9` | 30m |
| MacWiredMemoryHigh | wired above half of physical RAM | 30m |

## Why these metrics and not "percent used"

On macOS a used-percent gauge reads 85 to 90 percent on a perfectly healthy
machine, because `free` excludes cache and the memory manager deliberately
keeps very little free. An alert on that number would fire permanently.

macOS relieves pressure in a specific order, and the alerts follow it:

1. **Compress** inactive pages in RAM. Cheap. `node_memory_compressed_bytes`
   rising is the earliest honest signal.
2. **Grow the swap file** on demand. `node_memory_swap_total_bytes` increasing
   is itself evidence of pressure.
3. **Swap out to disk.** `node_memory_swapped_out_bytes_total` climbing means
   compression was not enough.

So MacMemoryPressure fires before MacSwapping, by design.

## Memory categories, and what each means

| Metric | Meaning | Reclaimable |
|---|---|---|
| `wired` | Kernel and drivers | No. Sets a hard floor |
| `active` | In use by running applications | Under pressure |
| `inactive` | Recently used, still cached | Yes |
| `compressed` | Squeezed to fit | Already under pressure |
| `purgeable` | Can be discarded on demand | Yes |
| `internal` | Application memory | Depends on the application |

A steady climb in **internal** is an application leak. A steady climb in
**wired** is a kernel extension or driver leak, which is more serious.

## Diagnosis

Current state:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=node_memory_compressed_bytes'
    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=node_memory_swap_used_bytes'
    vm_stat
    memory_pressure

What is using it:

    ps aux --sort=-%mem | head -15
    top -o MEM -l 1 -n 15 | tail -18

Is it a leak or a spike. Look at the Memory breakdown panel over 6 hours: a
sawtooth is normal, a staircase that never comes down is a leak.

Docker is the usual suspect on this machine:

    docker stats --no-stream
    docker system df

## Resolution

| Cause | Fix |
|---|---|
| Docker Desktop over-allocated | Settings, Resources, lower the memory limit. 8 GB is the configured value |
| A single application leaking | Restart that application. Record which one and how fast it grows |
| Too many applications open | Normal pressure. Nothing to fix |
| Wired memory climbing | A kernel extension or driver. Reboot, then watch whether it climbs again from a clean start |
| Swap file large but no swap activity | Historical. macOS does not shrink the swap file. Not an active problem |

## Known false positives

- **A large build or an export** produces 15 to 30 minutes of pressure that
  resolves on its own. The 15 minute `for` clause tolerates most of these but
  not all.
- **Swap total stays large after pressure ends**, because macOS keeps the file
  it created. MacSwapFileGrowing can stay firing long after the cause is gone.
  Judge by MacSwapping, which uses a rate.

## Escalation

- **Pressure with no identifiable process:** likely a kernel or driver leak.
  Reboot and watch wired memory from a clean start.
- **Recurring daily at the same time:** something scheduled. Check
  `launchctl list` and cron.
- **Swapping heavily with a nearly full disk:** these compound. Swap needs disk
  space, and a full disk makes swapping fail. Fix the disk first.
