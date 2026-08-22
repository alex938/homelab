# RUN-NOTES.md — APT cacher, accumulated findings

Facts established about this deployment — verify rather than trust, but start here.

This file is owned by the agent. Add what you learn, refresh the baselines at the bottom each run,
and delete anything that has become obsolete so the file stays streamlined. The standing procedure
lives in `CLAUDE.md` and is maintained by a human — do not edit it.

*Last updated 2026-08-22 12:20 UTC.*

## Access and host

The SSH account configured in `.env` is *not* in the `docker` group on `apt.labjunkie.org`, but has
passwordless sudo, so every docker command needs `sudo docker`. The host is on an Ubuntu 6.8 kernel,
hostname `apt`, 1.9 GB RAM and no swap.

## Container

Name `apt-cacher-ng`, image `aptcachernas:nfs-safe` (apt-cacher-ng 3.7.4), restart policy `always`,
no healthcheck. It is managed by docker compose from `/home/alex/docker-compose.yml` (project
`alex`). Published ports are `3142->3142` **and `80->3142`**. Command line is
`apt-cacher-ng ForeGround=1 SocketPath= PassThroughPattern=^.*:443$`. Mounts: `/home/alex/acng.conf`
and `/home/alex/zzz_override.conf` (both read-only) into `/etc/apt-cacher-ng/`, and the cache at
`/mnt/aptcacher` -> `/var/cache/apt-cacher-ng`.

**A changed `StartedAt` is usually a host package upgrade, not a fault.** On 2026-08-22 at 09:10 UTC
the host ran an unattended-style upgrade that pulled docker-ce 5:29.7.2, so systemd restarted
`docker.service` and the daemon restored the container — `StartedAt` jumped from 2026-08-16 to
2026-08-22 while host uptime stayed at 6 days. `RestartCount` remained 0 throughout, because that
counter only tracks restart-policy restarts, so it does **not** catch this. To tell a benign daemon
restart from a crash, check `journalctl -u docker` for a graceful `Stopping docker.service` /
`Daemon shutdown complete` pair, and `grep "^$(date +%F)" /var/log/dpkg.log | grep docker`. A
non-zero `RestartCount` is still a real signal of container-level trouble.

## Known open fault — the config files are not being read

Unresolved since 2026-08-20. The command line omits `-c /etc/apt-cacher-ng` and this build reads no
config directory by default (verified in a sandbox: without `-c` startup is silent and
`/acng-report.html` returns 503, matching the live daemon; with it, the mounted config parses). So
`ReportPage`, all `Remap-*` rules, and everything in `zzz_override.conf` (`DlMaxRetries: 10`,
`ResolveIPv6: 0`) are inert. `SocketPath` and `PassThroughPattern` survive only because they are
arguments. Caching is unaffected because `CacheDir`'s built-in default happens to match the bind
mount.

**Do not "fix" this by adding `-c` alone.** `acng.conf` contains `ExThreshold: 4G`, which is invalid —
`ExThreshold` is a number of *days* (default 4), not a size. With that line present the daemon prints
`Bad value for ExThreshold option` / `Error reading main options, terminating.` and will not start.
Both changes must land together, and both are config edits, so they are recommendations for a human.
`backends_debian`, `backends_ubuntu` and `backends_debvol` are 0 bytes and will emit
`No configuration was read from file:` warnings once the config is actually read.

## Report page

Expect `503 Host not found` at `/acng-report.html` until the above is fixed. Each probe writes its
own `E` line into the access log, so subtract URLs matching `acng-report` before reporting an error
count. `/style.css` returns 200 and `/` returns 406 with the usage page — both normal, on port 3142
and 80 alike.

## Deriving statistics without the report page

`docker logs` is useless: it holds only `Not creating Unix Domain Socket, fifo_path not specified`
messages emitted *without newlines*, so `wc -l` and `grep -c` return 0 even on non-empty output — use
`grep -o` to count there. Also `docker logs --since 7d` is **rejected**; Docker wants a Go duration,
so use `--since 168h`. The real data is inside the container at
`/var/log/apt-cacher-ng/apt-cacher.log`, format `epoch|type|bytes|client|url`, where `I` = fetched
upstream, `O` = sent to client, `E` = error. Volume hit rate is `(sum(O) - sum(I)) / sum(O)`. The log
is never reset and goes back to 2025-11-22; `apt-cacher.err` and `apt-cacher.dbg` sit at 0 bytes and
have never held anything.

**Quoting awk through `ssh` + `docker exec` does not work — always use the base64 route.** An inline
`awk -F"|" ...` gets mangled by the two layers of shell and fails with `unexpected character '\'`.
Base64-encode the script locally, decode it on the host, `docker cp` it in, run `awk -f`, then delete
both copies. That has worked cleanly on five runs. The container's awk does support `strftime`. For
simple end-to-end correlation, skip awk entirely and just
`sudo docker exec apt-cacher-ng grep -i <pkg> /var/log/apt-cacher-ng/apt-cacher.log`, then decode the
epochs locally with a `while IFS='|' read` loop.

## Interpreting the hit rate

**Always split the hit rate by content type before judging it.** Classify `.deb`/`.udeb` as package
and `InRelease|Release|Packages|Sources|Contents|dep11|by-hash|.gz|.xz|.bz2` as metadata. Metadata is
near-permanently a miss because index files change upstream constantly, so a quiet week with little
package traffic makes the headline rate collapse even though nothing is wrong. The 7-day aggregate
also swings as past bursts enter and age out of the rolling window. Judge the package figure against
its lifetime value instead. **A burst of new traffic depresses the short-window package rate**, since
unseen packages must be fetched once before they can ever be hits — 2026-08-22's +5.8 GB day dropped
7-day package hit rate 73.7% -> 68.4% while the lifetime figure barely moved (78.5% -> 77.8%). That
is healthy cache filling, not degradation; confirm it by checking that cache size and `.deb` count
grew over the same interval.

**Daily cache expiration is normal.** `/etc/cron.daily/apt-cacher-ng` fires
`/?doExpire=Start+Expiration&abortOnErrors=aOe` from `172.18.0.1` (the docker bridge gateway, i.e.
the host itself) at about 06:25 UTC. These appear as ordinary `O` lines from a client IP that is not
a real client — exclude `172.18.0.1` from client rankings. Expiration is not eating the cache.

**Two runs close together will show near-identical lifetime statistics.** Do not read that as a
frozen log or broken counter — confirm the log's `last=` timestamp is current (the awk script prints
it) and that the line count moved.

## End-to-end test

This client is `dev1` / 192.168.100.20 (arm64 Raspberry Pi, Debian bookworm), proxy set in
`/etc/apt/apt.conf.d/01proxy` for `Acquire::http::Proxy` only — there is no https proxy line, so
https sources bypass the cacher by design. Correlate by epoch against the access log: a lone `O` line
is a hit, an `I`+`O` pair is a miss. Download speed corroborates but does not prove — treat the log
correlation as the proof.

Packages already burned as test subjects (cached now, will only ever show hits): `sl`, `cowsay`,
`toilet`, `boxes`, `figlet`, `cmatrix`, `sysvbanner`. **Next run use `nyancat`**; `oneko`, `aview`
and `lolcat` were also confirmed uncached and installable as of 2026-08-22 and make good reserves.
**Confirm the candidate actually exists on the client first** with `apt-cache policy <pkg>` — the
08-21 run nominated `banner`, which is not a package in bookworm, and the 08-22 run had to pick a
replacement mid-test. Then confirm it is absent from the cache with
`sudo find /mnt/aptcacher -name "<pkg>_*.deb"` — search **arch-agnostically**, since `cowsay` is arch
`all` and an `arm64`-only filename search wrongly reports it as uncached. Download into `/tmp/e2e`
and delete the directory afterwards, leaving both it and the runbook directory clean.

## Log delivery to GitLab — direct push to `main` works

`main` protection was relaxed on 2026-08-20, and `git push origin HEAD:main` has now succeeded on
three consecutive runs with the `agent` token from `.env` (Developer level, scopes include
`write_repository`, expires 2027-08-20). Workflow: clone with
`https://oauth2:$GITLAB_ACCESS_TOKEN@...`, add the log under `aptcacher/`, append a one-line dated
entry to the README's `## Run log` section (the rest of that README is the stock GitLab template —
leave the boilerplate alone), commit, push. Verify afterwards via
`/api/v4/projects/alex%2Flogs/repository/tree?path=aptcacher` that the new file is present and no
pre-existing log changed. Note the same repo also receives `cleanup/` logs from another agent, so
expect unrelated README entries between runs. If protection is ever restored, fall back to a branch
plus merge request. **Do not attempt to unprotect `main` or raise the token's own access level** —
that is a permissions change for a human. The committed log is written by this agent as a
self-contained report, not copied from the partially-written `tee` output, because the final summary
is not in that file at commit time.

## Discord report

POST a JSON embed to `DISCORD_WEBHOOK_URL` from `.env`; a successful send returns **HTTP 204 with an
empty body**, so do not treat the empty response as a failure. Validate the JSON locally with
`python3 -c "import json;json.load(...)"` before posting — a malformed payload returns 400 with an
unhelpful message.

## Baselines from 2026-08-22 12:20 UTC

Host up 6d12h, load 0.01, 1.5 GB of 1.9 GB available, no swap. Container up 3h (see daemon-restart
note above), `RestartCount` 0. Cache **19G** on NFS (`nas.batcave.local:/volume1/aptcacher`, 3.5T,
28% used, 2.6T free); root fs 48G, 23% used, 36G free — NFS reports zero inodes so `df -i` is
meaningless there. Access log **103,440 lines** / 12.95 MB (was 100,790 on 08-21 17:17; +2650).
Cached `.deb`/`.udeb` **6190** (was 5454; +736). Lifetime **115.24 GB served / 36.23 GB upstream /
68.6%** (package 77.8%, metadata 28.6%) — up from 109.42 GB. Last 7 days 7.32 GB / 2.79 GB / 61.9%
aggregate, package **68.4%**, metadata 15.9%. Real errors last 7 days **0** (the four 2026-08-14
entries aged out of the window); lifetime real errors 2081 over nine months. Report-page probes
49 -> **50**. Top clients: 192.168.2.71 (50.32 GB), .88 (15.64 GB), .105 (14.32 GB), then .98, .14,
.91, .100.
