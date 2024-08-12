from queue import Queue

running = True
shutting_down = False
shutdown_complete = False
currently_syncing = None
current_sync_start_time = None
sync_queue = Queue()
queued_paths = set()
dry_run = False


def signal_handler(signum, frame):
    global running, shutting_down
    running = False
    shutting_down = True
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
