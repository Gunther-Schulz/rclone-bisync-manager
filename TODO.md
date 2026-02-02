# TODO

## Known Issues

- [ ] More than 3 sync_jobs will cause `JSON decode error: Expecting ',' delimiter: line 1 column 4089 (char 4088)` returned by the status command. - fixed by removing config objects from the status
- [ ] The tray displays "Daemon Offline" even when the daemon is running in the state described in the last point above.
- [ ] Stopping the dameon does not reliably work during tray status RUNNING
- [ ] The tray does not reliably display the RUNNING status. It's status window does however.

## Testing

- [ ] Test if missed runs are still processed
- [ ] Test behavior when suspending the PC
- [ ] Test per-sync job options override
- [ ] Verify exclude rule file changes trigger a resync

## Development

- [ ] Implement internal Python CPU limiter
- [ ] Implement separate filter files per job

## Improvements

- [ ] Refactor code to eliminate 'global' keyword (if possible)

## Refactor plan

### Tray: use modern AppIndicator / SNI path (GNOME-native) — DONE

- **Done:** Tray tries **AppIndicator3** (SNI) via **PyGObject** first; icon shows with “AppIndicator and KStatusNotifierItem Support” on stock GNOME. Falls back to **pystray** when `gi.repository.AppIndicator3` is unavailable (e.g. missing libappindicator3).
- **System deps (for AppIndicator):** `libappindicator3-1`, `gir1.2-appindicator3-0.1` (or equivalent). Python deps: PyGObject (already in tray extras).
- **Notes:** Notifications under AppIndicator use `notify-send`; status window and config editor still use tkinter.
