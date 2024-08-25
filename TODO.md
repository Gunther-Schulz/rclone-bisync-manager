# TODO

## Known Issues

- [ ] More than 3 sync_jobs will cause `JSON decode error: Expecting ',' delimiter: line 1 column 4089 (char 4088)` returned by the status command.
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
