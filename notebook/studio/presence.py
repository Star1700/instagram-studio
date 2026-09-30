"""Track open Studio tabs so the local server does not outlive the dashboard."""
import re
import threading
import time


class Presence:
    def __init__(self, clock=time.monotonic, startup_grace=120, stale_after=150, close_grace=8):
        self.clock = clock
        self.startup_grace = startup_grace
        self.stale_after = stale_after
        self.close_grace = close_grace
        self.started = clock()
        self.last_empty = None
        self.seen_tab = False
        self.tabs = {}
        self.lock = threading.Lock()

    def update(self, tab_id: str, action: str) -> None:
        if not isinstance(tab_id, str) or not re.fullmatch(r"[a-f0-9]{32}", tab_id):
            raise ValueError("Ungültiger Studio-Tab.")
        if action not in {"touch", "leave"}:
            raise ValueError("Ungültige Tab-Aktion.")
        with self.lock:
            if action == "touch":
                self.tabs[tab_id] = self.clock()
                self.seen_tab = True
                self.last_empty = None
            else:
                self.tabs.pop(tab_id, None)
                if self.seen_tab and not self.tabs and self.last_empty is None:
                    self.last_empty = self.clock()

    def should_stop(self) -> bool:
        with self.lock:
            now = self.clock()
            if not self.seen_tab:
                return now - self.started >= self.startup_grace
            self.tabs = {tab_id: last for tab_id, last in self.tabs.items()
                         if now - last < self.stale_after}
            if self.tabs:
                self.last_empty = None
                return False
            if self.last_empty is None:
                self.last_empty = now
            return now - self.last_empty >= self.close_grace
