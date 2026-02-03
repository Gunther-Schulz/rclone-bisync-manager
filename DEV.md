Quick reference for setting up, running, and testing the app locally.

---

## Setup

**Venv and install:**

```bash
python -m venv .venv
source .venv/bin/activate   # Bash/Zsh (Linux/macOS)
# source .venv/bin/activate.fish  # Fish
# .venv\Scripts\activate          # Windows
pip install -e .
```

**With tests (pytest):**

```bash
pip install -e ".[dev]"
```

**Fish shell (full dev setup + hook):**

```fish
python -m venv .venv
source .venv/bin/activate.fish
pip install -e ".[dev]"
git config core.hooksPath githooks
```

**Tray (system deps):** GTK3, AppIndicator, libnotify — see [ARCH_AND_AUR_DEPENDENCIES.md](ARCH_AND_AUR_DEPENDENCIES.md) for Arch packages.

---

## Run

**CLI** (from repo root or after `pip install -e .`):

- `rclone-bisync-manager daemon start|stop|status|reload` — daemon
- `rclone-bisync-manager sync [job ...]` — one-off sync (`--resync`, `--force-bisync` optional)
- `rclone-bisync-manager add-sync JOB ...` — queue jobs while daemon runs
- `rclone-bisync-manager --version` — show version

**Global options:** `--config PATH`, `-d`/`--dry-run`, `--console-log`

**Tray:** `rclone-bisync-manager-tray`  
Options: `--config PATH`, `--log-level DEBUG|INFO|...`, `--icon-style 1|2`, `--icon-thickness N`, `--enable-experimental`

**Debug:** `--console-log` for daemon/sync (logs to stdout); `--log-level DEBUG` for tray.

---

## Tests

- **Run:** `pytest tests/ -v` (from repo root; needs `pip install -e ".[dev]"`).
- **Pre-commit hook:** Install once so tests run before each commit:

  ```bash
  git config core.hooksPath githooks
  ```

  Commit is aborted if tests fail. Skip once: `git commit --no-verify`.

**Python version:** Requires Python 3.12+. Optional: Python 3.14+ free-threading (PEP 703) may affect threading assumptions; not required for current usage.
