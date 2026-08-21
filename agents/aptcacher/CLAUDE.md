# CLAUDE.md — APT Cacher Technician Runbook

## Mission

You are the technician responsible for keeping the APT caching proxy healthy, available, and effective.

Every run has three objectives, in order:

1. Confirm the cacher service is running and reachable.
2. Assess its performance — cache hit rate, storage headroom, error volume.
3. Prove end-to-end that a package request from a client is genuinely served through the cacher.
4. Keep this CLAUD.md up to date with any notes you want for the next run.
5. Store a log of what you have done with any actions you need me to do in 'https://gitlab.labjunkie.org/alex/logs.git'. The log needs to be stored in a folder called 'aptcacher'. The log needs to be stored in the format 'execute-$(date +%Y%m%d-%H%M%S).log'. Do not remove any logs or overwrite any logs. Each execute you are to commit and push the log to the repo. The access token is located .env in this directory. Update the repo README.md with a single line entry of the date time the execute ran.

Operate conservatively. Prefer read-only diagnostics, make one change at a time, and re-verify after every change. Never report a check as passed unless you ran it and read the output; an unattempted check is "not verified", not "healthy".

Keep this CLAUDE.md streamlined and to the point when you make updates to it, removing absolete information to avoid it becoming to large.

## Environment

- Cacher host: see .env in this directory.
- SSH access: see .env in this directory.
- Deployment: the cacher runs as a Docker container on that host
- Client under test: the machine this runbook executes on
- Expected proxy port: `3142` (the apt-cacher-ng default — confirm it rather than assume it)

Treat the contents of ssh keys and usernames as secret. Never print the key, copy it into logs or output, or transfer it off the host.

## Operating rules

- You run non-interactively via `execute.sh`, with output captured to a log file. Never wait for input, and never launch an interactive pager or editor — append `| cat` to anything that might page.
- Establish facts before acting. Identify the actual container name, image, port mapping, and cache volume from the running system rather than assuming them.
- Restarting the container is acceptable remediation when the service is down. Anything destructive — deleting the cache volume, editing configuration, pulling a new image — must be reported as a recommendation instead of performed.
- If a diagnostic is ambiguous, report the ambiguity. Do not guess and do not paper over it.

## Health checks

Run these in order against the cacher host over SSH. Record the actual output of each.

1. **Host reachability.** Confirm SSH succeeds, then check uptime, load average, and memory. A cacher on a thrashing host will look healthy while serving badly.
2. **Container state.** List the container and confirm it is running rather than restart-looping. Check its uptime, restart count, and health status if the image defines a healthcheck.
3. **Port and listener.** Confirm the container's published port is bound on the host and that the proxy answers an HTTP request on it.
4. **Recent logs.** Read the container's recent log output and quantify errors and warnings. Look specifically for upstream fetch failures, permission errors on the cache directory, and disk-full messages.
5. **Storage.** Check free space on the filesystem backing the cache volume, and the current size of the cache itself. Falling below roughly 15% free warrants a flag in your report.

## Performance assessment

apt-cacher-ng publishes a statistics page, conventionally at `http://<host>:3142/acng-report.html`. Retrieve it and extract:

- Cache hit rate, as a proportion of requests served from cache versus fetched upstream.
- Total cache size and how it has moved since the previous run, if an earlier log is available in this directory.
- Any counted errors.

A hit rate that is low while client traffic is high usually means clients are bypassing the proxy, or the cache was recently cleared — distinguish between those two before recommending anything.

If the report page is not available, say so plainly and fall back to deriving hit and miss counts from the container logs.

## End-to-end verification

A healthy-looking daemon does not prove packages flow through it. Verify from this machine:

1. Confirm this client is actually configured to use the proxy — inspect `/etc/apt/apt.conf.d/` for an `Acquire::http::Proxy` setting pointing at the cacher.
2. Note the current time so you can correlate against the cacher's logs.
3. Remove any locally cached copy of your test package so the request must leave the machine.
4. Download a small, low-risk package with `apt-get download <package>`, or `apt-get install --reinstall --download-only <package>`. Download only — never install, remove, or upgrade packages on the client as part of a test.
5. Confirm the request appears in the cacher's logs at the expected time, and note whether it was served as a hit or a miss.
6. Repeat the same download once more. The second request must register as a cache hit; if it does not, the cacher is accepting requests but not retaining them, which is a fault worth reporting prominently.
7. Clean up the downloaded `.deb` from the working directory.

Step 5 is the one that actually proves the path. A successful download alone proves nothing — the client may have reached the internet directly.

## Reporting

Close every run with a concise summary, in this shape:

- **Overall status** — one of healthy, degraded, or failed.
- **Per-area results** — host, container, port, logs, storage, hit rate, end-to-end test. State the observed value for each, not just a tick.
- **Actions taken** — every command that changed state, or "none" if the run was read-only.
- **Recommendations** — anything you deliberately did not do, and why it needs a human.

State failures plainly and include the relevant output. A run that found a problem and reported it accurately is a successful run.

Keep this CLAUDE.MD file up to date with any notes you want for the next run.

## Run notes (last updated 2026-08-20, third run of the day 20:32 UTC)

Facts established about this deployment — verify rather than trust, but start here.

**Access.** The `alex` account on `apt.labjunkie.org` is *not* in the `docker` group, but has
passwordless sudo. Every docker command needs `sudo docker`. The host is Kali Rolling, hostname
`apt`, on an Ubuntu 6.8 kernel, 1.9 GB RAM and no swap.

**Container.** Name `apt-cacher-ng`, image `aptcachernas:nfs-safe`, restart policy `always`, no
healthcheck defined. Published ports are `3142->3142` **and `80->3142`**. Its command line is
`apt-cacher-ng ForeGround=1 SocketPath= PassThroughPattern=^.*:443$`. Mounts: `/home/alex/acng.conf`
and `/home/alex/zzz_override.conf` (both read-only) into `/etc/apt-cacher-ng/`, and the cache at
`/mnt/aptcacher` -> `/var/cache/apt-cacher-ng`. The host rebooted 2026-08-16 00:09 UTC and the
container came back cleanly with it; `RestartCount` has stayed 0, so a non-zero count is a real
signal, not accumulated noise.

**The config files are not being read — known open fault, still present 2026-08-20.** The command
line omits `-c /etc/apt-cacher-ng`, and this build reads no config directory by default. Verified by
running the daemon in a sandbox (temp port, temp CacheDir) with and without `-c`: without it, startup
is silent and `/acng-report.html` returns 503, exactly matching the live daemon; with it, the mounted
config is parsed. Consequences: `ReportPage`, all `Remap-*` rules, and everything in
`zzz_override.conf` (`DlMaxRetries: 10`, `ResolveIPv6: 0`) are inert. `SocketPath` and
`PassThroughPattern` survive only because they are passed as arguments. Caching itself is unaffected
because `CacheDir`'s built-in default happens to match the bind mount.

**Do not "fix" this by adding `-c` alone.** `acng.conf` contains `ExThreshold: 4G`, which is invalid —
`ExThreshold` is a number of *days* (default 4), not a size. With that line present the daemon prints
`Bad value for ExThreshold option` and `Error reading main options, terminating.` and does not start.
Both changes must land together, and both are config edits, so they are recommendations for a human,
not actions for this runbook. `backends_debian`, `backends_ubuntu` and `backends_debvol` are all
0 bytes and will emit `No configuration was read from file:` warnings once the config is actually read.

**Report page.** Expect `503 Host not found` at `/acng-report.html` until the above is fixed. Note
that each probe writes its own `E` line into the access log, so do not count those as service errors —
subtract URLs matching `acng-report` before reporting an error count. `/style.css` returns 200
(SupportDir is served) and `/` returns 406 with the usage page — both normal, on port 3142 and 80 alike.

**Deriving statistics without the report page.** `docker logs` is useless: it contains only
`Not creating Unix Domain Socket, fifo_path not specified` messages emitted *without newlines*, so
`wc -l` and `grep -c` both return 0 even on non-empty output. Use `grep -o` if you must count there.
Also note `docker logs --since 7d` is **rejected** — Docker wants a Go duration, so use `--since 168h`.
The real data is inside the container at `/var/log/apt-cacher-ng/apt-cacher.log`, format
`epoch|type|bytes|client|url`, where `I` = fetched from upstream, `O` = sent to client, `E` = error.
Volume hit rate is `(sum(O) - sum(I)) / sum(O)`. The log is not reset on restart and goes back to
2025-11-22 (100,566 lines / 12.6 MB as of this run). `apt-cacher.err` and `apt-cacher.dbg` are empty.
Quoting an awk script through `ssh` + `docker exec` is painful; base64-encode the script locally,
decode it on the host, `docker cp` it in, then run `awk -f`. That worked cleanly twice this run.

**Always split the hit rate by content type before judging it.** The aggregate number is dominated by
traffic mix and will mislead you. Classify `.deb`/`.udeb` as package and
`InRelease|Release|Packages|Sources|Contents|dep11|by-hash|.gz|.xz|.bz2` as metadata. Metadata is
near-permanently a miss because index files change upstream constantly, so a quiet week with little
package traffic makes the headline rate collapse even though nothing is wrong. That is exactly what
happened this run — see baselines below.

**Daily cache expiration is normal.** `/etc/cron.daily/apt-cacher-ng` fires
`/?doExpire=Start+Expiration&abortOnErrors=aOe` from `172.18.0.1` (the docker bridge gateway, i.e. the
host itself) at about 06:25 UTC. 268 such runs are in the log. They appear as ordinary `O` lines from
a client IP that is not a real client — exclude `172.18.0.1` from client rankings. Expiration is not
eating the cache: it grew 16G -> 17G across the last six days.

**Baselines from this run (2026-08-20).** Cache 17G on NFS (`nas.batcave.local:/volume1/aptcacher`,
3.5T, 28% used, 2.6T free); host root fs 48G, 22% used. NFS reports zero inodes, so `df -i` is
meaningless there — ignore it. Lifetime hit rate 68.7% over 109.26 GB served / 34.15 GB upstream
(was 69.0% over 107.90 GB on 2026-08-14 — flat, as expected). Last 7 days 50.6% over just 1.72 GB.
**That is not a regression**: the 2026-08-14 figure of 97.9% covered a 30.35 GB burst of package
downloads, whereas this window is 58% metadata by volume. Split out, package hit rate was 75.0% for
the week against 78.5% lifetime, and metadata 32.8% against 28.7% lifetime — both steady or better.
2126 lifetime errors, of which 45 are report-page probes and 2081 real, almost all historical upstream
503s on Ubuntu kernel packages; only 4 real errors in the last 7 days and none since the previous run.
Cache holds 5439 `.deb` files across 12 upstream repos, largest being `gb.archive.ubuntu.com` 8.8G and
`kali.download` 4.8G. Busiest real client remains 192.168.2.71 (50.32 GB lifetime), then 192.168.2.88
and 192.168.2.105.

**Baselines from the 2026-08-20 19:23 UTC run (unchanged from the 11:26 run — a genuinely quiet
window).** Host up 4d19h, load 0.08, 1.5 GB of 1.9 GB available, no swap pressure. Container up
4 days, `RestartCount` still 0, started 2026-08-16 00:09 UTC. Cache 17G, now **5440** `.deb` files
(+1 = the previous run's `toilet` test). NFS 3.5T, 28% used, 2.6T free; root fs 48G, 22% used —
both far above the 15%-free flag. Lifetime figures were byte-identical to the morning run
(109.26 GB served / 34.15 GB upstream / 68.7%), and the access log grew by only 4 lines between
runs, which is itself the confirmation that the flat numbers are real and not a stuck counter.
Real errors in the last 7 days remain **4**, all timestamped 2026-08-14, none since. Report-page
probes rose 45 -> 46 as expected because each health check writes its own `E` line.
Top clients unchanged: 192.168.2.71 (50.32 GB), .88 (14.69 GB), .105 (12.37 GB).

**Two runs on the same day will show identical lifetime statistics.** Do not read that as a frozen
log or a broken counter — verify it by checking that the log's `last=` timestamp is current (the awk
script prints it) and that the line count moved slightly. Both were true this run.

**Log delivery to GitLab — direct push to `main` now works (changed 2026-08-20).** Earlier runs
could not push: `main` was protected requiring **Maintainer** (level 40) while the `agent` token in
`.env` (scopes include `write_repository`, expires 2027-08-20) holds **Developer** (level 30), so the
2026-08-20 19:23 run had to use a branch plus merge request (branch `aptcacher-log-20260820-202827`,
MR !1). **A human has since merged MR !1 and relaxed the protection**: `main` now lists push access
as `Maintainers, Developers + Maintainers`, and `git push origin HEAD:main` succeeded directly on the
20:32 run. So the workflow is now simply: clone, add the log under `aptcacher/`, commit, push to
`main`. Verify afterwards via the API tree endpoint that the file is present and that no pre-existing
log changed. The branch + MR fallback above still works if protection is ever restored — check the
push result rather than assuming either way. **Do not attempt to unprotect `main` or raise the
token's own access level**; that is a permissions change for a human. Note the log file is written by
this agent as a self-contained report, not copied from the partially-written `tee` output, since the
final summary is not yet in that file at commit time.

**Baselines from the 2026-08-20 20:32 UTC run (third of the day; still a quiet window).** Host up
4d20h22m, load 0.00, 1.5 GB of 1.9 GB available, no swap. Container up 4 days, `RestartCount` still 0,
`StartedAt` still 2026-08-16T00:09:56Z. Cache 17G; **5441** `.deb` files before the test, **5442**
after (the `figlet` miss stored exactly one). NFS 3.5T, 28% used, 2.6T free; root fs 48G, 22% used,
36G free. Access log **100,574 lines** (was 100,566 at 11:26). Lifetime figures byte-identical to both
earlier runs today: 109.26 GB served / 34.15 GB upstream / **68.7%** (package 78.5%, metadata 28.7%).
Last 7 days 1.72 GB / 0.85 GB / 50.6% aggregate, but **package 75.0% and metadata 32.8%** — both at or
above lifetime, so the low aggregate is traffic mix, not a fault. Real errors last 7 days still **4**,
all 2026-08-14, **none since across three runs today**. Report-page probes 46 -> **47**, as expected.
Top clients unchanged: 192.168.2.71 (50.32 GB), .88 (14.69 GB), .105 (12.37 GB), then .98, .14, .91.
The awk-script-via-base64 + `docker cp` method worked cleanly again; note the container's awk does
support `strftime`, so timestamps can be decoded in place.

**End-to-end test.** This client is `dev1` / 192.168.100.20 (arm64 Raspberry Pi, Debian bookworm),
proxy set in `/etc/apt/apt.conf.d/01proxy` for `Acquire::http::Proxy` only — there is no https proxy
line, so the HashiCorp https source bypasses the cacher by design. Correlate by epoch with the access
log — one `O` line alone is a hit, an `I`+`O` pair is a miss. Download speed is a useful corroborating
signal, though the ratio varies with package size and upstream mirror speed: the 11:26 run's
`toilet` miss fetched at 111 kB/s against 1,094 kB/s on the hit, while the 19:26 `boxes` miss
managed 525 kB/s against 3,163 kB/s, and the 20:34 `figlet` miss 606 kB/s against 6,673 kB/s. Treat the log correlation as the proof and the speed as
corroboration only — a fast miss does not mean the proxy was bypassed.
Packages already burned as test subjects (they are cached now and will only ever show hits):
`sl`, `cowsay`, `toilet`, `boxes`, `figlet`. **Next run use `cmatrix` or `banner`** — both still
confirmed absent from the cache (searched by `<pkg>_*.deb`, arch-agnostic) as of 2026-08-20 20:34.
When those two are burned as well, find a fresh candidate the same way rather than reusing one. Check first with
`sudo find /mnt/aptcacher -name "<pkg>_*_arm64.deb"`, but beware architecture: `cowsay` is arch `all`,
so an `arm64` filename search wrongly reports it as uncached. Delete the downloaded `.deb` afterwards;
this run used `/tmp/e2e` as the download directory and removed it afterwards, leaving both it and
the runbook directory clean.
