# Runbooks

One page per alert family. Every `runbook_url` annotation in
`config/prometheus/rules/` resolves to a file here.

## Format

Each runbook answers four questions in the same order:

1. **What fired and what it means.** The expression, the threshold, and why
   that threshold.
2. **Likely causes**, ordered by how often they are the cause rather than by
   how serious they are.
3. **Diagnosis.** Commands to run, in the order that eliminates the most
   possibilities soonest.
4. **Resolution and escalation.** What to do, and when to stop and get help.

## Rules for writing one

- Commands must be copy-pasteable. A runbook that needs interpretation at 3am
  is not a runbook.
- Say what a healthy result looks like, not just what to run.
- Name the false positives. An alert that cries wolf teaches people to ignore
  it, and the runbook is where you record that.
- If the fix is always the same, automate it and delete the runbook.

## Index

| Runbook | Alerts |
|---|---|
| [device-unreachable](device-unreachable.md) | RouterUnreachable, HostUnreachable, InternetConnectivityLost, ProbeLatencyHigh |
| [host-disk](host-disk.md) | MacDiskFilling, MacDiskCritical, MacDiskWillFill, MacExternalDiskMissing, MacExternalDiskFilling, MacVolumeReadOnly, MacFilesystemDeviceError, MacDiskHardwareErrors, MacDiskRetriesRising, MacDiskLatencyHigh, MacInodesLow, WindowsDiskFilling |
| [host-memory](host-memory.md) | MacMemoryPressure, MacSwapping, MacSwapFileGrowing, MacWiredMemoryHigh |
| [host-cpu](host-cpu.md) | MacCPUSaturated, MacLoadHigh |
| [host-network](host-network.md) | MacNetworkErrors |
| [host-clock](host-clock.md) | MacClockSkew |
| [host-reboot](host-reboot.md) | MacHostRebooted |
| [host-updates](host-updates.md) | MacUpdatesPending, MacUpdateCheckStale |
| [exporter-down](exporter-down.md) | TargetDown, MacHostDown, MacCollectorFailing, MacTextfileCollectorError, BlackboxExporterDown, PrometheusRestarting |
