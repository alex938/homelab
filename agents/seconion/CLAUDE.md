# CLAUDE.md — Security Onion Technician Runbook

## Mission

You are the technician responsible for keeping this Security Onion standalone deployment healthy, available, and recoverable. You are also required to check Kibana is working on the node as agents sometimes report '404 page not found' when accessing.

Your primary objective is to ensure Security Onion is running smoothly, with special attention to the recurring Elasticsearch/Lucene corruption fault documented below.

Operate conservatively. Prefer reversible, verified changes. Never claim a fix is complete until you have checked the resulting system state.

Store a log of what you have done with any actions you need me to do in 'https://gitlab.labjunkie.org/alex/logs.git'. The log needs to be stored in a folder called 'seconion'. The log needs to be stored in the format 'execute-$(date +%Y%m%d-%H%M%S).log'. Do not remove any logs or overwrite any logs. Each execute you are to commit and push the log to the repo. The access token is located .env in this directory. Update the repo README.md with a single line entry of the date time the execute ran.

Keep this CLAUDE.md streamlined and to the point when you make updates to it, removing absolete information to avoid it becoming to large.

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

## Operational Tooling Notes (for faster future fixes)

These are the concrete commands verified to work on this host as of 2026-08-21.

**`.env` format — verified 2026-08-21.** The file uses `key=value`, **not** `key: value`. Keys present: `host`, `password`, `GITLAB_ACCESS_TOKEN`. Earlier revisions of this runbook documented `awk -F': ' '/^password:/{print $2}'`, which silently returns an empty string against the real file and makes every SSH command fail. Parse with `cut -d= -f2-` instead — the `-f2-` matters, since it preserves any `=` appearing inside a secret. Beware off-by-one if using `substr`: `GITLAB_ACCESS_TOKEN=` is 20 characters, so the value starts at position 21, and a wrong offset yields a truncated token whose only symptom is a confusing `401 Unauthorized` / `HTTP Basic: Access denied` rather than an obvious parse error.

**SSH + sudo, non-interactively, without leaking the password.** The sudo password is the same as the SSH login password. Login uses `sshpass -f` with a process-substituted extraction; sudo reads the same password from the remote command's stdin via `-S`:

```
grep '^password=' .env | cut -d= -f2- | sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash -c "<commands>"'
```

For anything longer than a couple of lines, avoid nested-quoting pain by writing the script to a remote temp file first (plain SSH, no sudo needed for `/tmp`), then executing it as root in a second connection:

```
sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'cat > /tmp/fix.sh' <<'EOF'
#!/bin/bash
set -e
<commands>
EOF

grep '^password=' .env | cut -d= -f2- | sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash /tmp/fix.sh'
```

Remove the temp script from `/tmp` after use.

**Querying/mutating Elasticsearch.** Use Security Onion's own wrapper, run as root — it handles auth and TLS itself:

```
sudo so-elasticsearch-query <path> [-X <METHOD>] [-d '<json-body>']
```

Do not pass an extra `-H "Content-Type: ..."` — the tool sets its own and a duplicate header causes a `media_type_header_exception`. Examples used during the 2026-08-14 fix: `_cluster/health?pretty`, `_cat/shards?h=index,shard,prirep,state,unassigned.reason`, `_cluster/allocation/explain -X POST -d '{...}'`, `_cat/snapshots/so_backup?v&s=start_epoch:desc`, `_snapshot/so_backup/<name>/_restore?wait_for_completion=true -X POST -d '{...}'`, `_data_stream/_modify -X POST -d '{...}'`.

**Pushing the session log to GitLab.** Clone with the token embedded in the URL, write the log under `seconion/`, commit and push:

```
TOKEN=$(grep '^GITLAB_ACCESS_TOKEN=' .env | cut -d= -f2-)
git clone -q "https://oauth2:${TOKEN}@gitlab.labjunkie.org/alex/logs.git" /tmp/logsrepo
```

Pipe any git output through `sed 's/glpat-[A-Za-z0-9_-]*/<redacted>/g'` so the token cannot land in a transcript, and grep the finished log for the password and token strings before committing. Verify the token independently with `curl -s -o /dev/null -w '%{http_code}' --header "PRIVATE-TOKEN: $TOKEN" https://gitlab.labjunkie.org/api/v4/user` — expect `200`; a `401` almost always means the value was mis-parsed, not that the token expired.

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

### 8. Routine health check — 2026-08-14, later same day (session re-verification, no incident found)

Performed the Incident Response / Routine Health Check procedure again, ~17:12 UTC, roughly 30 minutes after health check #7. No fix was needed — this was a verification pass only, run because a new session started and CLAUDE.md's mission is to keep this system healthy.

Findings, all consistent with the fix #6 / health check #7 baseline:

- Cluster health: GREEN, 244/244 active primary shards, 0 unassigned, 0 shards in any non-STARTED state.
- `logs-soc-so` ingestion current: latest doc `@timestamp` 2026-08-14T17:11:37Z, i.e. essentially real-time when checked at 17:12Z.
- Elasticsearch heap: `heap_max_in_bytes = 3221225472` (3072m), confirmed at runtime. `bootstrap.memory_lock = true` confirmed via node settings. `vm.swappiness = 1` confirmed.
- Memory: 14Gi total, ~270Mi free, 3.2Gi buff/cache, 3.0Gi available; swap 2.7Gi/8Gi used, matching the known memory-constrained baseline, not worsening.
- Disk: root filesystem 49% (not where ES data lives). ES/NSM data lives on the separate `/nsm` mount (`/dev/mapper/system-nsm`): 75% (119G/158G used, 40G avail) — not near allocation watermarks. Prior health-check entries that cited "74% (118.2GB/157.9GB)" for "disk usage" were referring to this same `/nsm` mount, not `/` — noting this explicitly since the two filesystems have very different sizes and it would be easy to check the wrong one.
- rasdaemon: active, zero errors in Memory, MCE, PCIe AER, Extlog, devlink, disk — no change.
- No new corrupt_index_exception, checksum failures, or I/O errors in kernel logs for the prior 24h.
- SLM policy: `partial: true` still set, 7-day retention intact. `last_failure` on the policy is the 2026-08-14T02:30:11Z run (2 shards) — this predates the 16:54 repair in fix #6 and is expected/already explained, not a new failure. `last_success` still shows `daily-snap-2026.08.06-...-ikfa` (manual post-repair snapshots don't update SLM policy stats). **The 2026-08-15 ~02:30 SLM run had not occurred yet at check time (17:12 UTC on 08-14, ~9 hours before the next scheduled run) — still open, verify next session.**
- `so-status`: all 24 containers running (so-elasticsearch, so-elastalert, so-kibana, so-soc, so-logstash, etc.), "This onion is ready" banner shown — no degraded services.
- so-elastalert open item unchanged: container still up (RestartCount=0), still segfaulting at the same libpython3.13 offset (latest occurrence 2026-08-14 13:50 UTC, consistent with the existing pattern), most recent actual alert doc still dated 2026-07-17 (unchanged, still stale). Not re-investigated further this session; remains an open item.

**Conclusion: no active incident, no changes made or needed.** The system was already in its known-good state from fix #6, and this check confirms that state held.

### 9. Routine health check — 2026-08-14, ~17:15 UTC (session re-verification, one new observation, no fix needed)

Performed the Incident Response / Routine Health Check procedure again, ~3 minutes after health check #8, at the start of a new session. All core findings were unchanged from #8: cluster GREEN, 244/244 active primary shards, 0 unassigned; `logs-soc-so` ingestion current (latest doc `@timestamp` 2026-08-14T17:15:08Z); heap 3072m and `bootstrap.memory_lock: true` confirmed at runtime; `vm.swappiness = 1`; `/nsm` at 75% (118G/158G used, 41G avail); rasdaemon zero errors across all categories; no new corrupt_index_exception/checksum/I-O errors in the last 24h; SLM policy still `partial: true`, 7-day retention, `last_failure` still the pre-repair 2026-08-14T02:30:11Z run (2 shards, expected), `last_success` still `daily-snap-2026.08.06-...-ikfa`; `so-status` shows all containers running, "This onion is ready".

**New observation on the existing so-elastalert open item (refines, does not resolve it):** `docker inspect so-elastalert` showed `StartedAt: 2026-08-14T14:02:09Z` — i.e. the container's main process had only been up ~3 hours at check time, unlike every other so-* container (up ~3-4 weeks). `RestartCount` was still `0` and `State` was clean (`OOMKilled: false`, `ExitCode: 0`, `Error: ""`), so this was not a crash-loop restart counted by Docker's restart policy. The last libpython3.13 segfault before this was at 2026-08-14 13:50:25 UTC (same recurring offset as before, 11th+ occurrence), and the container's new `StartedAt` of 14:02:09 is only ~12 minutes later — a plausible but unconfirmed correlation. Checked `journalctl -u docker` for the 13:55–14:10 UTC window and found no container start/die/restart event logged, and no Salt minion log activity mentioning elastalert, so the actual trigger for the container-level restart (vs. just the internal subprocess segfault-and-respawn pattern documented in finding #7) is still untraced. No action taken: the container is healthy now, this doesn't match the Elasticsearch corruption failure mode, and there still isn't enough evidence to distinguish "benign docker/compose-level restart" from "the segfault finally took down the main process this once." This strengthens the case for root-causing the segfault open item in a future session rather than continuing to defer it indefinitely.

**Conclusion: no active incident, no changes made.** SLM 2026-08-15 ~02:30 run is still the key open item to verify next session.

### 10. Recurrence resolved — 2026-08-16 (third documented recurrence; corruption hit the index created by the previous repair)

Session started ~19:57 UTC on 2026-08-16, two days after health checks #7–#9. Cluster was found **RED** with 1 unassigned primary shard.

**What was corrupt:** `.ds-logs-soc-so-2026.08.14-000082` — the *active write index of `logs-soc-so`*, and notably **the very index created by the rollover in fix #6 two days earlier**. Allocation explain gave the now-familiar evidence:

```
corrupt_index_exception: failed engine (reason: [refresh failed source[schedule]]) (resource=preexisting_corruption)
  caused_by i_o_exception -> corrupt_index_exception:
  checksum failed (hardware problem?) : expected=5eb55d9a actual=d5f0157b
  (resource=... path="/usr/share/elasticsearch/data/indices/j_1cMj4tTmiqKEWHEVnMNw/0/index/_hjx_Lucene90_0.dvm")
```

**Timeline established from evidence (useful — this is the tightest corruption window captured so far):**
- 2026-08-16T02:29:59–02:30:47Z — scheduled SLM run `daily-snap-2026.08.16-qv06msxnt1mrsprowzqu7q` completed **SUCCESS**, 222/222 shards, 0 failures. The index was healthy at this point and the snapshot was confirmed to contain a good copy of it.
- 2026-08-16T13:58:17.292Z — shard went UNASSIGNED / ALLOCATION_FAILED (`unassigned.at`). Corruption therefore occurred within an ~11.5 hour window on 2026-08-16, **not** at the moment of the previous repair.
- 2026-08-16T~14:11Z — last document that reached Elasticsearch; SOC ingestion then stalled for ~6 hours until this repair, the same stall-on-corrupt-write-index side effect confirmed in fix #6.

Note the corrupt index survived only ~2 days (created 2026-08-14 16:5x, corrupt 2026-08-16 13:58). This is a **shorter interval than the previous recurrence**, and it happened on a freshly created index, which further undercuts any "old/accumulated data" explanation and is consistent with the standing host-side hardware/storage diagnosis.

**Fix applied — the documented sequence from #6 worked unchanged:**

1. `POST logs-soc-so/_rollover` → new write index `.ds-logs-soc-so-2026.08.16-000085` (succeeded even with the data stream RED).
2. `DELETE .ds-logs-soc-so-2026.08.14-000082` (now a non-write backing index, so the delete auto-detaches it).
3. `POST _snapshot/so_backup/daily-snap-2026.08.16-qv06msxnt1mrsprowzqu7q/_restore?wait_for_completion=true` with `{"indices":".ds-logs-soc-so-2026.08.14-000082","include_aliases":false}` → 1/1 shards, 0 failures. Restoring from *the same morning's* snapshot means data loss is bounded to roughly 02:30–13:58 on 2026-08-16 for that backing index.
4. `POST _data_stream/_modify` with `add_backing_index` → re-attached; data stream status returned GREEN.
5. Verified: cluster **GREEN**, 244/244 active primary shards, 0 unassigned, no shard in any non-STARTED state.
6. Fresh recovery snapshot `post-repair-2026.08.16-195856` — **SUCCESS, 224/224 shards, 0 failures**.

**Ingestion recovery was fast this time:** immediately after the rollover the latest doc was still 14:11Z, but the buffered backlog drained within ~3 minutes (samples: 19:58:46Z doc at 20:00:08, 20:00:36Z doc at 20:00:54, 20:01:06Z doc at 20:01:39; new write index went 44,822 → 45,396 docs across those samples). Contrast with fix #6, where a ~6-day backlog took hours. Verify with two spaced samples rather than one — a single sample right after rollover looks "stale" and is easy to misread as a failed fix.

**Prior open item CLOSED — SLM snapshots returned to full SUCCESS.** Both scheduled runs since the fix #6 repair were clean: `daily-snap-2026.08.15-...` SUCCESS 222/222 and `daily-snap-2026.08.16-...` SUCCESS 222/222, 0 failed shards each. `last_success` on the `daily-snapshots` policy now correctly points at the 2026-08-16 run. `last_failure` still shows the pre-repair 2026-08-14T02:30 run and is expected/historical. This confirms the fix #6 prediction and closes that item.

Other health signals checked during this session, all clean or unchanged: heap `heap_max_in_bytes = 3221225472` (3072m), `bootstrap.memory_lock: true`, `vm.swappiness = 1`; rasdaemon zero errors across Memory/MCE/PCIe AER/Extlog/devlink/disk; **no MCE, I/O, ATA, EXT4 or filesystem errors in `journalctl -k` for the last 24h** (i.e. the guest again saw no hardware signal at all despite real checksum corruption — consistent with the documented EDAC limitation, and further reason the host-side testing below is still mandatory); all 24 containers running with "This onion is ready"; SOC web UI responding (HTTP 307 redirect to login, i.e. nginx/SOC serving normally) — **this inference was later disproven; see finding #11. A 307 only proves nginx's `auth_request` layer is alive and says nothing about Kibana, which was in fact already dead at the time of this check.** `/nsm` at 77% (121G/158G used, 38G avail) — up 2 points from 75% two days ago, still clear of the 90%/95% watermarks but worth watching. Memory: 14Gi total, 1.6Gi available, swap 2.6Gi/8Gi used — steady, matching baseline.

**so-elastalert open item — partially refined, still open.** No segfault has occurred since 2026-08-14 13:50:25 UTC, i.e. **~2 days clean**, and the container has been up continuously since its unexplained 2026-08-14T14:02:09Z restart (`RestartCount: 0`, status running). So the restart appears to have stopped the segfault loop. However, the alerting gap is **not** resolved: the `elastalert` index (actual alerts) still holds only 11 docs with the newest dated **2026-07-17T21:53:50Z**, unchanged and now a month stale.

⚠️ **Query trap worth remembering:** searching `elastalert*/_search` returns a doc timestamped ~now and looks like alerting is healthy — but that hit comes from `elastalert_status` (7,593,799 docs, rule-execution bookkeeping), not from real alerts. **Always query the bare `elastalert` index** to judge alert freshness. Also newly noted: `elastalert_error` holds **481,119** docs, which is a large error volume and is probably the most promising lead for root-causing this next.



### 11. Kibana found dead for ~22 days and restored — 2026-08-20 (first non-Elasticsearch fault; explains the "404 page not found" reports)

Session started ~10:26 UTC on 2026-08-20, four days after fix #10. **Elasticsearch was healthy — the fault this time was Kibana, and it had been silently down for three weeks.** This is the first documented incident on this system that is not the Lucene corruption issue.

**Symptom / how it was found.** The mission's standing instruction to check Kibana is what surfaced this; every Elasticsearch-side check was clean and would have ended the session with "all healthy." `so-status` reported `so-kibana | running | Up 4 weeks` and the "This onion is ready" banner, so the normal status tooling actively concealed the outage.

**Root cause.** The Kibana Node.js process died at **2026-07-29T21:53Z** with a V8 fatal error and never came back:

```
# Fatal error in , line 0
# unreachable code
 2: 0x218cc71 V8_Fatal(char const*, ...)
 4: 0x24ffa7f v8::internal::compiler::MemoryLowering::ReduceStoreField(...)
 5: 0x2503a1e v8::internal::compiler::MemoryOptimizer::Optimize()
```

The container survived the death of its own service because of how the image's entrypoint is written. `/usr/local/bin/so-kibana.sh` starts Kibana **backgrounded** (`/usr/local/bin/kibana-docker &`) and then falls through to a `sleep infinity`. So PID 1 is the shell and PID 1107 is `sleep infinity`; when the Node process crashed, PID 1 stayed alive, Docker saw a healthy container (`RestartCount: 0`, `ExitCode: 0`, `StartedAt` still 2026-07-16), and no restart policy ever fired.

**Evidence that Kibana was genuinely down (not just misrouted):**
- Inside the container, `ps -ef` showed **no node/kibana process at all** — only the entrypoint shell and `sleep infinity`.
- Nothing was listening on 5601 inside the container (`/proc/net/tcp` held only Docker's embedded DNS socket on 127.0.0.11).
- `curl http://127.0.0.1:5601/api/status` returned `000` from the host, from inside the Kibana container itself, and from `so-nginx` to `http://so:5601/` — i.e. connection refused at every layer.
- `/var/log/kibana/kibana.log` was 0 bytes, and had rotated to a 20-byte (empty gzip) file every midnight since at least 2026-08-06 — a quietly visible symptom that nothing was writing logs.

⚠️ **Diagnostic trap — the 307 means nothing.** `curl -k https://localhost/kibana/` returns `307 Temporary Redirect` whether Kibana is alive or dead, because the nginx `location /kibana/` block runs `auth_request /auth/sessions/whoami` *before* proxying, so an unauthenticated request is redirected to login without Kibana ever being contacted. Earlier health checks (#7–#10) recorded "SOC web UI responding (HTTP 307 to login)" and treated it as proof the UI worked — **it is not**. To actually test Kibana, bypass the auth layer:

```
docker exec so-nginx curl -s -o /dev/null -w '%{http_code}\n' http://so:5601/api/status   # expect 200
docker exec so-kibana ps -ef | grep node                                                  # expect a node process
```

nginx routing itself was verified **correct** and was not the problem: `location /kibana/` does `rewrite /kibana/(.*) /$1 break;` then `proxy_pass http://so:5601/`, which correctly strips the prefix to match Kibana's `basePath: /kibana` + `rewriteBasePath: false`.

**Fix applied:** `sudo so-kibana-restart` (Salt-managed: 21 states, 0 failed). Kibana came up cleanly in ~50 seconds.

**Verified after the fix:**
- `http server running at http://0.0.0.0:5601`, then `[status] Kibana is now available`.
- Saved-object migrations **all completed** (`.kibana_task_manager` 202ms, `.kibana_alerting_cases` 203ms, `.kibana_analytics` 212ms, `.kibana_ingest` 209ms) — worth noting because Kibana had previously died twice (2026-06-07, 2026-07-12) on `WAIT_FOR_YELLOW_SOURCE -> FATAL` migration timeouts against `.kibana_task_manager_8.17.3_001`. Those failures happen when the cluster is not GREEN at Kibana start. **Restarting Kibana while the cluster is RED will likely fail this way — always return Elasticsearch to GREEN first, then restart Kibana.**
- `GET /api/status` → **200, `overall: available`, zero degraded core services or plugins** (168 plugins started).
- `so-nginx` → `http://so:5601/api/status` → **200** (was `000`), and `/app/home` → 302, i.e. the proxy path agents use now reaches a live Kibana.
- Re-checked ~4 minutes later: still up, still `available`, node process present.

Remaining Kibana log noise is benign and pre-existing: `plugins.fleet` "Failed to fetch latest version of synthetics from registry" and "Download Source ... already exists" (no outbound access to the Elastic package registry), plus config-deprecation warnings.

**Why this matters beyond Kibana.** A V8 "unreachable code" abort in the JIT's `MemoryLowering::ReduceStoreField` is a memory-integrity-shaped failure, and it is the *second* interpreter on this host dying in this manner (the other being the `so-elastalert` libpython3.13 segfaults). This is circumstantial, not proof — but it is consistent with, and adds weight to, the standing host-side RAM/storage diagnosis. It does **not** replace it: host-side memtest86+ and `smartctl` remain the outstanding action.

**so-elastalert open item — root cause of the alerting gap now identified (no fix applied).** Following the lead recorded in fix #10, the `elastalert_error` index (now **508,436** docs, ~317 in the last hour and ~7,576 in 24h — a steady, ongoing rate) is dominated by rule queries failing against fields that do not exist in this deployment:

```
Error running query: RequestError(400, 'verification_exception',
  'Found 2 problems\nline 1:11: Unknown column [winlog.channel]
   \nline 1:80: Unknown column [winlog.provider_name]')
```

Other samples reference `winlog.event_data.ObjectServer`, `winlog.event_data.AccessMask`, `winlog.event_data.ObjectType`. These are Windows-event-log Sigma rules, and this deployment ingests no `winlog.*` data, so those rules abort with HTTP 400 on every ~10-minute execution cycle and can never fire. This is a **data-coverage mismatch, not a broken service** — it explains the constant error volume, and it means the sparse `elastalert` index (still 11 docs, newest `2026-07-17T21:53:50Z`, rule `Security Onion - SOC Login Failure`) is most likely benign: the non-Windows rules do execute correctly and simply have not matched. No change was made — disabling or retuning the Windows rule set is a tuning decision beyond the scope of a health check, and CLAUDE.md's change-management rules call for evidence before acting. The segfault side stays quiet: no libpython3.13 segfault since 2026-08-14 13:50:25Z (~6 days clean), container up continuously since 2026-08-14T14:02:09Z, `RestartCount: 0`.

**Other signals checked this session, all clean or unchanged:** cluster GREEN 244/244 active primary shards, 0 unassigned, no shard in a non-STARTED state; `logs-soc-so` ingestion real-time across two spaced samples (doc `2026-08-20T10:26:16Z` at 10:26:30Z; doc `2026-08-20T10:34:47Z` at 10:35:12Z); write index still `.ds-logs-soc-so-2026.08.16-000085`, data stream GREEN, 5 backing indices; heap `heap_max_in_bytes = 3221225472` (3072m); `bootstrap.memory_lock: true`; `vm.swappiness = 1`; rasdaemon active with zero errors across Memory/MCE/PCIe AER/Extlog/devlink/disk; **zero** MCE/I-O/ATA/EXT4/segfault/OOM matches in `journalctl -k` for 24h; 23 containers running with "This onion is ready"; memory 14Gi total, 2.1Gi available, swap 2.8Gi/8Gi steady.

**Prior open item CLOSED — the corruption pattern did not recur on schedule.** Fix #10 predicted the write index `.ds-logs-soc-so-2026.08.16-000085` might be the next victim given the ~2-day interval. It has now survived **4 days** intact. All four scheduled SLM runs since the repair were fully clean — `daily-snap-2026.08.17` (223/223), `2026-08-18` (222/222), `2026-08-19` (221/221), `2026-08-20` (223/223) — **all SUCCESS with 0 failed shards**, and `last_success` on the policy now points at the 2026-08-20 run. The `last_failure` field still shows the historical pre-repair `daily-snap-2026.08.14` run and is expected. No new snapshot was taken this session: the corruption path was not touched, and `daily-snap-2026.08.20` (02:29:59Z, SUCCESS) already provides a clean same-day recovery point.

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

### 12. Routine health check — 2026-08-21, ~08:08–08:10 UTC (no fault found, no changes made; one significant new hardware-signal finding)

Full Routine Health Check run one day after the Kibana repair in finding #11. **Nothing was wrong and nothing was changed.** Both of the two faults this system has ever exhibited — Lucene checksum corruption and the dead-Kibana condition — were absent.

**Everything verified clean:** cluster **GREEN**, 235/235 active primary shards, 0 unassigned, 0 shards in any non-STARTED state; **zero** `corrupt_index_exception`/`CorruptIndexException`/`checksum failed` matches in `so-elasticsearch` logs over 24h; heap `heap_max_in_bytes = 3221225472` (3072m), `mlockall: true`, `vm.swappiness = 1`; rasdaemon active with zero errors across Memory/MCE/PCIe AER/Extlog/devlink/disk; zero MCE/I-O/ATA/EXT4/OOM matches in `journalctl -k` over 24h; all 23 containers running with "This onion is ready".

**Kibana confirmed genuinely up, using the finding-#11 method rather than the discredited 307 test:** one `node` process inside `so-kibana`; `so-nginx` → `http://so:5601/api/status` → **200**; `overall: available`; and `/var/log/kibana/kibana.log` at **175,561 bytes with an mtime of the current hour**. That last check is the sharpest one — during the outage the same file sat at 0 bytes and rotated to empty gzips nightly, so a large, freshly-written log is positive evidence the service is actually running rather than merely containerised. Container uptime 22 hours, matching the `so-kibana-restart`: **the fix held.**

**Ingestion real-time**, confirmed with two spaced samples per the fix-#10 guidance: doc `2026-08-21T08:08:29.482Z` read at 08:08:57Z, doc `2026-08-21T08:08:59.516Z` read at 08:09:10Z. Data stream GREEN, 5 backing indices.

**The corruption interval has been broken.** Write index `.ds-logs-soc-so-2026.08.16-000085` has now survived **5 days** (created 2026-08-16), against the ~2-day interval that fix #10 warned about. This does not mean the underlying problem is solved — the interval has always been irregular — but it is the longest clean run recorded since the pattern began.

**SLM fully healthy — five consecutive clean scheduled runs:** `daily-snap-2026.08.17` (223/223), `08.18` (222/222), `08.19` (221/221), `08.20` (223/223), `08.21` (215/215) — all SUCCESS, 0 failed shards. Policy retains `partial: true` and 7-day retention; `last_success` now points at the 2026-08-21 run, and `last_failure` still shows the historical pre-repair 2026-08-14 run as expected. No manual snapshot was taken: nothing was changed, and `daily-snap-2026.08.21-fulfwdftrau80bzo4zdj3a` (02:29:59Z, SUCCESS) already provides a clean same-day recovery point.

**`/nsm` disk trend reversed — 78% → 74%** (117G/158G used, 42G avail). The slow climb recorded across the previous three checks (75% → 77% → 78%) has corrected itself, consistent with 7-day snapshot and index retention aging data out. No longer a watch item at the previous level, though still worth a glance each session. (`/` is separate, 46%, 45G avail.)

**NEW FINDING — salt-minion `python3.10` segfaults, and this is the strongest hardware evidence the guest has produced so far (no fix applied).** Two segfaults in `/opt/saltstack`'s Python in the last 24h:

```
Aug 20 23:14:38 so kernel: /opt/saltstack/[2937971]: segfault at 1e
  ip 000000000053541c sp 00007ffd67c49570 error 6 in python3.10[400000+30b000]
Aug 21 04:59:12 so kernel: /opt/saltstack/[3440885]: segfault at 2000000da
  ip 000000000053bb79 sp 00007ffd67c4ad50 error 6 in python3.10[400000+30b000]
```

The interpretation matters more than the events themselves. The **instruction pointers differ** (`0x53541c` vs `0x53bb79`) and the **fault addresses differ wildly** (`0x1e` vs `0x2000000da`). That is the exact inverse of the `so-elastalert` libpython3.13 pattern, where every crash landed at the *same* offset (`+0x1600e4`) and was therefore reasonably assessed as a deterministic code bug. Crashes at varying instruction pointers, one of them dereferencing an address like `0x2000000da` that no correct program would produce, is the textbook signature of **random memory corruption** rather than a software defect.

This makes **three separate language runtimes** on this host to fail in a memory-integrity-shaped way: elastalert's libpython3.13 (fixed offset — probably a genuine bug), Kibana's V8 "unreachable code" JIT abort (finding #11), and now salt-minion's python3.10 at random offsets. Taken together with three Lucene checksum corruptions that produced **zero** guest-visible hardware signal each time, this substantially strengthens the standing host-side RAM/storage diagnosis. It remains circumstantial and does not substitute for the host-side testing below.

Impact is low and self-recovering: `salt-minion` is `active`, Salt respawns its workers, and no functional degradation was observed. No change was made — there is no safe guest-side remediation for suspected host DIMM faults, and CLAUDE.md's change-management rules require evidence-driven action.

**so-elastalert open item — unchanged, still open, still assessed benign.** Bare `elastalert` index: 11 docs, newest still `2026-07-17T21:53:50Z` (rule `Security Onion - SOC Login Failure`). `elastalert_error` grew 508,436 → **515,244** (~6,800/day, a steady ongoing rate consistent with the established root cause: Windows-event-log Sigma rules querying `winlog.*` fields this deployment never ingests, aborting with HTTP 400 each cycle). Container up since 2026-08-14T14:02:09Z, `RestartCount: 0`. **Zero** libpython3.13 segfaults in the current kernel journal — ~7 days clean. The remaining decision is a tuning one and is escalated to the user rather than actioned here.

**Conclusion: no active incident, no changes made.** The escalation-worthy output of this session is the salt-minion segfault signature, which raises the urgency of the host-side memtest86+/`smartctl` work that has now been outstanding across five sessions.

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

### Kibana (always check — this is a standing mission requirement)

Agents have reported `404 page not found` when accessing Kibana. As of 2026-08-20 the proven cause was that **Kibana had been dead for ~22 days while every status tool reported it healthy** (see finding #11).

Do not trust any of these as evidence Kibana works:
- `so-status` showing `so-kibana | running | Up N weeks` — the entrypoint backgrounds Kibana and then runs `sleep infinity`, so the container outlives its own service.
- `docker inspect` showing `RestartCount: 0` / `ExitCode: 0` — same reason.
- `curl -k https://localhost/kibana/` returning **307** — nginx runs `auth_request` *before* proxying, so an unauthenticated request redirects to login without ever contacting Kibana. This returns 307 whether Kibana is alive or dead.

Check it properly instead:

```
docker exec so-kibana ps -ef | grep -c '[n]ode'                                          # expect >= 1
docker exec so-nginx curl -s -o /dev/null -w '%{http_code}\n' http://so:5601/api/status  # expect 200
curl -s http://127.0.0.1:5601/api/status | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"]["overall"])'
docker exec so-kibana ls -l /var/log/kibana/kibana.log                                    # 0 bytes for days = dead
```

Healthy state is `overall: available` with zero degraded core services or plugins.

If Kibana is down, restart with `sudo so-kibana-restart`. **Return Elasticsearch to GREEN first** — Kibana has died twice historically (2026-06-07, 2026-07-12) on `WAIT_FOR_YELLOW_SOURCE -> FATAL` saved-object migration timeouts, which is what happens when it starts against a non-GREEN cluster. Confirm afterwards that migrations completed and that `[status] Kibana is now available` appears in `docker logs so-kibana`.

Benign, pre-existing log noise to ignore: `plugins.fleet` "Failed to fetch latest version of synthetics from registry" and "Download Source ... already exists" (no outbound access to the Elastic package registry), plus config-deprecation warnings.

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

The host is `alex@192.168.2.73`. The password is stored in `.env`, which uses `key=value` format — see **`.env` format** under Operational Tooling Notes above. `.env` also holds `GITLAB_ACCESS_TOKEN` for the log repository.

Rules:
- never write the password into CLAUDE.md;
- never commit `.env`;
- never write the GitLab token into CLAUDE.md, logs, or commit messages either — redact `glpat-` strings from any git output before it reaches a transcript;
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

At the latest verified point (**2026-08-21, ~08:10 UTC, health check #12 — no fault found, nothing changed**):

- Elasticsearch cluster: GREEN
- unassigned shards: 0
- active primary shards: 235
- corrupt indices this session: **0 — no Lucene corruption recurrence**, and zero `corrupt_index_exception`/checksum matches in Elasticsearch logs over 24h. Cumulative recovered corrupt indices across all recurrences remains 6.
- **`logs-soc-so` write index `.ds-logs-soc-so-2026.08.16-000085` has now survived 5 days intact** (created 2026-08-16) — the longest clean run since the corruption pattern began, against the ~2-day interval fix #10 warned about. Data stream GREEN, 5 backing indices.
- `logs-soc-so` ingestion real-time, confirmed with two spaced samples (doc `2026-08-21T08:08:29Z` seen at 08:08:57Z; doc `2026-08-21T08:08:59Z` seen at 08:09:10Z)
- **Kibana: UP and healthy — the 2026-08-20 restart held.** One `node` process present; `so-nginx` → `http://so:5601/api/status` → 200; `overall: available`; `/var/log/kibana/kibana.log` 175,561 bytes with a current-hour mtime (contrast the outage, where it was 0 bytes for weeks). Container up 22 hours. Always verify this way — never via the 307 test disproven in finding #11.
- Elasticsearch heap: 3072m (`heap_max_in_bytes = 3221225472`, confirmed at runtime)
- vm.swappiness: 1 (confirmed); bootstrap.memory_lock: true, mlockall: true (confirmed)
- memory: 14Gi total, 2.1Gi available; swap 3.1Gi/8Gi used — steady, up marginally from 2.8Gi on 2026-08-20, within normal variation and not a growth trend. Swap intentionally still enabled; `swapoff` remains unsafe at this memory level.
- disk: `/nsm` **74%** (117G/158G used, 42G avail) — **the slow upward trend reversed** (75% → 77% → 78% → 74%), consistent with 7-day retention aging data out. Well clear of the 90%/95% watermarks. (`/` is separate and comfortable at 46%, 45G avail.)
- snapshot repository: so_backup; SLM policy: daily-snapshots; `partial: true`, 7-day retention (`min_count: 3`, `max_count: 7`)
- **SLM fully healthy:** five consecutive clean scheduled runs — `daily-snap-2026.08.17` (223/223), `08.18` (222/222), `08.19` (221/221), `08.20` (223/223), `08.21` (215/215), all SUCCESS with 0 failed shards. `last_success` points at the 2026-08-21 run; `last_failure` still shows the historical pre-repair 2026-08-14 run and is expected.
- most recent clean recovery point: `daily-snap-2026.08.21-fulfwdftrau80bzo4zdj3a` (02:29:59Z, SUCCESS, 215/215, 0 failures)
- all 23 containers running, "This onion is ready"
- rasdaemon: active and enabled; zero errors in Memory, MCE, PCIe AER, Extlog, devlink, disk; zero MCE/I-O/ATA/EXT4/OOM matches in `journalctl -k` over 24h
- physical host RAM/storage: **still not cleared by guest-side checks; host-side memtest86+ and `smartctl` remain the top outstanding action, now across five sessions.** Corruption has recurred three documented times with zero guest-visible hardware signal each time, and this VM has no guest-visible EDAC support. **The evidence strengthened materially this session:** salt-minion's `python3.10` is segfaulting at *varying* instruction pointers with wild fault addresses (`0x2000000da`) — a random-memory-corruption signature, unlike elastalert's fixed-offset crashes. That makes three language runtimes (salt python3.10, Kibana V8, elastalert libpython3.13) failing in memory-integrity-shaped ways. See finding #12.
- **open item:** salt-minion `python3.10` segfaults — 2 in 24h, low impact and self-recovering (`salt-minion` active, workers respawned, no functional degradation). No guest-side fix exists; this is evidence for the host hardware question, not a separate fault to repair.
- **open item:** `so-elastalert` alerting gap — **root cause identified, no fix applied, assessed benign.** `elastalert_error` (515,244 docs, ~6,800/day ongoing) is dominated by `verification_exception: Unknown column [winlog.*]` — Windows-event-log Sigma rules querying fields this deployment never ingests, so they abort with HTTP 400 every cycle and can never fire. The sparse bare `elastalert` index (11 docs, newest `2026-07-17T21:53:50Z`) is therefore most likely benign rather than evidence of dropped alerts. Segfaults quiet ~7 days. Remaining decision is a tuning one and needs the user's call. When checking, **query the bare `elastalert` index** — `elastalert*` also matches `elastalert_status` and misleadingly looks current.

This baseline replaces the 2026-08-20 baseline, which was confirmed still valid in full this session; only the counts, dates and disk figures moved.

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
