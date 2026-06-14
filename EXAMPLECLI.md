# `press` — noun-verb CLI

`press` is the gh-style entry point for this project. Commands follow a
`press <noun> <verb>` shape and share one set of global flags, one output
contract, and structured logging out of the box.

## Architecture

The package is split into three layers under `src/template_press/`:

| Layer | Path | Role |
|-------|------|------|
| Library (`core`) | `core/` | Pure logic + Pydantic models. No printing. Reused by every front-end. |
| CLI (`cli`) | `cli/` | Thin presentation: formats `core` results. One module per noun in `cli/commands/`. |
| Web (`web`) | `web/` | FastAPI service behind the `web` extra — same models, second front-end (`just serve`, `just test-web`). See [EXAMPLEWEB.md](EXAMPLEWEB.md). |

The result of every command is a Pydantic model in `core/models.py` — that
model *is* the JSON representation, and the renderer turns the same object into
human text, JSON, or Markdown.

## Global flags (on every command)

| Flag | Purpose |
|------|---------|
| `-o, --output [text\|json\|markdown]` | output format (default `text`; env `PRESS_OUTPUT`; config `output.format`) |
| `--json` | shorthand for `--output json` |
| `--output-file PATH` | write results to a file instead of stdout (format still set by `--output`) |
| `-v, --verbose` | raise console log level (`-v` info, `-vv` debug) |
| `-q, --quiet` | lower console log level to error |
| `--log-level LEVEL` | explicit console level, overrides `-v`/`-q` (env `PRESS_LOG_LEVEL`) |
| `--log-file [PATH]` | enable rotating file logging; bare flag uses the XDG state path (env `PRESS_LOG_FILE`) |
| `--no-color` | force color off (`NO_COLOR` env and config `output.color` also honored) |
| `--config PATH` | path to a TOML config file (overrides discovery; env `PRESS_CONFIG`) |
| `--token TEXT` | Py token (overrides `$PRESS_TOKEN`; never stored on disk) |
| `--no-input` | never prompt; fail instead (scripts/CI) |
| `-V, --version` | version + Python + platform (root) |
| `-h, --help` | help at every level |

## Output contract

- **Results** → stdout (pipe-safe), or the `--output-file` path when given.
  **Logs, messages, errors** → stderr, always.
- In `--json` mode, stdout is clean parseable JSON; errors become a structured
  `{"error": {"code", "name", "message", "error_code", …}}` object on stderr
  (`hint` and `traceback_path` appear when available; keys are append-only).
- Format never auto-switches on TTY: piped output formats the same as
  interactive output unless `-o`/`PRESS_OUTPUT`/config says otherwise.
- Color: auto-detected from the TTY; `--no-color` > `NO_COLOR` env >
  `output.color` config (`auto`/`always`/`never`) > auto-detect.
- **Pager**: interactive `text` output taller than the terminal pipes through
  `PRESS_PAGER` > `PAGER` > `less -FRX` (set-but-empty disables, git-style).
  Never when piped, with `--output-file`, in JSON/Markdown mode, or under
  `--no-input`; a missing pager binary falls back to plain output.
- **Terminal niceties** (text mode on a terminal only): cells may carry OSC-8
  hyperlinks and relative times via each model's `table_rows_rich()`
  (helpers in `core/format.py`). JSON stays raw fields + ISO-8601 UTC;
  Markdown uses the plain rows.

## Exit codes & error codes

Both tables are **stable and append-only** — scripts depend on them.
Exit codes are coarse (what should the shell do); error codes (`PRESS###`)
are fine-grained (what exactly happened) and may share an exit code. Human
output prints the error code after the message plus an actionable `hint:`
line when one exists; JSON carries them as `error_code` / `hint`.

| Exit | Meaning      | Error code | Meaning                                |
|------|--------------|------------|----------------------------------------|
| 0    | success      | —          |                                        |
| 1    | config error | `PRESS001`  | configuration missing/invalid          |
| 2    | auth error   | `PRESS002`  | token missing/rejected                 |
| 3    | API error    | `PRESS003`  | remote call failed                     |
| 4    | I/O or bug   | `PRESS000`  | unexpected error (see crash log)       |
| 5    | interrupted  | `PRESS004`  | Ctrl-C / aborted prompt                |

Unexpected errors (`PRESS000`) always append the full traceback to
`<state>/press/press_crash.log` and print `full traceback: <path>` — nothing is
lost even without `--verbose`. Mistyped commands get git-style
"Did you mean …?" suggestions at every level.

## Usage

```bash
# Projects (noun) → list / get (verbs)
press projects list
press projects list --workspace "My Workspace" --json
press projects list -o markdown
press projects get 12345

# Config — set/get non-secret keys by dotted path (no network required)
press config init                                 # guided setup (prompts on stderr)
press config init --yes                           # accept current values, no prompts
press config path
press config get output.color
press config set logging.level info               # writes [logging] level
press config set output.color always --dry-run    # preview, write nothing
press config set logging.file_level debug --yes   # skip the overwrite prompt
# the token is NEVER stored in config — pass --token or set $PRESS_TOKEN
press config get token --json                     # masked; resolves from flag/env

# Diagnose setup (Python/platform, config file, token). Exits non-zero on errors.
press doctor
press doctor --json
press doctor --bundle --json   # redacted snapshot to paste into a bug report

# Shell completion (bash, zsh, fish)
press completion bash >> ~/.bashrc
eval "$(press completion zsh)"
press completion fish > ~/.config/fish/completions/press.fish
```

Mutating commands (e.g. `config set`, `config init`) share a safety pattern:
`--dry-run` previews the change, an overwrite prompts for confirmation on
stderr, and `--yes` / `--no-input` make it non-interactive (the latter refuses
rather than prompting).

## Configuration file (TOML, XDG)

`press` reads a TOML config file from an XDG-compliant location, namespaced
under the app and named so its purpose is obvious:

```
~/.config/press/press_config.toml          # $XDG_CONFIG_HOME/press/press_config.toml
```

```toml
# press_config.toml — non-secret settings only, organized into tables
[output]
format = "text"   # text | json | markdown
color  = "auto"   # auto | always | never

[logging]
level = "warning" # console level
```

Config is discovered in layers, each overriding the previous: system
(`$XDG_CONFIG_DIRS`) → user (`$XDG_CONFIG_HOME`) → project
(`./press_config.toml`); `--config` overrides discovery entirely. Per-setting
precedence: flag → env (`PRESS_*`) → project → user → system → default.

Secrets are **never** stored here — the token resolves from `--token` or
`$PRESS_TOKEN` only. The same XDG convention applies to other file kinds
(resolved in `core/paths.py`): data → `$XDG_DATA_HOME/press/press_db.db`,
state/logs → `$XDG_STATE_HOME/press/press.log`, cache → `$XDG_CACHE_HOME/press/`.

On **Windows** the XDG variables still win when set, but the defaults are
platform-native: config → `%APPDATA%\press`, data/state → `%LOCALAPPDATA%\press`,
cache → `%LOCALAPPDATA%\press\Cache` (matching `platformdirs` conventions).

First run: when no config file exists anywhere and stderr is an interactive
terminal, a one-time hint (recorded by a state marker) points at
`press config init`. It never appears for scripts (`--no-input`, `-q`,
piped stderr, JSON mode).

## Structured logging (dual sink)

Logging uses [`structlog`](https://www.structlog.org/) rendered through stdlib
handlers, giving two independent sinks:

- **Console (stderr, always on)** — human-friendly colored output on a TTY,
  one-JSON-object-per-line when piped or in CI. Level: `WARNING` by default;
  `-v` info, `-vv` debug, `-q` error, `--log-level` explicit override
  (also `PRESS_LOG_LEVEL` / config `logging.level`).
- **Rotating file (off by default)** — enabled by `--log-file [PATH]`,
  `$PRESS_LOG_FILE`, or config `logging.file`. Bare `--log-file` writes to
  `$XDG_STATE_HOME/press/press.log` (logs are *state*, not config). Rotates at
  10 MB x 5 backups. Its level (`logging.file_level`, default `debug`) and
  format (`logging.format`: `text` or `json` JSONL; env `PRESS_LOG_FORMAT`)
  are independent of the console.

When both sinks are active they attach to the same logger: the logger floor is
the most verbose sink and each handler filters independently — e.g. a quiet
console at `warning` while the file captures full `debug` detail.

```bash
press doctor -vv                          # debug detail on stderr
press doctor --log-file                   # + JSONL/text file under XDG state
press doctor --log-file /tmp/run.log --log-level error   # quiet console, full file
press config set logging.file_level info --yes           # tune the file sink
```

Results on stdout are never mixed with logs — `press ... --json | jq` stays
safe at any verbosity.
