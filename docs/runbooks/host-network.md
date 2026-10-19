# Host network

**Alerts:** MacNetworkErrors

## What fired

`rate(node_network_receive_errs_total{device!~"lo0|utun.*|awdl.*|llw.*"}[15m]) > 1`
for 15 minutes.

Sustained receive errors on a real interface. The filter excludes loopback,
VPN tunnels and Apple Wireless Direct Link, which generate errors that mean
nothing.

## Likely causes, in order

1. **Wi-Fi interference.** The most common cause on this network, which runs
   three SSIDs on one subnet with a mix of 2.4 and 5 GHz devices.
2. **Weak signal**, from distance or obstruction.
3. **Channel congestion**, from neighbouring networks.
4. **A driver problem**, usually after a macOS update.
5. **Failing hardware**, on a cable or the adapter itself. Rare.

## Diagnosis

Which interface and how bad:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=increase(node_network_receive_errs_total[1h])'
    netstat -i

Signal quality, if it is Wi-Fi:

    /System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I
    system_profiler SPAirPortDataType | head -40

RSSI above -60 dBm is good, -70 is marginal, below -80 is poor. Noise should
be below -90.

Is it affecting anything measurable:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=changes(probe_success[6h])'
    ping -c 100 192.168.0.1 | tail -3

Packet loss to the gateway above about 1 percent is a real problem.

## Correlate with the probe data

This host also runs the blackbox probes, so network errors and probe flapping
should move together. If probes are flapping while errors stay at zero, the
problem is the remote devices rather than this host's link.

## Resolution

| Cause | Fix |
|---|---|
| Interference | Change the Wi-Fi channel on the router. 5 GHz is usually less congested |
| Weak signal | Move the device or the router. Nothing in software fixes this |
| Driver | `sudo ifconfig en1 down && sudo ifconfig en1 up`, then consider a reboot |
| Congestion | Check how many devices are on the same band |
| Hardware | Try a different cable or band to isolate it |

## Known false positives

- **Multicast-heavy home networks** produce a background level of errors from
  discovery protocols. Compare against the historical baseline rather than
  treating any non-zero value as a fault.
- **Waking from sleep** produces a brief error burst that is normal.

## Escalation

- **Errors with measurable packet loss and probes flapping:** the network is
  genuinely degraded, not just noisy.
- **Only this host affected while others are fine:** the adapter or its driver.
- **Everything affected:** the router or the ISP.
