# Host disk

**Alerts:** MacDiskFilling, MacDiskCritical, MacDiskWillFill, MacExternalDiskMissing, MacExternalDiskFilling, MacVolumeReadOnly, MacFilesystemDeviceError, MacDiskHardwareErrors, MacDiskRetriesRising, MacDiskLatencyHigh, MacInodesLow, WindowsDiskFilling

## What fired

| Alert | Threshold | Urgency |
|---|---|---|
| MacDiskFilling | above 85 percent for 10m | Plan a cleanup |
| MacDiskCritical | above 93 percent for 5m | Act now. macOS fails writes near full |
| MacDiskWillFill | predicted full within 24h | Act today |
| MacExternalDiskMissing | the SSD is no longer mounted | The repo, tooling and Docker image live there |
| MacVolumeReadOnly | a volume remounted read only | APFS does this on detecting corruption |
| MacDiskHardwareErrors | any read or write error in 1h | Back up first, investigate second |
| MacDiskRetriesRising | over 100 retries in 1h | Earliest warning of a failing drive |
| MacInodesLow | under 10 percent inodes free | Millions of small files |

## Important: APFS containers share space

`/`, `/System/Volumes/Preboot`, `/System/Volumes/Update`,
`/System/Volumes/VM` and `/System/Volumes/Data` are five volumes in one
container, all reporting the same 228 GB and the same free space.

Every filesystem rule is scoped to
`mountpoint=~"/System/Volumes/Data|/Volumes/.+"` for that reason. Without the
scope, one condition produces five alerts. If you add a rule, scope it the
same way.

`/System/Volumes/Data/home` is a zero-size automount map. Any percentage
calculation against it divides by zero.

## Likely causes, in order

1. **An application cache with no upper bound.** Messaging apps, browsers,
   Docker, Xcode derived data. See the known incident below.
2. **A second user account.** `/Users/sirius` holds 81 GB on this machine, a
   third of the disk.
3. **The Docker disk image**, which grows and never shrinks on its own.
4. **Large applications.** Final Cut, iMovie, Motion and Logic total roughly
   17 GB, plus their content libraries elsewhere.
5. **Time Machine local snapshots**, which pin blocks of deleted files.
6. **iOS device backups**, 10 to 40 GB each.

## Diagnosis

Where it stands:

    df -h /System/Volumes/Data
    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=100 * (1 - node_filesystem_avail_bytes{mountpoint=~"/System/Volumes/Data|/Volumes/.+"} / node_filesystem_size_bytes{mountpoint=~"/System/Volumes/Data|/Volumes/.+"})'

Top down, one level at a time. Do not jump to conclusions from the first
level:

    sudo du -xh -d1 /System/Volumes/Data 2>/dev/null | sort -rh | head -10
    sudo du -xh -d1 /Users 2>/dev/null | sort -rh
    du -sh ~/Library/* 2>/dev/null | sort -rh | head -10
    sudo du -xh -d1 /Applications 2>/dev/null | sort -rh | head -10

Space that is not real:

    du -sh ~/.Trash
    tmutil listlocalsnapshots /
    lsof +L1 2>/dev/null | head        # deleted files still held open

Purgeable space explains why Finder and `df` disagree:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=node_filesystem_purgeable_bytes'

Hardware, if an error or retry alert fired:

    curl -sG 'http://localhost:9090/api/v1/query' \
      --data-urlencode 'query=increase(node_disk_read_errors_total[24h])'
    diskutil verifyVolume /System/Volumes/Data

## Known incident: WhatsApp Desktop, October 2026

**Symptom.** MacDiskFilling fired at 85 percent and kept climbing to 91.9.

**Cause.** `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared`
held **127 GB** across 304,968 files, 55 percent of the whole disk.

**Why.** WhatsApp Desktop is a full independent client, not a mirror of the
phone. Multi-device means each device keeps its own complete copy. End to end
encryption means there is no server-side archive to fetch on demand. Media
auto-download is on by default and nothing ever cleans up.

**Misleading detail.** WhatsApp's own Manage Storage screen reported
**1.13 GB** against 127 GB on disk. Do not trust an application's own
accounting of its storage.

**Resolution.** Unlinked the device from the phone first, then removed the app
and its container. The phone keeps everything, so no data was lost.

**Prevention.** Settings, Storage and Data, Media auto-download set to Never
for all four types. Without that the problem returns.

**Monitoring gap this exposed.** node_exporter has no concept of directory
size, so a single folder consuming half the disk is invisible until the volume
alert fires. Closed with a textfile collector script exporting
`node_custom_directory_size_bytes`, and an alert at 30 GB.

## Resolution by alert

| Alert | Action |
|---|---|
| MacDiskFilling | Run the diagnosis above, find the largest reclaimable item, clear it |
| MacDiskCritical | Free something immediately. Empty Trash, clear caches, delete the largest unused app. Investigate afterwards |
| MacDiskWillFill | Find what is growing: compare `du` output against yesterday |
| MacExternalDiskMissing | Remount the SSD. Nothing in the repo works without it, and the Docker disk image lives there |
| MacVolumeReadOnly | Stop. Back up what you can reach, then `diskutil verifyVolume`. This usually precedes a failure |
| MacDiskHardwareErrors | Back up first. Then `diskutil verifyVolume` and check the drive's SMART status |
| MacInodesLow | `find <path> -xdev -type f \| wc -l` per directory to locate the file count |

## Escalation

- **Read only volume or hardware errors:** stop using the machine for anything
  that writes, back up immediately, and treat the drive as suspect.
- **A second user's account is the cause:** that is a household conversation,
  not a technical one. Do not delete another person's data.
- **The disk stays above 85 percent after every reasonable cleanup:** this is a
  capacity finding, not an incident. 228 GB is small for two accounts plus a
  container runtime. Record it and plan for external storage.
