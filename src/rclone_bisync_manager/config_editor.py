"""GTK config editor for the tray. Uses only GTK (same stack as the tray); no tkinter."""

import copy
import logging
import re
import yaml

from rclone_bisync_manager.daemon_client import request_config_schema
from rclone_bisync_manager.logging_utils import log_message

_GTK_AVAILABLE = False
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk
    _GTK_AVAILABLE = True
except (ImportError, ValueError):
    Gdk = None
    Gtk = None

# General (top-level) fields in display order with human labels
GENERAL_FIELDS = [
    ("local_base_path", "Local base path"),
    ("exclusion_rules_file", "Exclusion rules file (optional)"),
    ("max_cpu_usage_percent", "Max CPU usage (%)"),
    ("redirect_rclone_log_output", "Redirect rclone log output"),
    ("run_missed_jobs", "Run missed jobs"),
    ("run_initial_sync_on_startup", "Run initial sync on startup"),
    ("dry_run", "Dry run (global)"),
    ("log_file_path", "Log file path"),
]

GENERAL_TOOLTIPS = {
    "local_base_path": "Base directory for local files. Sync job 'local' paths are relative to this.",
    "exclusion_rules_file": "Path to a filter file. If updated, a resync is run on next sync (rclone requires resync after filter changes).",
    "max_cpu_usage_percent": "CPU limit for rclone (0–100). Requires cpulimit; ignored if not installed.",
    "redirect_rclone_log_output": "Whether to redirect rclone log output to the daemon log file.",
    "run_missed_jobs": "If true, run jobs that would have run while the daemon was stopped.",
    "run_initial_sync_on_startup": "If true, run an initial sync for each job when the daemon starts.",
    "dry_run": "Global dry run: show what would be done without making changes.",
    "log_file_path": "Path to the daemon log file.",
}

# Sync job fields in display order with human labels (scalar only; option dicts handled separately)
SYNC_JOB_FIELDS = [
    ("local", "Local path (relative to base)"),
    ("rclone_remote", "Rclone remote name"),
    ("remote", "Remote path"),
    ("schedule", "Schedule (cron)"),
    ("active", "Active"),
    ("dry_run", "Dry run"),
    ("force_resync", "Force resync"),
    ("force_operation", "Force operation"),
]

SYNC_JOB_TOOLTIPS = {
    "local": "Path relative to local_base_path, e.g. 'my_folder'.",
    "rclone_remote": "Name of the rclone remote (as in rclone config).",
    "remote": "Path on the remote, e.g. 'path/to/folder'.",
    "schedule": "Cron expression, e.g. '*/30 * * * *' for every 30 minutes. Use the preset dropdown or enter custom.",
    "active": "Whether this job is enabled for scheduled runs.",
    "dry_run": "Dry run for this job only.",
    "force_resync": "If true, next run will do a full resync (--resync) before bisync.",
    "force_operation": "If true, next run will use --force for bisync.",
}

# Schedule presets: (cron_value, display_label)
SCHEDULE_PRESETS = [
    ("*/5 * * * *", "Every 5 min"),
    ("*/15 * * * *", "Every 15 min"),
    ("*/30 * * * *", "Every 30 min"),
    ("0 * * * *", "Hourly"),
    ("0 */2 * * *", "Every 2 hours"),
    ("0 0 * * *", "Daily (midnight)"),
    ("0 0 * * 0", "Weekly (Sunday)"),
]

# Option keys that use a dropdown instead of free text (section -> key -> list of choices).
# Values match rclone/bisync CLI: --compare, --log-level, --conflict-resolve, --conflict-loser.
OPTION_DROPDOWNS = {
    "rclone_options": {
        "compare": ["size", "modtime", "checksum", "size,modtime", "size,modtime,checksum"],
        "log_level": ["DEBUG", "INFO", "NOTICE", "WARNING", "ERROR"],
    },
    "bisync_options": {
        "conflict_resolve": ["none", "path1", "path2", "newer", "older", "larger", "smaller"],
        "conflict_loser": ["num", "pathname", "delete"],
    },
}

OPTION_TOOLTIPS = {
    "compare": "Bisync compare options (comma-separated): size, modtime, checksum. Default: size,modtime.",
    "log_level": "rclone log verbosity (DEBUG, INFO, NOTICE, WARNING, ERROR).",
    "conflict_resolve": "Auto-resolve conflicts: none, path1, path2, newer, older, larger, smaller (rclone --conflict-resolve).",
    "conflict_loser": "Action on conflict loser: num (rename with suffix), pathname (path-based suffix), delete (rclone --conflict-loser).",
}

# Canonical form for option dropdown values (case-insensitive match -> display value) for dirty comparison.
_OPTION_CANONICAL = {}
for _section_opts in OPTION_DROPDOWNS.values():
    for _choice in _section_opts.values():
        for _c in _choice:
            _OPTION_CANONICAL[_c.lower()] = _c

# Tooltips for per-job YAML option areas (keyed by option key)
SYNC_JOB_OPTION_TOOLTIPS = {
    "rclone_options": "Per-job rclone options (e.g. log_level, compare). YAML format.",
    "bisync_options": "Per-job bisync options (e.g. conflict_resolve, conflict_loser). YAML format.",
    "resync_options": "Per-job resync options. YAML format.",
}


def _set_by_path(d, path, value):
    if not path or not isinstance(path, str):
        return
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _get_by_path(d, path):
    """Get value from nested dict by path (e.g. 'sync_jobs.job1.local'). Returns None if missing."""
    if not path or not isinstance(path, str):
        return None
    keys = path.split(".")
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _safe_yaml_dump(value):
    """Serialize value for display in a text field; parse back with yaml.safe_load."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return yaml.dump(value, default_flow_style=False, allow_unicode=True).strip()
    return str(value)


def _safe_yaml_load(text):
    """Parse text back to Python value; empty string -> None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text  # fallback to string if invalid YAML


def edit_config_gtk(config_file_path):
    """Open GTK config editor for the given config file. No-op if GTK unavailable."""
    if not _GTK_AVAILABLE or Gtk is None:
        return
    with open(config_file_path, "r", encoding="utf-8", errors="replace") as f:
        config = yaml.safe_load(f.read()) or {}
    # Cache original values so Revert restores state from when editor was opened (even after Save).
    config_original = copy.deepcopy(config)
    # What we last wrote to disk (or initial load). Used for dirty indicator: current widgets vs this.
    last_saved_config = copy.deepcopy(config)
    try:
        request_config_schema()
    except Exception as e:
        dlg = Gtk.MessageDialog(
            transient_for=None, flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=f"Failed to fetch config schema: {e}",
        )
        dlg.run()
        dlg.destroy()
        return
    widgets = {}  # path -> (widget, type_str)  type: "bool"|"int"|"str"|"yaml"

    win = Gtk.Window(title="Edit Configuration")
    win.set_default_size(820, 620)
    status_label = Gtk.Label(label="Saved")
    status_label.set_margin_start(4)
    status_label.set_margin_end(4)

    nb = Gtk.Notebook()

    def _set_tooltip(widget, tooltips, key):
        if tooltips and key in tooltips:
            widget.set_tooltip_text(tooltips[key])

    def add_tab(name, section_dict, prefix, field_order=None, allow_yaml=True, tooltips=None, option_dropdowns=None):
        """Build a tab from section_dict. If field_order is given, use (key, label) list; else show all scalar keys.
        If allow_yaml, use TextView for list/dict values (type 'yaml').
        tooltips: optional dict key -> tooltip string. option_dropdowns: optional dict key -> list of choices (use ComboBox)."""
        sw = Gtk.ScrolledWindow()
        grid = Gtk.Grid()
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        sw.add(grid)
        nb.append_page(sw, Gtk.Label(label=name))
        row = 0
        if field_order:
            items = list(field_order)
        else:
            items = [(k, k.replace("_", " ").title()) for k in (section_dict or {}).keys() if not isinstance((section_dict or {}).get(k), dict)]
        for key, label in items:
            value = (section_dict or {}).get(key)
            full_key = f"{prefix}{key}" if prefix else key
            # Skip nested dicts when we're not using yaml widget (e.g. in strict field_order without allow_yaml)
            if isinstance(value, dict) and not allow_yaml:
                continue
            if isinstance(value, list) or (isinstance(value, dict) and allow_yaml):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                tv = Gtk.TextView()
                tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
                tv.set_left_margin(4)
                tv.set_right_margin(4)
                tv.get_buffer().set_text(_safe_yaml_dump(value))
                tv.set_size_request(-1, 80)
                grid.attach(tv, 1, row, 1, 1)
                _set_tooltip(tv, tooltips, key)
                widgets[full_key] = (tv, "yaml")
                row += 1
            elif isinstance(value, bool):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                w = Gtk.CheckButton()
                w.set_active(value)
                grid.attach(w, 1, row, 1, 1)
                _set_tooltip(w, tooltips, key)
                widgets[full_key] = (w, "bool")
                row += 1
            elif isinstance(value, int):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                w = Gtk.SpinButton.new_with_range(-1e9, 1e9, 1)
                w.set_value(value)
                grid.attach(w, 1, row, 1, 1)
                _set_tooltip(w, tooltips, key)
                widgets[full_key] = (w, "int")
                row += 1
            elif option_dropdowns and key in option_dropdowns:
                choices = option_dropdowns[key]
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                w = Gtk.ComboBoxText.new()
                for c in choices:
                    w.append_text(str(c))
                val_str = (str(value) if value is not None else "").strip()
                if val_str in choices:
                    w.set_active(choices.index(val_str))
                else:
                    # Case-insensitive match so "Notice" in file matches "NOTICE" in dropdown
                    val_low = val_str.lower()
                    idx = next((i for i, c in enumerate(choices) if c.lower() == val_low), 0)
                    w.set_active(idx)
                w.set_hexpand(True)
                grid.attach(w, 1, row, 1, 1)
                _set_tooltip(w, tooltips, key)
                widgets[full_key] = (w, "combo")
                row += 1
            else:
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                w = Gtk.Entry()
                w.set_text(str(value) if value is not None else "")
                w.set_hexpand(True)
                grid.attach(w, 1, row, 1, 1)
                _set_tooltip(w, tooltips, key)
                widgets[full_key] = (w, "str")
                row += 1

    # General tab: all schema fields in order with human labels and tooltips
    general = {k: config.get(k) for k in [x[0] for x in GENERAL_FIELDS]}
    add_tab("General", general, "", field_order=GENERAL_FIELDS, allow_yaml=False, tooltips=GENERAL_TOOLTIPS)

    # Sync Jobs tab: one frame per job; scalar fields + per-job option dicts as YAML text
    sync_jobs = config.get("sync_jobs", {})
    sync_sw = Gtk.ScrolledWindow()
    sync_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    sync_sw.add(sync_box)
    nb.append_page(sync_sw, Gtk.Label(label="Sync Jobs"))
    for job_name, job_cfg in sync_jobs.items():
        fr = Gtk.Frame(label=job_name)
        fr.set_margin_start(10)
        fr.set_margin_end(10)
        fr.set_margin_top(5)
        fr.set_margin_bottom(5)
        g = Gtk.Grid()
        g.set_margin_start(10)
        g.set_margin_bottom(10)
        fr.add(g)
        sync_box.pack_start(fr, False, False, 0)
        r = 0
        for key, label in SYNC_JOB_FIELDS:
            if key not in job_cfg:
                continue
            v = job_cfg[key]
            full = f"sync_jobs.{job_name}.{key}"
            g.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            if isinstance(v, bool):
                w = Gtk.CheckButton()
                w.set_active(v)
                _set_tooltip(w, SYNC_JOB_TOOLTIPS, key)
                widgets[full] = (w, "bool")
                g.attach(w, 1, r, 1, 1)
            elif key == "schedule":
                w = Gtk.ComboBoxText.new_with_entry()
                for _cron, _label in SCHEDULE_PRESETS:
                    w.append_text(_label)
                sval = str(v).strip() if v is not None else ""
                found = False
                for idx, (cron, _) in enumerate(SCHEDULE_PRESETS):
                    if cron == sval:
                        w.set_active(idx)
                        found = True
                        break
                if not found:
                    w.set_active(-1)
                    if w.get_child():
                        w.get_child().set_text(sval)
                w.set_hexpand(True)
                _set_tooltip(w, SYNC_JOB_TOOLTIPS, key)
                widgets[full] = (w, "schedule_combo")
                g.attach(w, 1, r, 1, 1)
            else:
                w = Gtk.Entry()
                w.set_text(str(v) if v is not None else "")
                w.set_hexpand(True)
                _set_tooltip(w, SYNC_JOB_TOOLTIPS, key)
                widgets[full] = (w, "str")
                g.attach(w, 1, r, 1, 1)
            r += 1
        # Per-job option dicts as YAML text areas
        for opt_key, opt_label in [("rclone_options", "Rclone options (YAML)"), ("bisync_options", "Bisync options (YAML)"), ("resync_options", "Resync options (YAML)")]:
            full = f"sync_jobs.{job_name}.{opt_key}"
            val = job_cfg.get(opt_key)
            if not isinstance(val, dict):
                val = {}
            g.attach(Gtk.Label(label=opt_label, xalign=0), 0, r, 1, 1)
            tv = Gtk.TextView()
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.set_left_margin(4)
            tv.set_right_margin(4)
            tv.get_buffer().set_text(_safe_yaml_dump(val))
            tv.set_size_request(-1, 60)
            _set_tooltip(tv, SYNC_JOB_OPTION_TOOLTIPS, opt_key)
            g.attach(tv, 1, r, 1, 1)
            widgets[full] = (tv, "yaml")
            r += 1

    # Option tabs: support list/dict via yaml; dropdowns and tooltips for known keys
    add_tab("Rclone Options", config.get("rclone_options", {}), "rclone_options.", allow_yaml=True, tooltips=OPTION_TOOLTIPS, option_dropdowns=OPTION_DROPDOWNS.get("rclone_options"))
    add_tab("Bisync Options", config.get("bisync_options", {}), "bisync_options.", allow_yaml=True, tooltips=OPTION_TOOLTIPS, option_dropdowns=OPTION_DROPDOWNS.get("bisync_options"))
    add_tab("Resync Options", config.get("resync_options", {}), "resync_options.", allow_yaml=True, tooltips=OPTION_TOOLTIPS)

    def get_widget_value(w, t):
        if t == "bool":
            return w.get_active()
        if t == "int":
            try:
                return int(w.get_value())
            except (TypeError, ValueError):
                return 0
        if t == "yaml":
            buf = w.get_buffer()
            start, end = buf.get_bounds()
            return _safe_yaml_load(buf.get_text(start, end, False))
        if t == "combo":
            return w.get_active_text() or ""
        if t == "schedule_combo":
            i = w.get_active()
            if 0 <= i < len(SCHEDULE_PRESETS):
                return SCHEDULE_PRESETS[i][0]
            return (w.get_child() and w.get_child().get_text()) or ""
        return w.get_text() or ""

    def set_widget_value(w, t, value):
        """Set widget w of type t to value (used by Revert)."""
        if t == "bool":
            w.set_active(bool(value))
        elif t == "int":
            try:
                w.set_value(int(value))
            except (TypeError, ValueError):
                w.set_value(0)
        elif t == "yaml":
            w.get_buffer().set_text(_safe_yaml_dump(value))
        elif t == "combo":
            store = w.get_model()
            val_str = str(value) if value is not None else ""
            for i in range(store.iter_n_children(None)):
                it = store.iter_nth_child(None, i)
                if store.get_value(it, 0) == val_str:
                    w.set_active(i)
                    return
            w.set_active(0)
        elif t == "schedule_combo":
            sval = str(value).strip() if value is not None else ""
            found = False
            for idx, (cron, _) in enumerate(SCHEDULE_PRESETS):
                if cron == sval:
                    w.set_active(idx)
                    found = True
                    break
            if not found:
                w.set_active(-1)
                if w.get_child():
                    w.get_child().set_text(sval)
        else:
            w.set_text(str(value) if value is not None else "")

    def build_config_from_widgets():
        """Build current config dict from widget values (same structure as last_saved_config)."""
        built = copy.deepcopy(last_saved_config)
        for path, (w, t) in widgets.items():
            val = get_widget_value(w, t)
            _set_by_path(built, path, val)
        return built

    def _normalize_for_compare(c):
        """Normalize so empty string/missing/None are comparable; drop dict keys with None value.
        Option-like strings (e.g. log_level) are normalized to canonical form (case-insensitive)."""
        if c is None:
            return None
        if isinstance(c, str):
            if c.strip() == "":
                return None
            low = c.strip().lower()
            return _OPTION_CANONICAL.get(low, c)
        if isinstance(c, dict):
            return {k: v for k, v in ((k, _normalize_for_compare(v)) for k, v in c.items()) if v is not None}
        if isinstance(c, list):
            return [_normalize_for_compare(x) for x in c]
        return c

    def update_dirty_indicator(*_args):
        """Update status label and window title: Saved vs Unsaved changes (current widgets vs last_saved_config)."""
        built = build_config_from_widgets()
        try:
            a = _normalize_for_compare(built)
            b = _normalize_for_compare(last_saved_config)
            dump_a = yaml.dump(a, sort_keys=True)
            dump_b = yaml.dump(b, sort_keys=True)
            dirty = dump_a != dump_b
            if dirty:
                log_message("config_editor: dirty check True (opening or after edit)", level=logging.DEBUG)
                log_message(f"config_editor: built (from widgets) normalized dump (first 800 chars):\n{dump_a[:800]}", level=logging.DEBUG)
                log_message(f"config_editor: last_saved_config normalized dump (first 800 chars):\n{dump_b[:800]}", level=logging.DEBUG)
                # Log first differing line
                for i, (line_a, line_b) in enumerate(zip(dump_a.splitlines(), dump_b.splitlines())):
                    if line_a != line_b:
                        log_message(f"config_editor: first diff at line {i + 1}: built={repr(line_a)} saved={repr(line_b)}", level=logging.DEBUG)
                        break
                else:
                    if len(dump_a.splitlines()) != len(dump_b.splitlines()):
                        log_message(f"config_editor: different line count built={len(dump_a.splitlines())} saved={len(dump_b.splitlines())}", level=logging.DEBUG)
        except Exception as e:
            dirty = True
            log_message(f"config_editor: dirty check exception: {e}", level=logging.DEBUG)
        if dirty:
            status_label.set_text("Unsaved changes")
            status_label.set_tooltip_text("Current form values differ from the last saved state (disk).")
            if Gdk is not None:
                status_label.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.75, 0.4, 0.0, 1.0))  # orange
            win.set_title("Edit Configuration • Unsaved changes")
        else:
            status_label.set_text("Saved")
            status_label.set_tooltip_text("Current form matches the last saved state (disk).")
            if Gdk is not None:
                status_label.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.0, 0.55, 0.0, 1.0))  # green
            win.set_title("Edit Configuration")

    def connect_widget_change(w, t):
        """Connect widget to call update_dirty_indicator when user changes it."""
        def on_change(*args):
            update_dirty_indicator()
        if t == "yaml":
            w.get_buffer().connect("changed", on_change)
        elif t == "bool":
            w.connect("toggled", on_change)
        elif t == "int":
            w.connect("value-changed", on_change)
        else:
            w.connect("changed", on_change)

    def revert_config(btn):
        """Restore all fields from the cached original config (state when editor was opened)."""
        for path, (w, t) in widgets.items():
            val = _get_by_path(config_original, path)
            set_widget_value(w, t, val)
        update_dirty_indicator()
        dlg = Gtk.MessageDialog(
            transient_for=win, flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Reverted to the values from when the editor was opened.",
        )
        dlg.run()
        dlg.destroy()

    def save_config_gtk(btn):
        for path, (w, t) in widgets.items():
            val = get_widget_value(w, t)
            _set_by_path(config, path, val)
        with open(config_file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        def update_value(lines, path, value):
            if not path:
                return False
            if value is None:
                value = ""
            if isinstance(value, (list, dict)):
                value_str = yaml.dump(value, default_flow_style=False, allow_unicode=True).strip()
            else:
                value_str = str(value)
            pat = re.compile(r"^(\s*{}: ).*$".format(re.escape(path)))
            for i, line in enumerate(lines):
                if pat.match(line):
                    prefix = pat.match(line).group(1)
                    if "\n" in value_str:
                        parts = value_str.split("\n")
                        lines[i] = prefix + parts[0] + "\n"
                        for j, rest in enumerate(parts[1:]):
                            lines.insert(i + 1 + j, "  " + rest + "\n")
                    else:
                        lines[i] = prefix + value_str + "\n"
                    return True
            return False

        def update_config_lines(cdict, pfx=""):
            for key, value in cdict.items():
                full_key = f"{pfx}{key}" if pfx else key
                if isinstance(value, dict) and not (key in ("rclone_options", "bisync_options", "resync_options") or pfx.startswith("sync_jobs.")):
                    update_config_lines(value, f"{full_key}.")
                else:
                    if not update_value(lines, full_key, value):
                        val_str = yaml.dump(value, default_flow_style=False, allow_unicode=True).strip() if isinstance(value, (list, dict)) else str(value)
                        lines.append(f"{full_key}: {val_str}\n")

        update_config_lines(config)
        with open(config_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        last_saved_config.clear()
        last_saved_config.update(copy.deepcopy(config))
        update_dirty_indicator()
        dlg = Gtk.MessageDialog(
            transient_for=win, flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Configuration saved.\nReload config from the tray menu (Config & Logs → Reload Config) to apply.",
        )
        dlg.run()
        dlg.destroy()
        win.destroy()

    for path, (w, t) in widgets.items():
        connect_widget_change(w, t)
    update_dirty_indicator()

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    vbox.pack_start(nb, True, True, 0)
    hint = Gtk.Label(label="After saving, use Config & Logs → Reload Config in the tray menu to apply changes.", xalign=0)
    hint.set_margin_start(4)
    hint.set_margin_end(4)
    vbox.pack_start(hint, False, False, 0)
    vbox.pack_start(status_label, False, False, 0)
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_margin_top(4)
    revert_btn = Gtk.Button(label="Revert")
    revert_btn.set_tooltip_text("Restore all fields to the values from when the editor was opened (before any edits or saves).")
    revert_btn.connect("clicked", revert_config)
    btn_box.pack_start(revert_btn, False, False, 0)
    save_btn = Gtk.Button(label="Save")
    save_btn.set_tooltip_text("Save configuration to file. Use Config & Logs → Reload Config in the tray to apply changes.")
    save_btn.connect("clicked", save_config_gtk)
    btn_box.pack_start(save_btn, False, False, 0)
    vbox.pack_start(btn_box, False, False, 0)
    win.add(vbox)
    win.show_all()
