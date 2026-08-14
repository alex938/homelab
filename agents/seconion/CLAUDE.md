# CLAUDE.md — Security Onion Technician Runbook

## Mission

You are the technician responsible for keeping this Security Onion standalone deployment healthy, available, and recoverable.

Your primary objective is to ensure Security Onion is running smoothly, with special attention to the recurring Elasticsearch/Lucene corruption fault documented below.

Operate conservatively. Prefer reversible, verified changes. Never claim a fix is complete until you have checked the resulting system state.

## Environment

- Security Onion deployment: standalone stack
- Guest type: KVM/QEMU VM
- Security Onion host: alex@192.168.2.73
- SSH password: stored in `.env`
- Elasticsearch heap target: 3072m
- Kernel swappiness target: vm.swappiness=1
- Elasticsearch heap locking target: bootstrap.memory_lock: true
- Elasticsearch snapshot repository: so_backup
- SLM policy: daily-snapshots
- Nightly snapshot time: approximately 02:30
- Snapshot retention: 7 days

Never copy the password from `.env` into this file, logs, command output, chat responses, shell history, or source control.

When connecting, load credentials from `.env` only as needed and avoid echoing secrets.

### `.env` format

`.env` uses colon-separated `key: value` lines (`host: ...`, `password: ...`) — it is **not** `KEY=VALUE` format. Do not parse it by splitting on `=`; that silently fails to redact on this format and can dump the raw password into terminal/tool output. Extract a field with a colon-aware parser, e.g. `awk -F': ' '/^password:/{print $2}' .env`, and pipe the result directly into the auth mechanism (e.g. `sshpass -f`) rather than assigning it to a variable that might get echoed, logged, or printed.

## Operational Tooling Notes (for faster future fixes)

These are the concrete commands verified to work on this host as of 2026-08-14.

**SSH + sudo, non-interactively, without leaking the password.** The sudo password is the same as the SSH login password. Login uses `sshpass -f` with a process-substituted colon-aware extraction; sudo reads the same password from the remote command's stdin via `-S`:

```
awk -F': ' '/^password:/{print $2}' .env | sshpass -f <(awk -F': ' '/^password:/{print $2}' .env) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash -c "<commands>"'
```

For anything longer than a couple of lines, avoid nested-quoting pain by writing the script to a remote temp file first (plain SSH, no sudo needed for `/tmp`), then executing it as root in a second connection:

```
sshpass -f <(awk -F': ' '/^password:/{print $2}' .env) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'cat > /tmp/fix.sh' <<'EOF'
#!/bin/bash
set -e
<commands>
EOF

awk -F': ' '/^password:/{print $2}' .env | sshpass -f <(awk -F': ' '/^password:/{print $2}' .env) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash /tmp/fix.sh'
```

Remove the temp script from `/tmp` after use.

**Querying/mutating Elasticsearch.** Use Security Onion's own wrapper, run as root — it handles auth and TLS itself:

```
sudo so-elasticsearch-query <path> [-X <METHOD>] [-d '<json-body>']
```

Do not pass an extra `-H "Content-Type: ..."` — the tool sets its own and a duplicate header causes a `media_type_header_exception`. Examples used during the 2026-08-14 fix: `_cluster/health?pretty`, `_cat/shards?h=index,shard,prirep,state,unassigned.reason`, `_cluster/allocation/explain -X POST -d '{...}'`, `_cat/snapshots/so_backup?v&s=start_epoch:desc`, `_snapshot/so_backup/<name>/_restore?wait_for_completion=true -X POST -d '{...}'`, `_data_stream/_modify -X POST -d '{...}'`.

## Critical Recurring Incident: Elasticsearch Lucene Checksum Corruption

### User-visible symptom

Every few days the Elasticsearch cluster has historically entered RED status, causing the SOC alerts dashboard to become unavailable.

The usual Elasticsearch symptom is an unassigned primary shard with `ALLOCATION_FAILED` and a Lucene corruption error similar to:

```
CorruptIndexException
checksum failed (hardware problem?) : expected=9052a566 actual=f93af994
```

A corrupt write index can also stall ingestion for the affected data stream.

### Corrected root-cause assessment

Do not assume that swapping by itself corrupts Lucene data.

Earlier notes attributed the issue primarily to memory pressure causing mmap-backed Lucene pages to be swapped and later corrupted. That explanation was incomplete and overstated.

The important facts are:

- The VM is memory-constrained and previously experienced substantial swap activity.
- Elasticsearch originally used a 5174m heap plus significant direct/off-heap memory, for a total footprint of roughly 7.7 GB.
- The heap was reduced to 3072m and vm.swappiness was reduced from 30 to 1.
- Corruption recurred after those changes, affecting three separate indices on Aug 2 and Aug 3, with repeated corrupt_index_exception / checksum mismatch errors.
- Swapping clean page cache on healthy hardware should not silently alter bytes.
- Repeated checksum failures strongly point to bad data somewhere in the RAM or storage path, especially when Lucene itself reports "hardware problem?".
- This system is a KVM/QEMU guest using an emulated QEMU HARDDISK; the guest cannot directly inspect the physical host's DIMMs or disk health.

### Current working diagnosis

Treat the remaining underlying cause as a likely host-side hardware or storage integrity problem until disproven.

Most important suspects:

- physical host RAM / DIMM errors;
- host storage errors;
- storage controller or I/O path corruption;
- less likely, a guest-side software issue not yet identified.

Memory pressure is still operationally important because this Security Onion standalone deployment is tight on RAM, but it is not sufficient by itself to explain silent checksum corruption on healthy hardware.

## Verified Fixes Already Applied

These changes are considered current baseline unless live verification proves otherwise.

### 1. Elasticsearch heap reduced

Changed `esheap: 5174m` to `esheap: 3072m`.

Salt pillar location: `/opt/so/saltstack/local/pillar/minions/so_standalone.sls`

Applied with: `sudo salt-call state.apply elasticsearch`

Purpose:
- reduce Elasticsearch's memory footprint;
- leave more RAM for the OS page cache and the rest of the Security Onion stack.

### 2. Kernel swappiness reduced

Persistent target: `vm.swappiness=1`

Configured via: `/etc/sysctl.d/99-elasticsearch.conf`

Verify with: `sysctl vm.swappiness` — expected: `vm.swappiness = 1`

### 3. Elasticsearch memory locking enabled

Added to the Salt-managed Elasticsearch configuration: `bootstrap.memory_lock: true`

The configuration was added under the Elasticsearch config section in: `/opt/so/saltstack/local/pillar/minions/so_standalone.sls`

A backup existed at the time of the change: `so_standalone.sls.bak-20260806093754`

Applied with: `sudo salt-call state.apply elasticsearch`

Verified outcomes at the time of the fix:
- setting rendered into elasticsearch.yml;
- Elasticsearch reported `mlockall = true`;
- Elasticsearch heap is pinned in RAM and cannot be swapped.

This was intentionally chosen instead of immediately disabling swap because the VM was too memory-constrained for a safe swapoff.

### 4. Snapshot policy made resilient

Snapshots were already configured. Earlier documentation claiming otherwise was incorrect.

- Repository: `so_backup`
- SLM policy: `daily-snapshots`

The policy was changed to allow partial snapshots: `"partial": true`

Reason: a corrupt/unassigned shard had been causing nightly snapshots to fail completely. With partial snapshots enabled, one bad shard should not prevent all other healthy shards from being backed up.

At the time of the fix, snapshot history showed approximately 5 failed, 1 successful. A fresh manual snapshot was then taken successfully: `daily-snap-2026.08.06-...ikfa` — result: SUCCESS, 226/226 shards, 0 failures.

The normal daily policy runs around 02:30 with 7-day retention.

### 5. Corrupted indices were restored from snapshot

During the major recurrence:
- three corrupt indices were recovered from `daily-snap-2026.08.01`;
- restore result was 3/3 shards with 0 failures;
- the cluster returned to GREEN;
- there were 0 unassigned shards;
- all shards were STARTED.

The `logs-soc-so` data stream required special handling because its corrupt backing index was also the active write index.

Recovery sequence used:
1. roll over the data stream first so a healthy write index exists;
2. restore the corrupt historical backing index from the known-good snapshot;
3. re-attach the restored SOC backing index to its data stream if required;
4. verify ingestion resumed;
5. verify cluster health is GREEN.

Do not simply delete a corrupt index until snapshot recovery options have been checked.

### 6. Recurrence resolved — 2026-08-14

Cluster was found RED with 2 unassigned primary shards, both `CorruptIndexException: checksum failed (hardware problem?)`:

- `.ds-logs-soc-so-2026.08.06-000078` — the active **write index** of the `logs-soc-so` data stream (failed 2026-08-08T22:29Z). This is the same recurring pattern as fix #5 above.
- `elastalert_error` — a plain (non-data-stream) index (failed 2026-08-07T01:47Z). **New: this is the first time a standalone, non-data-stream index has been hit.**

Side effect confirmed for the first time: the corrupt `logs-soc-so` write index **stalled SOC ingestion for ~6 days** (last doc before the fix was timestamped 2026-08-08T23:29Z, i.e. ingestion had been silently stuck since shortly after the corruption occurred, not just "ingestion may stall" as a hypothetical). Daily snapshots had also been running `PARTIAL` (not `SUCCESS`) every day since 2026-08-07 because of these same 2 shards — `daily-snap-2026.08.06-...-ikfa` (2026-08-06) was the last fully-clean snapshot and was confirmed to contain good copies of both affected indices before it was used.

Fix applied (mechanically identical to #5 for the data-stream index; a simpler variant for the standalone index):

1. `POST logs-soc-so/_rollover` — protects ingestion by creating `.ds-logs-soc-so-2026.08.14-000082` as the new write index.
2. `DELETE .ds-logs-soc-so-2026.08.06-000078` — deleting a non-write backing index directly auto-detaches it from the data stream.
3. `POST _snapshot/so_backup/daily-snap-2026.08.06-.../_restore` with `{"indices":".ds-logs-soc-so-2026.08.06-000078"}` — restores it as a standalone index.
4. `POST _data_stream/_modify` with `add_backing_index` action — re-attaches the restored index to `logs-soc-so`.
5. For `elastalert_error` (no data stream involved, so no rollover/reattach needed): `DELETE elastalert_error`, then restore the same way from the same snapshot.
6. Verified: cluster GREEN, 243/243 active shards, 0 unassigned. Took a fresh manual recovery snapshot `post-repair-2026.08.14-165422` — SUCCESS, 223/223 shards, 0 failures.

Open item from 2026-08-14 fix, resolved same day: `logs-soc-so` ingestion was re-checked later on 2026-08-14 and had caught up to real time (latest doc `@timestamp` 2026-08-14T17:04:35Z, checked at ~17:05Z) — the multi-day backlog drain completed. No further action needed.

### 7. Routine health check — 2026-08-14 (post-fix-#6 verification)

Performed the full Incident Response / Routine Health Check procedure to confirm fix #6 held and look for any recurrence. Findings:

- Cluster health: GREEN, 244/244 active primary shards, 0 unassigned (up from 243 baseline immediately after fix #6, consistent with normal index churn).
- `logs-soc-so` ingestion confirmed caught up to real time (see above) — closes the prior open item.
- Elasticsearch heap confirmed at runtime: `heap_max_in_bytes = 3221225472` = 3072m. `bootstrap.memory_lock = true` confirmed via node settings. `vm.swappiness = 1` confirmed.
- Disk usage 74% (118.2GB/157.9GB used, 39.6GB avail) — not near the 90%/95% allocation watermarks.
- SLM daily snapshots: every scheduled 02:30 run from 2026-08-07 through 2026-08-14 was `PARTIAL` (2 shards failed each time) — this is expected and already explained by fix #6: those runs all occurred *before* the 16:54 repair that day. `last_success` in the SLM policy still shows `daily-snap-2026.08.06-...-ikfa`. The next scheduled run (~02:30 on 2026-08-15) should be the first to return to full `SUCCESS` now that the cluster is GREEN — **verify this at the next session**.
- rasdaemon: active/running, zero errors in Memory, MCE, PCIe AER, Extlog, devlink, disk — no change from prior baseline, no new hardware evidence.
- No OOM events in the last 7 days (`journalctl -k`). `vmstat 1 5` showed a stable, non-growing swap-in/swap-out pattern. Swap usage steady at ~2.7GB used / 5.3GB free out of 8GB — consistent with the known memory-constrained baseline, not worsening.
- No new corrupt_index_exception, checksum failures, MCE, or disk I/O errors found in kernel/journal logs for the prior 24h–7d. **No recurrence of the Lucene corruption issue as of this check.**

**New, previously undocumented finding — elastalert segfaults (not yet root-caused, no fix applied):**

The `so-elastalert` container (image `so-elastalert:2.4.160`) has a Python interpreter (`libpython3.13.so.1.0`) segfaulting repeatedly — confirmed 11 occurrences over the 2026-08-11 through 2026-08-14 window via `journalctl -k`, most recently 2026-08-14 13:50 UTC. Every crash is at the *same* offset in the library (`+0x1600e4`), which points to a deterministic bug in a specific code path rather than random memory corruption — this looks unrelated to the Elasticsearch/hardware corruption issue (rasdaemon and cluster health show no correlated hardware signal). The container itself stays up (`docker inspect` shows `RestartCount: 0`, status `running`); `elastalert_status` documents show rules continuing to execute on their normal ~10-minute cadence through and after the crash times, so a subprocess/worker appears to be crashing and getting respawned without killing the main container process. However, the most recent actual alert in the `elastalert` index is dated 2026-07-17 — about four weeks stale as of this check — and it is not yet established whether that gap is benign (no rule matches) or a symptom of the crash pattern silently dropping alerts. No change was made: this doesn't match the documented corruption incident, and CLAUDE.md's change-management rules call for identifying a failure mode from evidence before acting. Root-causing this (e.g. checking for a known Python 3.13 / elastalert bug, correlating crash times with specific rules, checking for a newer image) is an **open item for a future session**.

## rasdaemon Hardware Error Monitoring

rasdaemon has been installed/configured and was verified active.

### Expected service state

`active (running)`, enabled at boot.

Previously verified process: `/usr/sbin/rasdaemon -f -r`

### Verified trace monitoring

The rasdaemon trace instance was confirmed to have the following enabled:

```
instances/rasdaemon/events/mce/mce_record/enable = 1
ras/mc_event/enable = 1
```

It was also verified to hold open per-CPU trace_pipe_raw handles across all 8 guest CPUs.

Event classes being recorded included: mce_record, mc_event, aer_event, extlog, devlink, disk_errors.

### Baseline at last verification

Zero recorded errors in: Memory, MCE, PCIe AER, Extlog, devlink, disk.

Check current state with:
```
sudo systemctl status rasdaemon --no-pager
sudo ras-mc-ctl --summary
sudo ras-mc-ctl --errors
```

### Important limitation

This VM does not have guest-visible EDAC memory-controller support.

`ras-mc-ctl --status` previously reported relevant drivers not loaded.

Therefore:
- per-DIMM ECC counters generally will not be available inside this VM;
- a failing physical DIMM on the hypervisor may not appear to the guest;
- guest-side rasdaemon only captures errors the hypervisor exposes to the VM.

Host-side testing remains mandatory to close the hardware question.

## Incident Response Procedure

Use this whenever the SOC dashboard becomes unavailable, Elasticsearch is RED, ingestion appears stalled, snapshots begin failing, or Lucene reports checksum corruption.

### 1. Establish current cluster health

Check: cluster health; unassigned shards; failed shard allocation explanations; current data-stream write indices; whether ingestion is still progressing; recent Elasticsearch logs.

The key questions are:
- Is there an unassigned primary shard?
- Does allocation explain show `corrupt_index_exception`, `CorruptIndexException`, or checksum failure?
- Is the corrupt index the active write index of a data stream?
- Does a known-good snapshot contain that index?

### 2. Protect current writes first

If the corrupt index is the current write index for a data stream, roll over the data stream before restore/delete operations.

This is especially important for `logs-soc-so`, because SOC logging can stall when its write index is corrupt.

After rollover, verify the new write index is accepting documents.

### 3. Inspect snapshots before deleting anything

Check the `so_backup` repository and the `daily-snapshots` history.

Find the newest snapshot from before corruption that contains the affected index.

Prefer restore over deletion whenever a good snapshot exists.

### 4. Restore the corrupt index

Typical safe flow:
1. record affected index name and data stream;
2. ensure it is no longer the active write index;
3. remove/close the unusable local copy only as required by Elasticsearch restore semantics;
4. restore the index from the latest known-good snapshot;
5. if needed, re-attach the restored backing index to the original data stream;
6. wait for shard recovery;
7. verify all restored shards are STARTED.

### 5. Verify full recovery

Do not stop at "restore completed". Confirm all of the following:
- cluster status = GREEN
- unassigned shards = 0
- all expected primary shards = STARTED
- SOC ingestion = advancing
- SOC alerts dashboard = functional
- latest snapshot policy = healthy or intentionally partial

Also inspect logs for fresh corruption after recovery.

### 6. Create a new recovery point

After recovery, trigger or verify a fresh snapshot so the system has a clean post-repair restore point.

Confirm the snapshot reports success and record: snapshot name; date/time; shard count; failures, if any.

## Routine Health Checks

When asked to "check Security Onion", "make sure it is healthy", or equivalent, perform at least the following.

### Elasticsearch

Verify:
- cluster health is GREEN;
- zero unassigned shards;
- no recent corrupt_index_exception or checksum failures;
- no shard allocation loops;
- Elasticsearch is running with the expected heap;
- memory locking is active;
- disk watermarks are not being approached;
- data streams have valid write indices;
- document counts/timestamps indicate ingestion is advancing.

Expected configuration:
```
esheap = 3072m
bootstrap.memory_lock = true
mlockall = true
vm.swappiness = 1
```

### Snapshots

Verify:
- repository `so_backup` is reachable;
- `daily-snapshots` policy is enabled;
- policy has `partial: true`;
- latest scheduled snapshot ran;
- snapshot result is healthy enough to provide a usable recovery point;
- retention remains approximately 7 days.

A cluster issue that also breaks backups is higher priority than a cluster issue alone.

### System memory

Check:
```
free -h
swapon --show
vmstat 1 5
```

Watch for: very low available RAM; increasing swap usage; sustained swap-in/swap-out; OOM events; Elasticsearch memory-lock failures.

Do not run `swapoff` casually on this VM. Previous measurements showed the machine had only about 2.4 GiB available while about 2.4 GiB was already in swap. Disabling swap in that condition could trigger the OOM killer.

### Hardware/error signals

Check:
```
sudo ras-mc-ctl --summary
sudo ras-mc-ctl --errors
sudo journalctl -k --since "24 hours ago"
sudo dmesg -T
```

Look for: MCE events; PCIe AER errors; disk I/O errors; filesystem errors; guest-visible machine-check or memory errors; unexpected resets.

Remember that a clean guest log does not clear the physical hypervisor host.

## Required Hypervisor-Side Follow-up

The guest cannot close the root-cause investigation by itself. The physical host should be checked for:

### RAM errors
- run memtest86+ on the physical host;
- if ECC RAM is present, inspect host EDAC/rasdaemon/IPMI/BMC counters;
- identify any DIMM reporting corrected or uncorrected errors.

### Physical storage health
- run `smartctl -a` against the physical disk(s) backing the VM image;
- inspect reallocated sectors, pending sectors, CRC errors, NVMe media/data-integrity errors, and device self-tests;
- inspect host dmesg / journalctl -k for I/O errors, link resets, controller errors, filesystem faults, or corruption.

### Memory capacity / workload pressure
- add RAM if possible;
- otherwise reduce workload;
- this guest has previously had roughly 14 GiB total RAM and is tight for a full standalone Security Onion stack.

Once the guest has adequate RAM headroom, consider disabling swap entirely as the cleaner Elasticsearch posture. Do not do so before confirming that the system can safely operate without it.

## Change Management Rules

### Before changing anything
- Record current state.
- Identify the failure mode from evidence, not assumption.
- Check whether the setting is Salt-managed.
- Prefer changing the Security Onion Salt pillar/source of truth instead of editing rendered files directly.
- Back up any local configuration file before modifying it when practical.
- Check snapshots before destructive index operations.

### After every change
- Verify the actual result.
- For Elasticsearch changes, check at minimum: service/container restarted successfully if required; rendered config contains the intended setting; Elasticsearch reports the setting/effect at runtime where possible; cluster returns to GREEN; no unassigned shards; ingestion resumes; snapshots remain functional.
- Never equate "command returned 0" with "problem fixed".

### Destructive actions

Before deleting an index:
- confirm it is not a current write index;
- check whether a snapshot exists;
- preserve the exact index name;
- understand its data stream relationship;
- prefer recovery over deletion.

Do not delete multiple indices broadly with wildcards during an incident unless there is overwhelming evidence and a verified recovery path.

## Secrets and Access

The host is `alex@192.168.2.73`. The password is stored in `.env` (see [`.env` format](#env-format) above).

Rules:
- never write the password into CLAUDE.md;
- never commit `.env`;
- never print the password in terminal output;
- never paste it into incident notes;
- do not put it directly in reusable shell scripts;
- prefer key-based authentication if it becomes available;
- if an SSH command needs non-interactive authentication, use a method that does not expose the secret in process listings or logs whenever possible.

## CLAUDE.md Maintenance Requirement

Keep this file up to date.

After every material investigation, fix, configuration change, restore, snapshot-policy change, monitoring change, or new recurrence:
- update the relevant section of this file;
- distinguish clearly between: historical observations; current verified state; hypotheses; confirmed root causes;
- correct older statements when new evidence disproves them;
- record important dates and exact index/snapshot names when useful;
- do not leave known-false root-cause claims in place;
- keep procedures aligned with what actually worked on this machine;
- never add secrets.

When new evidence conflicts with this runbook, the live system wins. Verify the live state, update this file, and explain the correction.

## Current Known-Good Baseline

At the latest verified point (2026-08-14, routine health check #7, performed a few hours after fix #6):

- Elasticsearch cluster: GREEN
- unassigned shards: 0
- active primary shards: 244
- recovered corrupt indices this recurrence: 2 (`.ds-logs-soc-so-2026.08.06-000078`, `elastalert_error`)
- cumulative recovered corrupt indices across all recurrences: 5
- failed restored shards: 0
- SOC backing index restored/re-attached after rollover; write index as of this check: `.ds-logs-soc-so-2026.08.14-000082`
- `logs-soc-so` ingestion confirmed caught up to real time (latest doc `@timestamp` 2026-08-14T17:04:35Z) — prior open item closed
- Elasticsearch heap: 3072m (confirmed at runtime via `_nodes/stats/jvm`)
- vm.swappiness: 1 (confirmed)
- bootstrap.memory_lock: true (confirmed via node settings)
- mlockall: true
- swap: intentionally still enabled due to limited RAM; usage steady ~2.7GB/8GB, not growing, no OOM events in 7 days
- disk usage: 74% (118.2GB/157.9GB), not near allocation watermarks
- snapshot repository: so_backup
- SLM policy: daily-snapshots
- SLM partial snapshots: enabled
- daily SLM runs were PARTIAL every day 2026-08-07 through 2026-08-14 02:30 due to the 2 corrupt shards fixed in #6 (all those runs predate the 16:54 repair); should return to full SUCCESS starting with the 2026-08-15 ~02:30 run — **verify next session**
- fresh known-good manual snapshot taken after repair: `post-repair-2026.08.14-165422`, success, 223/223 shards
- rasdaemon: active and enabled
- guest-visible rasdaemon baseline (re-checked 2026-08-14, post-fix): zero errors in Memory, MCE, PCIe AER, Extlog, devlink, disk — no change
- physical host RAM/storage: not cleared by guest-side checks; still requires host-side validation
- **new open item:** `so-elastalert` container repeatedly segfaulting (11x over 2026-08-11 to 2026-08-14, same crash offset each time) — rule execution appears unaffected so far (elastalert_status shows normal ~10min cadence continuing), but most recent actual alert is stale (2026-07-17); not yet root-caused, see fix/finding #7 above
- open item: confirm 2026-08-15 ~02:30 SLM run returns to SUCCESS

This baseline is historical until re-verified during the next session.

## Priority Order During Future Recurrence

1. Preserve current ingestion by rolling over a corrupt write index.
2. Confirm the exact corrupt shard/index and obtain allocation evidence.
3. Find the newest known-good snapshot.
4. Restore data instead of deleting it when possible.
5. Return the cluster to GREEN with zero unassigned shards.
6. Verify SOC dashboards and ingestion.
7. Take/verify a fresh snapshot.
8. Check rasdaemon, kernel logs, memory, swap, and I/O signals.
9. Escalate host RAM/storage testing if checksum corruption recurs.
10. Update this CLAUDE.md with what actually happened and what was proven.
