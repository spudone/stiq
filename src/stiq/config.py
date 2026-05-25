import os
import json


class ConfigManager:
    def __init__(self) -> None:
        self.dir: str = os.path.expanduser("~/.stiq")
        self.file: str = os.path.join(self.dir, "config.json")
        self.watchlist: list[str] = []
        self.poll_interval_secs: int = 300
        self.market_provider: str = "yahoo"
        self.quotes_provider: str = "yahoo"
        self.history_provider: str = "yahoo"
        self.weekend_provider: str = "yahoo"
        self.use_rate_limit: bool = True
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as f:
                    data = json.load(f)
                    self.watchlist = [s.upper() for s in data.get("watchlist", [])]
                    self.poll_interval_secs = max(60, int(data.get("poll_interval_secs", data.get("poll_interval", 300))))
                    self.market_provider = data.get("market_provider", "yahoo")
                    self.quotes_provider = data.get("quotes_provider", "yahoo")
                    self.history_provider = data.get("history_provider", "yahoo")
                    self.weekend_provider = data.get("weekend_provider", "yahoo")
                    self.use_rate_limit = bool(data.get("use_rate_limit", True))
            except Exception:
                pass
        else:
            self.save()

    def save(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            data = {
                "poll_interval_secs": self.poll_interval_secs,
                "market_provider": self.market_provider,
                "quotes_provider": self.quotes_provider,
                "history_provider": self.history_provider,
                "weekend_provider": self.weekend_provider,
                "use_rate_limit": self.use_rate_limit,
                "watchlist": self.watchlist
            }
            with open(self.file, "w") as f:
                json.dump(data, f, indent=4)
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
        self.poll_interval_secs = max(60, int(seconds))
        self.save()


config = ConfigManager()
