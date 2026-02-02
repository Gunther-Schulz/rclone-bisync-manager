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

### Tray: use modern AppIndicator / SNI path (GNOME-native)

- **Goal:** Tray icon works like Telegram/Steam on GNOME: use **Status Notifier Item (SNI) / AppIndicator** instead of the legacy X11 system tray (XEmbed), so the icon shows with the “AppIndicator and KStatusNotifierItem Support” extension that many distros ship by default.
- **Current:** pystray, which on Linux typically uses the legacy tray → icon does not show on stock GNOME; user needs a different/extra extension.
- **Target:** Use **libappindicator** (AppIndicator) via **PyGObject** (e.g. `python-appindicator` or equivalent bindings). Optional: keep pystray as fallback for non-GNOME desktops if desired.
- **Notes:** Set/keep `PYSTRAY_BACKEND=gtk` if pystray remains; add dependency on libappindicator3 (and corresponding Python bindings); implement tray UI with AppIndicator API so it behaves like Telegram/Steam on GNOME.
