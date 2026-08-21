# Log Viewer

You are the technician responsible for viewing the homelab agents' logs and dealing
with any issues those agents raise. This folder holds a Django app that reads the
agents' log repository and shows, for each service, the key points and the actions
required from the **most recent log only**.

**Remain within this folder for all development.**

## The brief

- Django app, run from a local `.venv`.
- Design style: [cosmic-ui](https://github.com/rizznme/cosmic-ui).
- Logs live in `https://gitlab.labjunkie.org/alex/logs.git`, one folder per service
  (`aptcacher` and `seconion` today; more will appear and must be picked up
  automatically).
- The HTTPS access token is in `.env` in this folder.
- Simple and quick: a summary card per service.
- When a new log is committed, the displayed log is cleared and replaced by the new
  one. Summaries are produced by shelling out to `claude -p --dangerously-skip-permissions`.
- Fully tested.

## Running it

```bash
./run.sh                 # gunicorn on 0.0.0.0:8000 - every interface, DEBUG off
./run.sh 0.0.0.0:9000    # a different port
DEV=1 ./run.sh           # Django's auto-reloading dev server instead, DEBUG on
```

First run creates `.venv`, installs `requirements.txt`, migrates and runs
`collectstatic`. It binds `0.0.0.0` by default, so it answers on the machine's LAN
and public addresses, not just localhost.

Gunicorn runs **one worker with eight threads**. That is deliberate: the refresh runs
in a background thread guarded by a process-local lock, so a second worker process
could start a second concurrent refresh against the same clone. Threads give all the
concurrency a dashboard like this needs. If you ever do need multiple worker
processes, the lock has to move into the database first.

Manually:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py refresh_logs           # sync + summarise now
.venv/bin/python manage.py refresh_logs --force   # re-summarise even if unchanged
.venv/bin/python manage.py refresh_logs --json    # machine-readable result
.venv/bin/python manage.py test dashboard         # 144 tests
```

The board populates itself on first visit, so `refresh_logs` is only needed for cron
or for debugging.

### Keeping it running (systemd)

Started from a terminal, the app dies with that terminal. `logviewer.service` runs
the same `run.sh` under systemd instead, so it survives logout and comes back after
a reboot:

```bash
sudo ./install-service.sh          # install, enable at boot, start now
systemctl status logviewer
journalctl -u logviewer -f         # gunicorn's access and error logs
sudo systemctl restart logviewer
```

It runs as `alex` from this directory with an explicit `PATH` that includes
`~/.local/bin`, because the Claude CLI lives there and a service has no login
shell to set it up. `Restart=on-failure` brings it back if gunicorn dies;
`TimeoutStartSec=600` allows for the first run building `.venv` on a Pi. To
uninstall: `sudo systemctl disable --now logviewer`, delete
`/etc/systemd/system/logviewer.service` and `sudo systemctl daemon-reload`.

### After changing the code

gunicorn does not watch the filesystem, so a running service keeps serving the
code it imported at start. Pick up changes with:

```bash
sudo systemctl restart logviewer   # the safe default: re-runs run.sh in full
sudo systemctl reload logviewer    # HUP: re-imports Python only, no downtime
```

`restart` re-runs `run.sh`, so it also does `pip install -r requirements.txt`,
`migrate` and `collectstatic --clear`. `reload` only respawns gunicorn's workers,
so use it for a pure Python edit and `restart` whenever dependencies, migrations,
templates that were collected, or the CSS changed. When in doubt, restart - it
costs a second or two.

To iterate without touching the service, run the dev server alongside it on
another port: `DEV=1 ./run.sh 0.0.0.0:8001`. It auto-reloads on every save and
shares the same `data/` directory and SQLite database, so only run one of them
through a refresh at a time. Run the tests before restarting the service:
`.venv/bin/python manage.py test dashboard`.

### Exposing it beyond the LAN

`DEBUG` now defaults to **off**, and WhiteNoise serves the stylesheet so static files
work without a separate web server. Before putting this on a genuinely public
address, also:

- set `DJANGO_SECRET_KEY` to a real random value;
- narrow `DJANGO_ALLOWED_HOSTS` from `*` to the hostname you actually use;
- put it behind a reverse proxy with TLS, and set `DJANGO_CSRF_TRUSTED_ORIGINS` to
  the `https://...` origin so the Refresh button keeps working.

There is no authentication on the dashboard. Anyone who can reach the port can read
every log and trigger refreshes.

## Layout

```
config/                     Django project
  env.py                    dependency-free .env loader
  settings.py               all tunables live here (see Configuration)
dashboard/                  the only app
  models.py                 Service, LogSummary, RefreshState
  views.py                  board, service detail, refresh, state, healthz
  services/repo.py          git access to the logs repository
  services/summariser.py    claude -p summarisation + heuristic fallback
  services/refresh.py       orchestration and the background worker
  services/cleanup.py       disk-usage reporting and pruning
  management/commands/     refresh_logs, cleanup
  templates/dashboard/      base, index, service_detail, _statusbar
  static/dashboard/css/cosmic.css
  tests/                    factories + six test modules
data/                       gitignored: clone, sqlite db, claude workdir
run.sh                      launcher (gunicorn, or DEV=1 for runserver)
logviewer.service           systemd unit, so it keeps running after logout
install-service.sh          installs and enables that unit
```

## How it works

1. **Sync** — `services/repo.py` clones `LOGS_REPO_URL` into `data/logs`, or
   `fetch` + `reset --hard origin/<branch>` + `clean -fd` if it is already there.
   The clone is treated as read-only and disposable, so a force-push upstream can
   never leave it stuck.
2. **Discover** — every top-level directory that is not hidden and not in
   `LOGS_IGNORED_DIRS` is a service. New folders appear on the board with no code
   change; folders that disappear are deleted from the board.
3. **Pick the newest log** — files ending `.log`, `.md` or `.txt` are ordered by the
   timestamp in the filename (`execute-20260821-090820.log`), falling back to the
   file's last commit date and then to its mtime. Only the newest one is ever used.
4. **Summarise** — the log is hashed. If the hash matches the stored summary, nothing
   happens and no subprocess is spawned. Otherwise the log is piped to
   `claude -p --dangerously-skip-permissions`, which is asked for a strict JSON object
   with `status`, `headline`, `key_points` and `actions`. The reply is parsed
   defensively (bare JSON, fenced JSON, or JSON buried in prose) and normalised:
   unknown statuses and priorities are coerced to safe defaults, lists are capped.
5. **Replace** — the old `LogSummary` row for that service is deleted inside a
   transaction and the new one written, so exactly one summary exists per service.
   `RefreshState.version` is bumped.
6. **Show** — cards are sorted worst-status-first (critical, warning, unknown,
   healthy).

The Claude CLI is run with `cwd` set to `data/claude-workdir`, deliberately outside
this project, so it does not pick up *this* CLAUDE.md and answer as the technician
instead of returning JSON.

### Picking up new logs automatically

The browser polls `/api/state/` every `LOGVIEWER_BROWSER_POLL_SECONDS` (20s). That
endpoint, at most once every `LOGVIEWER_POLL_SECONDS` (120s), runs `git ls-remote`
and compares the remote tip with local `HEAD`. If they differ it starts a background
refresh thread. When the refresh bumps `version`, the next poll sees the change and
the page reloads itself, clearing the old log and showing the new one. The
**Refresh** button forces the same path immediately.

Only one refresh thread runs at a time; a second request is refused rather than
queued.

### When Claude is unavailable

If the CLI is missing, times out, exits non-zero, or returns something unparseable,
a deterministic heuristic summariser takes over: it scrapes the outcome line, bullet
findings, and anything under an `ACTIONS REQUIRED` / `RECOMMENDATIONS` /
`NEXT STEPS` heading, inferring priority from `PRIORITY 1`, `[MEDIUM]`, `[LOW]`
markers. The card then shows `via heuristic` and the detail page records why. The
board is never blank because a subprocess failed.

## Design

`dashboard/static/dashboard/css/cosmic.css` mirrors cosmic-ui's own `@theme` block:
primary `rgb(20,160,230)`, accent `rgb(202,65,34)`, a background of primary mixed 80%
into black, white foreground, Orbitron display type over Roboto body text, cosmic-ui's
small type scale (13.5px base) and its faint 35rem foreground grid. cosmic-ui's SVG
`Frame` decoration is reproduced with `clip-path` corner cuts: a 1px coloured outer
shape with the panel inset inside it, tinted by status. No JavaScript framework, no
build step, no CDN beyond the Google Fonts stylesheet.

Status colours: healthy teal, warning amber, critical rose, unknown grey.

### The raw log panel

Agent logs are fixed-width ASCII — box art, aligned tables, `=====` rules — so the
panel defaults to `white-space: pre` and scrolls sideways rather than wrapping and
destroying the alignment. A **Wrap** button toggles that, remembered in
`localStorage`. The panel sets its own padding instead of inheriting the frame's, so
the `<pre>` scrolls edge to edge without the frame's clipped corners cropping it, and
its height is `clamp(20rem, 100vh - 19rem, 62rem)` so it fills the viewport instead
of an arbitrary fixed height. On wide screens the summary column is `position:
sticky`, keeping the actions on screen while a long log scrolls.

## Configuration

Read from the environment, with `.env` in this folder merged in (real environment
variables win). Everything is defined in `config/settings.py`.

| Variable | Default | Purpose |
|---|---|---|
| `GITLAB_ACCESS_TOKEN` | *(from `.env`)* | HTTPS token for the logs repository |
| `GITLAB_TOKEN_USERNAME` | `oauth2` | Username paired with the token |
| `LOGS_REPO_URL` | `https://gitlab.labjunkie.org/alex/logs.git` | Upstream repository |
| `LOGS_REPO_BRANCH` | `main` | Branch to follow |
| `LOGS_REPO_DIR` | `data/logs` | Local clone |
| `LOGS_CLONE_DEPTH` | `50` | Commits kept in the clone; `0` for full history |
| `LOGVIEWER_DATA_DIR` | `data` | Clone, SQLite db and Claude workdir |
| `CLAUDE_COMMAND` | `claude -p --dangerously-skip-permissions` | Summariser command |
| `CLAUDE_TIMEOUT_SECONDS` | `300` | Per-log summariser timeout |
| `CLAUDE_MAX_LOG_CHARS` | `60000` | Log is truncated past this before summarising |
| `CLAUDE_PRUNE_TRANSCRIPTS` | `1` | Delete CLI session transcripts after summarising |
| `CLAUDE_TRANSCRIPT_KEEP` | `0` | Transcripts to keep when pruning |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Where the CLI keeps its state |
| `LOGVIEWER_POLL_SECONDS` | `120` | Minimum gap between remote checks |
| `LOGVIEWER_BROWSER_POLL_SECONDS` | `20` | Browser poll interval |
| `DJANGO_DEBUG` | `0` | `DEV=1 ./run.sh` turns it on |
| `DJANGO_SECRET_KEY` | insecure default | Set a real one if exposed beyond the LAN |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma separated |

The token is only ever passed as a subprocess argument, never through a shell, and
`repo.scrub()` strips it (and any `user:pass@host` form) from every error message
before it can reach a template, a log line or the database. There is a test for this.

## Disk usage

Nothing here grows without limit, and the pruning is automatic — the `cleanup`
command only exists so the growth can be inspected or forced.

```bash
.venv/bin/python manage.py cleanup --dry-run   # report only
.venv/bin/python manage.py cleanup             # report and prune
.venv/bin/python manage.py cleanup --json
```

| What | Where | How it is bounded |
|---|---|---|
| Claude session transcripts | `$CLAUDE_CONFIG_DIR/projects/<workdir>` | Deleted after every summarisation |
| Git objects | `data/logs/.git` | Shallow clone (`LOGS_CLONE_DEPTH`) plus reflog expiry and `git gc` after every sync |
| Logs checkout | `data/logs` | Mirrors the remote; the viewer does not add to it |
| Summaries | `data/db.sqlite3` | Exactly one row per service, replaced in place |
| Collected static | `data/staticfiles` | `collectstatic --clear` on every start |

The transcripts are the one that mattered. The Claude CLI writes a full session
transcript per invocation — **including the entire log piped into it** — into its own
config directory, which is outside this project. At a few refreshes a day that was
tens of megabytes a year that nothing here would ever have cleaned up.
`summariser.prune_transcripts()` now runs in a `finally` block around every CLI call,
so a failing summariser cannot fill the disk either. It only ever touches the
directory belonging to this app's own private work directory.

The clone is shallow (50 commits by default). The dashboard only ever displays the
newest log, and log ordering comes from the filename timestamp, so older files
falling outside the shallow window lose nothing but their commit metadata. Set
`LOGS_CLONE_DEPTH=0` for a full clone.

`data/` is disposable in its entirety: delete it and the next refresh rebuilds it.

## Routes

| Path | Purpose |
|---|---|
| `/` | The board: one card per service |
| `/service/<slug>/` | Summary plus the full raw log |
| `/refresh/` | `POST` to start a refresh (`force=1` to re-summarise) |
| `/api/state/` | Polled by the browser; also drives automatic pickup |
| `/healthz/` | Liveness check |
| `/admin/` | Django admin over the three models |

## Tests

`.venv/bin/python manage.py test dashboard` — 144 tests, no network access and no
Claude CLI required.

- `test_env.py` — `.env` parsing, quoting, `export`, precedence.
- `test_repo.py` — clone/pull/reset against real throwaway git repos, service
  discovery, newest-log ordering, filename timestamp parsing, token scrubbing.
- `test_summariser.py` — JSON extraction from messy CLI output, normalisation of bad
  payloads, subprocess failure modes, the heuristic fallback.
- `test_refresh.py` — first run, unchanged run, new log replacing old, edited log,
  new/removed service folders, one broken service not stopping the others, refresh
  state, remote polling, the background worker, the management command.
- `test_views.py` — every route, card ordering, metrics, and an end-to-end pass over
  a real git repo with the Claude CLI deliberately absent.
- `test_cleanup.py` — transcript path derivation and pruning (including the
  keep-N and disabled cases), shallow cloning, that repeated syncs do not grow the
  object store, and the usage report.

Background-worker tests stub `threading.Thread` rather than starting a real one:
SQLite's in-memory test database cannot be shared safely across threads.

## Notes for future work

- The repository folder name is `aptcacher` (not `aptcache`).
- Adding a service needs no code change — just a new folder upstream.
- To run refreshes from cron instead of from browser polling, set
  `LOGVIEWER_POLL_SECONDS` very high and schedule `manage.py refresh_logs`.
