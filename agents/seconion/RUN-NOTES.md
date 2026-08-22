# RUN-NOTES.md — Security Onion, accumulated findings

Operational history of this specific machine — verify rather than trust, but start here.

This file is owned by the agent. The standing procedure lives in `CLAUDE.md` and is maintained by a
human — do not edit it. Follow the maintenance rules at the bottom of `CLAUDE.md` when updating this
file, in particular: **a routine check that found nothing does not get its own history entry** —
update the baseline and the open items instead. **Never add secrets.**

*Last updated 2026-08-21, ~08:10 UTC.*

---

## Operational tooling

Concrete commands verified to work on this host as of 2026-08-21.

**`.env` format — verified 2026-08-21.** The file uses `key=value`, **not** `key: value`. Keys present: `host`, `password`, `GITLAB_ACCESS_TOKEN`. Earlier revisions of this runbook documented `awk -F': ' '/^password:/{print $2}'`, which silently returns an empty string against the real file and makes every SSH command fail. Parse with `cut -d= -f2-` instead — the `-f2-` matters, since it preserves any `=` appearing inside a secret. Beware off-by-one if using `substr`: `GITLAB_ACCESS_TOKEN=` is 20 characters, so the value starts at position 21, and a wrong offset yields a truncated token whose only symptom is a confusing `401 Unauthorized` / `HTTP Basic: Access denied` rather than an obvious parse error.

**SSH + sudo, non-interactively, without leaking the password.** The sudo password is the same as the SSH login password. Login uses `sshpass -f` with a process-substituted extraction; sudo reads the same password from the remote command's stdin via `-S`:

```bash
grep '^password=' .env | cut -d= -f2- | sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash -c "<commands>"'
```

For anything longer than a couple of lines, avoid nested-quoting pain by writing the script to a remote temp file first (plain SSH, no sudo needed for `/tmp`), then executing it as root in a second connection:

```bash
sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'cat > /tmp/fix.sh' <<'EOF'
#!/bin/bash
set -e
<commands>
EOF

grep '^password=' .env | cut -d= -f2- | sshpass -f <(grep '^password=' .env | cut -d= -f2-) ssh -o StrictHostKeyChecking=no alex@192.168.2.73 'sudo -S -p "" bash /tmp/fix.sh'
```

Remove the temp script from `/tmp` after use.

**Querying/mutating Elasticsearch.** Use Security Onion's own wrapper, run as root — it handles auth and TLS itself:

```bash
sudo so-elasticsearch-query <path> [-X <METHOD>] [-d '<json-body>']
```

Do not pass an extra `-H "Content-Type: ..."` — the tool sets its own and a duplicate header causes a `media_type_header_exception`. Paths used during past fixes: `_cluster/health?pretty`, `_cat/shards?h=index,shard,prirep,state,unassigned.reason`, `_cluster/allocation/explain -X POST -d '{...}'`, `_cat/snapshots/so_backup?v&s=start_epoch:desc`, `_snapshot/so_backup/<name>/_restore?wait_for_completion=true -X POST -d '{...}'`, `_data_stream/_modify -X POST -d '{...}'`.

**Pushing the session log to GitLab.** Clone with the token embedded in the URL, write the log under `seconion/`, commit and push:

```bash
TOKEN=$(grep '^GITLAB_ACCESS_TOKEN=' .env | cut -d= -f2-)
git clone -q "https://oauth2:${TOKEN}@gitlab.labjunkie.org/alex/logs.git" /tmp/logsrepo
```

Pipe any git output through `sed 's/glpat-[A-Za-z0-9_-]*/<redacted>/g'` so the token cannot land in a transcript, and grep the finished log for the password and token strings before committing. Verify the token independently with `curl -s -o /dev/null -w '%{http_code}' --header "PRIVATE-TOKEN: $TOKEN" https://gitlab.labjunkie.org/api/v4/user` — expect `200`; a `401` almost always means the value was mis-parsed, not that the token expired.

---

## The recurring incident: Elasticsearch Lucene checksum corruption

### User-visible symptom

Every few days the Elasticsearch cluster has historically entered RED status, causing the SOC alerts dashboard to become unavailable.

The usual Elasticsearch symptom is an unassigned primary shard with `ALLOCATION_FAILED` and a Lucene corruption error similar to:

```text
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

**Supporting evidence has strengthened over time.** Three separate language runtimes on this host have now failed in memory-integrity-shaped ways — salt-minion's `python3.10` (segfaults at *varying* instruction pointers with wild fault addresses, the textbook random-corruption signature), Kibana's V8 (`unreachable code` JIT abort in `MemoryLowering::ReduceStoreField`), and elastalert's `libpython3.13` (fixed offset, so probably a genuine software bug rather than corruption). Meanwhile all three Lucene corruptions produced **zero** guest-visible hardware signal. This is circumstantial and does not substitute for the host-side testing in `CLAUDE.md`.

---

## Configuration changes already applied

These are considered current baseline unless live verification proves otherwise.

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

Verified outcomes at the time of the change:
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

At the time of the change, snapshot history showed approximately 5 failed, 1 successful. A fresh manual snapshot was then taken successfully: `daily-snap-2026.08.06-...ikfa` — result: SUCCESS, 226/226 shards, 0 failures.

The normal daily policy runs around 02:30 with 7-day retention.

---

## Incident history

### 2026-08-02/03 — first documented recurrence, restored from snapshot

Three corrupt indices were recovered from `daily-snap-2026.08.01`; restore result was 3/3 shards with 0 failures; the cluster returned to GREEN with 0 unassigned shards and all shards STARTED.

The `logs-soc-so` data stream required special handling because its corrupt backing index was also the active write index. Recovery sequence used:

1. roll over the data stream first so a healthy write index exists;
2. restore the corrupt historical backing index from the known-good snapshot;
3. re-attach the restored SOC backing index to its data stream if required;
4. verify ingestion resumed;
5. verify cluster health is GREEN.

**Do not simply delete a corrupt index until snapshot recovery options have been checked.**

### 2026-08-14 — second recurrence; first non-data-stream index hit

Cluster was found RED with 2 unassigned primary shards, both `CorruptIndexException: checksum failed (hardware problem?)`:

- `.ds-logs-soc-so-2026.08.06-000078` — the active **write index** of the `logs-soc-so` data stream (failed 2026-08-08T22:29Z). Same recurring pattern as the first incident.
- `elastalert_error` — a plain (non-data-stream) index (failed 2026-08-07T01:47Z). **First time a standalone, non-data-stream index has been hit.**

Side effect confirmed for the first time: the corrupt `logs-soc-so` write index **stalled SOC ingestion for ~6 days** (last doc before the fix was timestamped 2026-08-08T23:29Z — ingestion had been silently stuck since shortly after the corruption occurred, not just "ingestion may stall" as a hypothetical). Daily snapshots had also been running `PARTIAL` every day since 2026-08-07 because of these same 2 shards; `daily-snap-2026.08.06-...-ikfa` was the last fully-clean snapshot and was confirmed to contain good copies of both affected indices before use.

**This is the canonical repair sequence — it has since worked unchanged on a third recurrence:**

1. `POST logs-soc-so/_rollover` — protects ingestion by creating a new write index.
2. `DELETE <corrupt backing index>` — deleting a non-write backing index directly auto-detaches it from the data stream.
3. `POST _snapshot/so_backup/<snapshot>/_restore` with `{"indices":"<index>"}` — restores it as a standalone index.
4. `POST _data_stream/_modify` with `add_backing_index` — re-attaches the restored index to the data stream.
5. For a plain index (no data stream, so no rollover/reattach needed): `DELETE`, then restore the same way.
6. Verify GREEN and take a fresh manual recovery snapshot.

Result: cluster GREEN, 243/243 active shards, 0 unassigned; recovery snapshot `post-repair-2026.08.14-165422` SUCCESS, 223/223 shards, 0 failures. Ingestion backlog drained over several hours and was confirmed caught up to real time the same day.

### 2026-08-16 — third recurrence; corruption hit the index created by the previous repair

Cluster found **RED** with 1 unassigned primary shard: `.ds-logs-soc-so-2026.08.14-000082` — the active write index of `logs-soc-so`, and **the very index created by the rollover two days earlier**.

```text
corrupt_index_exception: failed engine (reason: [refresh failed source[schedule]]) (resource=preexisting_corruption)
  caused_by i_o_exception -> corrupt_index_exception:
  checksum failed (hardware problem?) : expected=5eb55d9a actual=d5f0157b
  (resource=... path="/usr/share/elasticsearch/data/indices/j_1cMj4tTmiqKEWHEVnMNw/0/index/_hjx_Lucene90_0.dvm")
```

**Tightest corruption window captured so far:**
- 02:29:59–02:30:47Z — scheduled SLM run `daily-snap-2026.08.16-qv06msxnt1mrsprowzqu7q` completed SUCCESS, 222/222 shards. The index was healthy at this point and the snapshot confirmed to contain a good copy.
- 13:58:17.292Z — shard went UNASSIGNED / ALLOCATION_FAILED. Corruption therefore occurred within an ~11.5 hour window, **not** at the moment of the previous repair.
- ~14:11Z — last document to reach Elasticsearch; SOC ingestion then stalled ~6 hours until repair.

The corrupt index survived only ~2 days (created 2026-08-14 16:5x, corrupt 2026-08-16 13:58) — a shorter interval than the previous recurrence, on a freshly created index, which further undercuts any "old/accumulated data" explanation.

The canonical sequence above was applied unchanged and worked: restore 1/1 shards 0 failures from the same morning's snapshot (bounding data loss to roughly 02:30–13:58), cluster GREEN 244/244, recovery snapshot `post-repair-2026.08.16-195856` SUCCESS 224/224.

**Ingestion recovery was fast this time** — the buffered backlog drained within ~3 minutes, unlike the ~6-day backlog of the previous incident. **Verify with two spaced samples rather than one**: a single sample right after rollover looks "stale" and is easy to misread as a failed fix.

⚠️ **Query trap.** Searching `elastalert*/_search` returns a doc timestamped ~now and looks like alerting is healthy — but that hit comes from `elastalert_status` (rule-execution bookkeeping, millions of docs), not from real alerts. **Always query the bare `elastalert` index** to judge alert freshness.

### 2026-08-20 — Kibana found dead for ~22 days and restored

**Elasticsearch was healthy — the fault was Kibana, silently down for three weeks.** First documented incident on this system that is not the Lucene corruption issue, and the explanation for the "404 page not found" reports.

**How it was found.** The mission's standing instruction to check Kibana is what surfaced this; every Elasticsearch-side check was clean and would have ended the session with "all healthy." `so-status` reported `so-kibana | running | Up 4 weeks` and the "This onion is ready" banner, so the normal status tooling actively concealed the outage.

**Root cause.** The Kibana Node.js process died at **2026-07-29T21:53Z** with a V8 fatal error and never came back:

```text
# Fatal error in , line 0
# unreachable code
 2: 0x218cc71 V8_Fatal(char const*, ...)
 4: 0x24ffa7f v8::internal::compiler::MemoryLowering::ReduceStoreField(...)
 5: 0x2503a1e v8::internal::compiler::MemoryOptimizer::Optimize()
```

The container survived the death of its own service because `/usr/local/bin/so-kibana.sh` starts Kibana **backgrounded** (`/usr/local/bin/kibana-docker &`) and then falls through to `sleep infinity`. PID 1 is the shell and PID 1107 is `sleep infinity`; when the Node process crashed, PID 1 stayed alive, Docker saw a healthy container (`RestartCount: 0`, `ExitCode: 0`, `StartedAt` still 2026-07-16), and no restart policy ever fired.

**Evidence it was genuinely down:** no node/kibana process inside the container (`ps -ef`); nothing listening on 5601 (`/proc/net/tcp` held only Docker's embedded DNS socket); `curl http://127.0.0.1:5601/api/status` returned `000` from the host, from inside the Kibana container, and from `so-nginx`; `/var/log/kibana/kibana.log` was 0 bytes and had rotated to a 20-byte empty gzip every midnight since at least 2026-08-06.

⚠️ **Diagnostic trap — the 307 means nothing.** Earlier health checks recorded "SOC web UI responding (HTTP 307 to login)" and treated it as proof the UI worked. It is not: nginx's `location /kibana/` runs `auth_request /auth/sessions/whoami` *before* proxying, so an unauthenticated request redirects to login without Kibana ever being contacted, alive or dead. The correct checks are in `CLAUDE.md` under Routine Health Checks → Kibana. nginx routing itself was verified **correct** and was not the problem.

**Fix:** `sudo so-kibana-restart` (Salt-managed: 21 states, 0 failed). Kibana came up cleanly in ~50 seconds, all saved-object migrations completed, `GET /api/status` → 200 `overall: available`, 168 plugins started, and `so-nginx` → `http://so:5601/api/status` went from `000` to `200`.

Kibana had previously died twice (2026-06-07, 2026-07-12) on `WAIT_FOR_YELLOW_SOURCE -> FATAL` migration timeouts against `.kibana_task_manager_8.17.3_001`, which is what happens when it starts against a non-GREEN cluster — **always return Elasticsearch to GREEN before restarting Kibana**.

---

## rasdaemon (hardware error monitoring)

Installed, configured, and verified active.

**Expected service state:** `active (running)`, enabled at boot. Previously verified process: `/usr/sbin/rasdaemon -f -r`

**Verified trace monitoring.** The rasdaemon trace instance was confirmed to have the following enabled:

```text
instances/rasdaemon/events/mce/mce_record/enable = 1
ras/mc_event/enable = 1
```

It was also verified to hold open per-CPU trace_pipe_raw handles across all 8 guest CPUs. Event classes being recorded included: mce_record, mc_event, aer_event, extlog, devlink, disk_errors.

**Baseline at last verification:** zero recorded errors in Memory, MCE, PCIe AER, Extlog, devlink, disk.

Check current state with:

```bash
sudo systemctl status rasdaemon --no-pager
sudo ras-mc-ctl --summary
sudo ras-mc-ctl --errors
```

**Important limitation.** This VM does not have guest-visible EDAC memory-controller support; `ras-mc-ctl --status` previously reported the relevant drivers not loaded. Therefore per-DIMM ECC counters generally will not be available inside this VM, a failing physical DIMM on the hypervisor may not appear to the guest, and guest-side rasdaemon only captures errors the hypervisor exposes. **Host-side testing remains mandatory to close the hardware question.**

---

## Open items

**Host-side RAM/storage testing — top outstanding action, now across five sessions.** Corruption has recurred three documented times with zero guest-visible hardware signal each time. See `CLAUDE.md` → Required Hypervisor-Side Follow-up. Restate in every report until done.

**salt-minion `python3.10` segfaults — evidence, not a separate fault to repair.** Two in 24h as of 2026-08-21:

```text
Aug 20 23:14:38 so kernel: /opt/saltstack/[2937971]: segfault at 1e
  ip 000000000053541c sp 00007ffd67c49570 error 6 in python3.10[400000+30b000]
Aug 21 04:59:12 so kernel: /opt/saltstack/[3440885]: segfault at 2000000da
  ip 000000000053bb79 sp 00007ffd67c4ad50 error 6 in python3.10[400000+30b000]
```

The interpretation matters more than the events. The **instruction pointers differ** (`0x53541c` vs `0x53bb79`) and the **fault addresses differ wildly** (`0x1e` vs `0x2000000da`) — the exact inverse of the elastalert pattern, where every crash landed at the same offset and was reasonably assessed as a deterministic code bug. Crashes at varying instruction pointers, one dereferencing an address no correct program would produce, is the textbook signature of **random memory corruption**. Impact is low and self-recovering: `salt-minion` stays `active`, Salt respawns its workers, no functional degradation observed. There is no safe guest-side remediation for suspected host DIMM faults.

**`so-elastalert` alerting gap — root cause identified, no fix applied, assessed benign.** `elastalert_error` (515,244 docs as of 2026-08-21, growing ~6,800/day) is dominated by rule queries failing against fields this deployment does not ingest:

```text
Error running query: RequestError(400, 'verification_exception',
  'Found 2 problems\nline 1:11: Unknown column [winlog.channel]
   \nline 1:80: Unknown column [winlog.provider_name]')
```

These are Windows-event-log Sigma rules querying `winlog.*`, so they abort with HTTP 400 on every ~10-minute cycle and can never fire. This is a **data-coverage mismatch, not a broken service**, and it means the sparse bare `elastalert` index (11 docs, newest `2026-07-17T21:53:50Z`, rule `Security Onion - SOC Login Failure`) is most likely benign rather than evidence of dropped alerts. The non-Windows rules execute correctly and simply have not matched.

Disabling or retuning the Windows rule set is a **tuning decision needing the user's call**, beyond the scope of a health check. The libpython3.13 segfault side has been quiet since 2026-08-14 13:50:25Z; the container has been up continuously since an unexplained 2026-08-14T14:02:09Z restart (`RestartCount: 0`) that was never traced to a docker or Salt event.

---

## Current known-good baseline

At the latest verified point (**2026-08-21, ~08:10 UTC — routine check, no fault found, nothing changed**):

- Elasticsearch cluster: GREEN; unassigned shards: 0; active primary shards: 235
- corrupt indices this session: **0**, and zero `corrupt_index_exception`/checksum matches in Elasticsearch logs over 24h. Cumulative recovered corrupt indices across all recurrences: 6.
- **`logs-soc-so` write index `.ds-logs-soc-so-2026.08.16-000085` has survived 5 days intact** (created 2026-08-16) — the longest clean run since the pattern began, against the ~2-day interval the previous incident warned about. The interval has always been irregular; this is not evidence the underlying problem is solved. Data stream GREEN, 5 backing indices.
- ingestion real-time, confirmed with two spaced samples (doc `2026-08-21T08:08:29Z` seen at 08:08:57Z; doc `2026-08-21T08:08:59Z` seen at 08:09:10Z)
- **Kibana: UP and healthy — the 2026-08-20 restart held.** One `node` process; `so-nginx` → `http://so:5601/api/status` → 200; `overall: available`; `/var/log/kibana/kibana.log` 175,561 bytes with a current-hour mtime (contrast the outage, where it was 0 bytes for weeks). Container up 22 hours. Always verify this way — never via the discredited 307 test.
- Elasticsearch heap: 3072m (`heap_max_in_bytes = 3221225472`, confirmed at runtime)
- vm.swappiness: 1; bootstrap.memory_lock: true, mlockall: true (all confirmed)
- memory: 14Gi total, 2.1Gi available; swap 3.1Gi/8Gi used — steady, within normal variation. Swap intentionally still enabled; `swapoff` remains unsafe at this memory level.
- disk: `/nsm` **74%** (117G/158G used, 42G avail) — the slow upward trend reversed (75% → 77% → 78% → 74%), consistent with 7-day retention aging data out. Well clear of the 90%/95% watermarks. (`/` is separate and comfortable at 46%, 45G avail.) Note that `/nsm`, not `/`, is where ES data lives — the two have very different sizes and it is easy to check the wrong one.
- snapshot repository: so_backup; SLM policy: daily-snapshots; `partial: true`, 7-day retention (`min_count: 3`, `max_count: 7`)
- **SLM fully healthy:** five consecutive clean scheduled runs — `daily-snap-2026.08.17` (223/223), `08.18` (222/222), `08.19` (221/221), `08.20` (223/223), `08.21` (215/215), all SUCCESS with 0 failed shards. `last_success` points at the 2026-08-21 run; `last_failure` still shows the historical pre-repair 2026-08-14 run and is expected — manual post-repair snapshots do not update SLM policy stats.
- most recent clean recovery point: `daily-snap-2026.08.21-fulfwdftrau80bzo4zdj3a` (02:29:59Z, SUCCESS, 215/215, 0 failures)
- all 23 containers running, "This onion is ready"
- rasdaemon: active and enabled; zero errors in Memory, MCE, PCIe AER, Extlog, devlink, disk; zero MCE/I-O/ATA/EXT4/OOM matches in `journalctl -k` over 24h
