import os
import json


class ConfigManager:
    def __init__(self) -> None:
        self.dir: str = os.path.expanduser("~/.stiq")
        self.file: str = os.path.join(self.dir, "config.json")
        self.watchlist: list[str] = []
        self.poll_interval: int = 300
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as f:
                    data = json.load(f)
                    self.watchlist = [s.upper() for s in data.get("watchlist", [])]
                    self.poll_interval = int(data.get("poll_interval", 300))
            except Exception:
                pass

    def save(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            data = {"watchlist": self.watchlist, "poll_interval": self.poll_interval}
            with open(self.file, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def add(self, sym: str) -> None:
        sym_upper = sym.upper()
        if sym_upper not in self.watchlist:
            self.watchlist.append(sym_upper)
            self.save()

    def remove(self, sym: str) -> None:
        sym_upper = sym.upper()
        if sym_upper in self.watchlist:
            self.watchlist.remove(sym_upper)
            self.save()

    def set_interval(self, seconds: int) -> None:
        self.poll_interval = int(seconds)
        self.save()


config = ConfigManager()
