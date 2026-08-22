# RUN-NOTES.md — fleet maintenance, accumulated findings

Facts established by previous runs — verify rather than trust, but start here.

This file is owned by the agent. Add what you learn, refresh the last-run summary at the bottom, and
delete anything that has become obsolete so the file stays streamlined. The standing procedure lives
in `CLAUDE.md` and is maintained by a human — do not edit it. **No secrets or personal information
in this file**, same rule as everywhere else.

*Last updated 2026-08-22 12:17 UTC (seeded from the 2026-08-22 run log).*

## Scope and expected exit codes

The playbook runs against `homelab:k8s` — 22 hosts in inventory, of which roughly 15 have been
reachable on recent runs.

**Exit code 4 with zero task failures is a normal, successful run.** Ansible returns 4 when any host
is unreachable, so the exit code alone does not distinguish "some hosts were off" from "tasks
failed". Read the PLAY RECAP, not just `$?`, and keep unreachable hosts in their own section of the
log.

## Persistently unreachable hosts

As of 2026-08-22: `ai` (connection timed out), and `k8slb`, `quiz`, `si`, `tk`, `tkw1`, `tkw2` (no
route to host). These are recorded and carried into "Actions required" — per `CLAUDE.md` they are
never retried, investigated, or chased. Note whether the set changes between runs; a host moving in
or out of this list is worth a line in the log.

## Recurring findings that need a human

These have appeared in past runs and are not something this agent can fix — the playbook is the only
sanctioned action, and none of these are addressed by it.

- **Reboot required.** Routinely reported on a large fraction of the fleet after upgrades (11 hosts
  on 2026-08-22: apt, db, gitlab, kali, kw1, kw2, pi5-rivers, pihole3, rustdeck, shf, testbox).
  Updates are installed but inactive until reboot. Always list these; never reboot.
- **`mnt-nas.mount` failed on pi5-svr1 and pi5-svr2.** The identical failure on both hosts points at
  the NAS export rather than the Pis. Anything depending on `/mnt/nas` — backups in particular —
  should be assumed silently dead while this persists.
- **kw1 and kw2 low on disk.** Down to ~12 GB free on `/` on 2026-08-22, *after* the prune, so the
  remainder is real data. Both are k8s workers heading toward disk-pressure eviction. Track the
  figure run to run; a continued fall is the escalation signal.
- **NTP not synchronised on kali.**
- **Zombie processes** on pi5-svr1 (2) and pi5-rivers (1), both with very long uptimes (~880h /
  ~855h). Benign at this count, but worth watching for growth.

## `tasks.yml` — unpinned remote script (open concern, raised 2026-08-22)

`tasks.yml` includes a task that pipes `cleanup.sh` from a GitHub `main` branch into `sudo bash` on
every host. The version reviewed on 2026-08-22 was clean: no network egress, no obfuscation, and the
data-destroying `--volumes` flag deliberately not passed. The concern is not that version but that
the fetch is **unpinned** — whatever sits at that URL at run time executes as root fleet-wide, so a
future change to that repo lands unreviewed. Pinning to a commit SHA, or vendoring the script with
`ansible.builtin.copy`, closes it. The same change also relaxed `upgrade: dist` to `upgrade: yes`,
which holds back upgrades requiring package add/removal.

This is recorded for the user's decision. `CLAUDE.md` forbids editing `tasks.yml`, so do not act on
it — restate it under "Actions required" only while it remains open.

## Log delivery

Push to `main` of `https://gitlab.labjunkie.org/alex/logs.git` has been working. The same repo also
receives `aptcacher/` logs from another agent, so expect unrelated entries in the README's
`## Run log` section between runs — leave them alone.

Discord: a successful webhook POST returns **HTTP 204 with an empty body**; do not read the empty
response as a failure.

## Last run — 2026-08-22 12:11–12:13 UTC

Exit code 4 (unreachable only), **zero task failures**. 15 reachable hosts, all 15 tasks completed on
every one: Docker prune, apt update/upgrade/autoremove --purge, journal vacuum, `/tmp` sweep, and the
cleanup script. Playbook `sha256` identical before and after the run, so nothing changed mid-flight.
Log pushed as `cleanup/execute-20260822-121724.log` with the secret scan run first and clean.
