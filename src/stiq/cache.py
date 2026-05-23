import os
import json
from datetime import date


class CacheManager:
    def __init__(self) -> None:
        self.dir: str = os.path.expanduser("~/.stiq")
        self.file: str = os.path.join(self.dir, "cache.json")
        self.history: dict[str, tuple[str, list[float]]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as f:
                    data = json.load(f)
                    for sym, entry in data.items():
                        if (
                            isinstance(entry, dict)
                            and "date" in entry
                            and "history" in entry
                        ):
                            self.history[sym] = (entry["date"], entry["history"])
            except Exception:
                pass

    def save(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            data = {
                sym: {"date": d, "history": h} for sym, (d, h) in self.history.items()
            }
            with open(self.file, "w") as f:
                json.dump(data, f)
        except Exception:
            pass


# Shared global cache instance
_cache = CacheManager()


def get_cached_history(sym: str) -> list[float] | None:
    entry = _cache.history.get(sym.upper())
    today = date.today().isoformat()
    if entry and entry[0] == today:
        return entry[1]
    return None


def set_cached_history(sym: str, history: list[float]) -> None:
    _cache.history[sym.upper()] = (date.today().isoformat(), history)
    _cache.save()
