```bash
python -m venv .venv
# Activate (use one):
source .venv/bin/activate      # Bash/Zsh (Linux/macOS)
source .venv/bin/activate.fish # Fish
# .venv\Scripts\activate       # Windows (cmd/PowerShell)
pip install -e .
```

## How to run

**CLI** (after `pip install -e .`):
- `rclone-bisync-manager daemon start|stop|status|reload` — daemon lifecycle
- `rclone-bisync-manager sync [job ...]` — run sync (optionally `--resync`, `--force-bisync`)
- `rclone-bisync-manager add-sync JOB ...` — queue job(s)

**Global options (CLI):** `--console-log` (log to console), `-d`/`--dry-run`, `--config PATH`

**Tray:** `rclone-bisync-manager-tray`  
Options: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL` (default NONE), `--enable-experimental`, `--config PATH`, `--icon-style 1|2`, `--icon-thickness N`

**Debug:** Use `--console-log` for daemon/sync so logs go to stdout; use `--log-level DEBUG` (or INFO) for the tray.

## Pydantic usage

- **Config validation:** `config.py` defines Pydantic v2 models (`ConfigSchema`, `SyncJobConfig`, `OptionsValidatorMixin`) used only for loading and validating YAML + CLI merge. The runtime `Config` class holds the validated `_config` (a `ConfigSchema` instance) and mutable state (paths, log state, args). Schema and runtime are kept separate.
- **Serialization:** `status_server.py` uses `BaseModel` only to detect Pydantic models when building JSON (`.model_dump()`). No Pydantic models are used for status payloads; status is plain dicts.
- **Dependency:** `pydantic>=2.8,<3`; code assumes v2 API (`model_json_schema`, `model_dump`, `Field(ge=..., le=...)`, `field_validator` with `info`).

## Architecture notes (Python 3.14 / free-threading)

The current design uses global mutable state (e.g. `config`, `scheduler`, `get_sync_state_store()`) and module-level locks. Moving toward injected services and less global state would make it easier to adopt free-threading (PEP 779) or run the daemon loop and status server in a free-threaded environment later.