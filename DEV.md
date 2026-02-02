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

## Architecture notes (Python 3.14 / free-threading)

The current design uses global mutable state (e.g. `config`, `scheduler`, `get_sync_state_store()`) and module-level locks. Moving toward injected services and less global state would make it easier to adopt free-threading (PEP 779) or run the daemon loop and status server in a free-threaded environment later.