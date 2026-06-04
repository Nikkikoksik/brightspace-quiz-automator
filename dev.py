"""Dev launcher: restarts gui.py automatically when any .py file changes."""
import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = Path(__file__).parent
ENTRY = [sys.executable, "gui.py"]


class Restarter(FileSystemEventHandler):
    def __init__(self):
        self._proc = None
        self._restart()

    def _restart(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait()
        print("\n-- restarting gui.py --")
        self._proc = subprocess.Popen(ENTRY)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._restart()


if __name__ == "__main__":
    handler = Restarter()
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()
    print(f"Watching {WATCH_DIR} for .py changes  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if handler._proc and handler._proc.poll() is None:
            handler._proc.terminate()
    observer.join()
