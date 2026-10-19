# Exporter and monitoring failures

**Alerts:** TargetDown, MacHostDown, MacCollectorFailing, MacTextfileCollectorError, BlackboxExporterDown, PrometheusRestarting

## Why these matter most

Every other alert in this stack depends on these working. A failed exporter
does not make the dashboard red, it makes it empty, and an empty dashboard
looks calm. This is the only alert family where silence is the symptom.

## What fired

| Alert | Expression | Means |
|---|---|---|
| TargetDown | `up == 0` for 5m | Prometheus cannot scrape a target |
| MacHostDown | `up{job="node-exporter-mac"} == 0` | No host metrics at all |
| MacCollectorFailing | `node_scrape_collector_success == 0` | One collector is silently empty |
| MacTextfileCollectorError | `node_textfile_scrape_error > 0` | A .prom file is unreadable |
| BlackboxExporterDown | `up == 0` **or** `absent(probe_success)` | No probes are running |
| PrometheusRestarting | more than 2 restarts in 30m | Prometheus itself is unstable |

## The absent() pattern

`BlackboxExporterDown` uses `or absent(probe_success)` for a specific reason.

When an exporter stops, its series do not go to zero. **They disappear.**
`up == 0` only fires if Prometheus still knows the target exists. If the
scrape job is removed, or the series ages out, nothing fires at all and every
device appears healthy by omission.

`absent()` is the only thing that catches that. Any alert whose absence would
be dangerous needs it. `TargetDown` does not have this protection, which is a
known gap: if someone deletes a scrape job, nothing alerts.

## Diagnosis

Which target and what error. This is the single most useful command here,
because health counts tell you something is wrong while `lastError` tells you
what:

    curl -s 'http://localhost:9090/api/v1/targets?state=active' \
      | python3 -c '
    import json,sys
    for t in json.load(sys.stdin)["data"]["activeTargets"]:
        if t["health"] != "up":
            print(t["labels"].get("job"), t["labels"].get("instance"), "|", t.get("lastError",""))'

Which collector:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=node_scrape_collector_success == 0'

Is the exporter alive on the host:

    curl -s --max-time 3 localhost:9100/metrics | head -3
    brew services list | grep node_exporter

Is the pod alive, for in-cluster exporters:

    kubectl -n observability get pods
    kubectl -n observability logs deploy/blackbox-exporter --tail=30
    kubectl -n observability describe pod <name> | sed -n '/Events/,$p'

Is Prometheus itself healthy:

    curl -s http://localhost:9090/-/healthy
    kubectl -n observability logs deploy/prometheus --tail=40
    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=prometheus_config_last_reload_successful'

That last one returning 0 means Prometheus is running on an older config than
the one on disk. A silent failure worth knowing about.

## Common causes

| Symptom | Usually |
|---|---|
| Target down, exporter reachable from the host | Pod cannot route to the host. Test from inside the cluster |
| Target down, connection refused | Nothing listening. The exporter stopped or the host is off |
| Target down, connection timeout | Firewall. On Windows, check the network profile is Private not Public |
| All collectors fine but one | That collector genuinely failed. `thermal` on this host is known to fail |
| Textfile error | A malformed .prom file, or the SSD is unmounted |
| Prometheus restarting | Memory limit, or a config error on reload |
| Config applied, nothing changed | ConfigMap applied without restarting the pod |

## The render, apply, restart cycle

Every config change in this repo follows the same sequence. Skipping the
restart is the single most common self-inflicted failure:

    ./scripts/render-all.sh
    kubectl apply -f manifests/
    kubectl -n observability rollout restart deploy/prometheus
    kubectl -n observability rollout status deploy/prometheus

Applying a ConfigMap does not restart the pods that mount it, and Prometheus
does not reread its config on its own. `rollout status` confirms an existing
rollout finished; it does not start one.

Alternative, since `--web.enable-lifecycle` is set:

    curl -X POST http://localhost:9090/-/reload

Faster, but it depends on the mounted ConfigMap having propagated, which can
take up to a minute. An immediate reload may silently apply the old config.

## Known false positives

- **`thermal` fails on this Mac** and emits nothing. It will keep
  MacCollectorFailing pending forever. Either disable the collector or exclude
  it from the rule.
- **Prometheus restarts reset every pending alert clock**, because pending
  state is in memory. After a restart, alerts that were nearly firing start
  their `for` clause again from zero.
- **`emptyDir` storage means a restart loses all history**, so a restart looks
  like a gap in every graph.

## Escalation

- **Monitoring is down and you cannot restore it quickly:** say so. An
  unmonitored system that everyone believes is monitored is worse than one
  nobody is watching.
- **Prometheus restarting repeatedly:** check the memory limit against actual
  usage. The container limit is 1Gi.
- **A target has been down for days:** either fix it or remove it. A
  permanently red dashboard teaches people to ignore red.
