# Screenshots

Evidence for the README. Every image was checked for sanitisation before
inclusion: private-range addresses only, no public IP, no MAC addresses, no
hostnames identifying the household.

| File | Shows | Use in |
|---|---|---|
| alerts-firing.png | Three alert groups with one alert firing in each | Alerting section |
| alerts-pending-and-firing.png | HostDiskFilling firing with its full annotation set, including the rendered runbook_url and the templated description | Alerting section, the stronger of the two |
| alertmanager-discovery.png | Prometheus has discovered Alertmanager, no dropped instances | Alerting section |
| probe-failures-24h.png | changes(probe_success[24h]) as a bar gauge: one device at 210 transitions against 0 for the TCP probe | Black box section |
| probe-metrics-available.png | The full probe metric surface the exporter publishes | Optional, more reference than evidence |

## Still worth capturing

- The Alertmanager webhook payload from `kubectl -n observability logs deploy/alertmanager-sink`, showing the rendered annotations and runbook link arriving at a receiver. Strongest single image in the repo and not yet taken as a clean screenshot.
- The homelab exporter dashboard, once imported.
- `homelab_device_present` showing an isolated device at 1 while blackbox cannot reach it. Take this from Grafana rather than the terminal: the terminal version in this chat had the device map with real MAC addresses on screen beside it.
