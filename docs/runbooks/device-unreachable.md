# Device unreachable

**Alerts:** RouterUnreachable, HostUnreachable, InternetConnectivityLost, ProbeLatencyHigh

## What fired

A blackbox probe returned `probe_success == 0` for longer than the alert's
`for` clause. The probe runs from inside the cluster, not from the Mac, so
"unreachable" means unreachable from a pod.

| Alert | Expression | for | Why that threshold |
|---|---|---|---|
| RouterUnreachable | `probe_success{instance="192.168.0.1"} == 0` | 2m | Everything downstream depends on the gateway, so detection is fast |
| HostUnreachable | `probe_success{job="blackbox-tcp"} == 0` | 5m | A host rebooting should not page anyone |
| InternetConnectivityLost | external down **and** router up | 2m | The `and` separates a WAN failure from a local one |
| ProbeLatencyHigh | `probe_duration_seconds > 1` | 10m | Informational. Wi-Fi power saving produces spikes |

## Read the control targets first

This is the fastest diagnostic available and it takes one glance at the
Network overview dashboard.

| Pattern | Means |
|---|---|
| One device down, `1.1.1.1` and the router up | The device failed |
| Everything down including both controls | Your network, the exporter, or Prometheus |
| External controls down, router and local devices up | The WAN link or the ISP |
| Everything up but latency high | Congestion or Wi-Fi power saving, not an outage |

## Likely causes, in order

1. **The device is off or asleep.** Battery devices sleep their radio. Check
   the flap counter before assuming a fault.
2. **DHCP reassigned the address.** The target is a static IP in the scrape
   config. A new lease breaks the probe silently while the device is fine.
3. **Client isolation on the router.** Eight IoT devices are isolated by
   design and cannot be probed. See D-009.
4. **Wi-Fi interference or a weak signal**, which presents as flapping rather
   than a clean outage.
5. **The blackbox exporter itself**, in which case every probe fails together.

## Diagnosis

Confirm whether this is one target or all of them:

    curl -sG 'http://localhost:9090/api/v1/query' --data-urlencode 'query=probe_success' \
      | python3 -c '
    import json,sys
    for r in json.load(sys.stdin)["data"]["result"]:
        print("  %-40s %s" % (r["metric"]["instance"], r["value"][1]))'

Get the actual error rather than the symptom:

    curl -s 'http://localhost:9090/api/v1/targets?state=active' \
      | python3 -c '
    import json,sys
    for t in json.load(sys.stdin)["data"]["activeTargets"]:
        if t["health"] != "up":
            print(t["labels"].get("job"), t["labels"].get("instance"), "|", t.get("lastError",""))'

Test from the Mac. If the Mac can reach it but the pod cannot, the problem is
routing, not the device:

    ping -c 3 <ip>
    nc -vz -w 3 <ip> <port>

Test from inside the cluster, which is where the probe actually runs:

    kubectl -n observability run nettest --rm -it --image=busybox:1.36 --restart=Never -- \
      sh -c 'wget -qO- --timeout=5 http://<ip>:<port>/ | head -3'

Has the address changed:

    arp -a | grep -i '<mac prefix>'
    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=changes(probe_ip_addr_hash[6h])'

Is it flapping rather than down:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=changes(probe_success[24h])'

## Known false positives

- **`192.168.0.63`** is an embedded Tuya device that transitions roughly 200
  times a day. It is excluded from paging for that reason. A single probe
  failure there means nothing.
- **A 30 second gap** is indistinguishable from a real outage at a 15 minute
  graph range. Narrow the range before drawing a conclusion.
- **The scrape interval is 15s** and the ICMP timeout 5s, so outages shorter
  than roughly 30 seconds may produce one failed sample or none.

## Resolution

| Cause | Fix |
|---|---|
| Device off | Nothing. Confirm it was intentional |
| Address changed | Update `config/prometheus/prometheus.yml`, render, apply, restart. Then reserve the address on the router |
| Client isolation | Expected. Do not remove the control to satisfy monitoring |
| Exporter failing | See [exporter-down](exporter-down.md) |
| Router down | Power cycle. If it recurs, check for overheating or a failing power supply |

## Escalation

- **Router down and will not recover:** this is the household's internet. Not
  a monitoring problem any more.
- **Everything down including the controls:** check Docker and the cluster
  before touching the network.
- **Repeated unexplained flapping on one device:** record the pattern in
  `docs/decisions.md` and decide whether it belongs in alerting at all.
