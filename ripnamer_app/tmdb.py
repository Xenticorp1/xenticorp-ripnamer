"""TMDb client: search, seasons, episode groups (alternate orderings).

Hardened for flaky networks: timeouts, 5xx and 429 (rate limit) are retried with backoff,
honouring Retry-After. Errors come back as TMDbError with a message fit for the UI.
"""

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import APP, VERSION


class TMDbError(RuntimeError):
    """User-facing TMDb failure."""


class TMDb:
    BASE = "https://api.themoviedb.org/3"
    ATTEMPTS = 4          # 1 try + 3 retries
    TIMEOUT = 15          # seconds per request
    MAX_WAIT = 10         # cap on any single backoff sleep
    GROUP_TYPES = {1: "Original air date", 2: "Absolute", 3: "DVD", 4: "Digital",
                   5: "Story arc", 6: "Production", 7: "TV"}

    def __init__(self, key: str, opener=None, sleep=None):
        self.key = key.strip()
        self._cache = {}
        self._open = opener or urllib.request.urlopen   # injectable for tests
        self._sleep = sleep or time.sleep

    # ------------------------------------------------------------------ transport

    def _request(self, path, params):
        headers = {"Accept": "application/json", "User-Agent": f"Xenticorp-{APP}/{VERSION}"}
        params = dict(params)
        if len(self.key) > 40:  # v4 read access token (JWT)
            headers["Authorization"] = f"Bearer {self.key}"
        else:                   # v3 API key
            params["api_key"] = self.key
        url = f"{self.BASE}{path}?{urllib.parse.urlencode(params)}"
        return urllib.request.Request(url, headers=headers)

    def _get(self, path, **params):
        req = self._request(path, params)
        problem = "unknown error"
        for attempt in range(self.ATTEMPTS):
            wait = 2 ** attempt  # 1, 2, 4, 8 s
            try:
                with self._open(req, timeout=self.TIMEOUT) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise TMDbError("TMDb rejected the API key (401). Check it in ⚙ Settings.") from None
                if e.code == 404:
                    raise TMDbError("TMDb: not found (404). Does that season / ordering exist?") from None
                if e.code == 429:
                    problem = "TMDb is rate-limiting requests (429)"
                    try:
                        wait = max(wait, float(e.headers.get("Retry-After", 0)))
                    except (TypeError, ValueError):
                        pass
                elif 500 <= e.code < 600:
                    problem = f"TMDb server error ({e.code})"
                else:
                    raise TMDbError(f"TMDb error {e.code}.") from None
            except urllib.error.URLError as e:
                reason = e.reason
                if isinstance(reason, socket.gaierror):
                    problem = "Can't reach TMDb. Check your internet connection"
                elif isinstance(reason, (socket.timeout, TimeoutError)):
                    problem = "TMDb timed out"
                else:
                    problem = f"Can't reach TMDb ({reason})"
            except (socket.timeout, TimeoutError):
                problem = "TMDb timed out"
            except (ConnectionError, OSError) as e:
                problem = f"Connection problem ({e})"
            except json.JSONDecodeError:
                problem = "TMDb sent a garbled response"
            if attempt < self.ATTEMPTS - 1:
                self._sleep(min(wait, self.MAX_WAIT))
        raise TMDbError(f"{problem}. Tried {self.ATTEMPTS} times.")

    def _cached(self, key, fetch):
        if key not in self._cache:
            self._cache[key] = fetch()
        return self._cache[key]

    def forget_groups(self):
        """Drop cached orderings so newly added TMDb episode groups show up."""
        self._cache = {k: v for k, v in self._cache.items() if k[0] not in ("groups", "group")}

    # ------------------------------------------------------------------ endpoints

    def search_tv(self, query: str) -> list[dict]:
        data = self._get("/search/tv", query=query, include_adult="false")
        return [{"id": r["id"], "name": r.get("name") or r.get("original_name") or "?",
                 "year": (r.get("first_air_date") or "")[:4], "overview": r.get("overview", "")}
                for r in data.get("results", [])]

    def season(self, show_id: int, season: int) -> list[dict]:
        """Standard aired season, in plan() episode format."""
        def fetch():
            data = self._get(f"/tv/{show_id}/season/{season}")
            return [{"number": e["episode_number"], "title": e.get("name") or f"Episode {e['episode_number']}",
                     "runtime": e.get("runtime"), "season": season, "episode": e["episode_number"]}
                    for e in data.get("episodes", [])]
        return self._cached(("season", show_id, season), fetch)

    def episode_groups(self, show_id: int) -> list[dict]:
        """Alternate orderings (DVD volumes, absolute, story arcs…)."""
        def fetch():
            data = self._get(f"/tv/{show_id}/episode_groups")
            return [{"id": g["id"], "name": g.get("name") or "?",
                     "type": self.GROUP_TYPES.get(g.get("type"), "Other"),
                     "groups": g.get("group_count", 0), "episodes": g.get("episode_count", 0)}
                    for g in data.get("results", [])]
        return self._cached(("groups", show_id), fetch)

    def episode_group(self, group_id: str) -> list[dict]:
        """Sub-groups (e.g. 'Volume 1') of an ordering, each with its episodes in disc order."""
        def fetch():
            data = self._get(f"/tv/episode_group/{group_id}")
            subs = sorted(data.get("groups", []), key=lambda g: g.get("order", 0))
            out = []
            for g, n in zip(subs, scheme_numbers([g.get("name", "") for g in subs])):
                eps = sorted(g.get("episodes", []), key=lambda e: e.get("order", 0))
                out.append({"name": g.get("name") or f"Part {n}", "number": n, "episodes": [
                    {"pos": i + 1, "title": e.get("name") or f"Episode {i + 1}", "runtime": e.get("runtime"),
                     "orig_season": e.get("season_number", 0), "orig_episode": e.get("episode_number", 0)}
                    for i, e in enumerate(eps)]})
            return out
        return self._cached(("group", group_id), fetch)


def scheme_numbers(names: list[str]) -> list[int]:
    """Season numbers for sub-groups: 'Volume 3' -> 3, 'Specials'/'Extras'/'OVA' -> 0, else running count."""
    out, count = [], 0
    for name in names:
        low = name.lower()
        m = re.search(r"(\d+)", name)
        if "special" in low or "extra" in low or "ova" in low.split():
            out.append(0)
        elif m:
            out.append(int(m.group(1)))
        else:
            count += 1
            out.append(count)
        if out[-1] > 0:
            count = max(count, out[-1])
    return out


def scheme_episodes(sub: dict, naming: str) -> list[dict]:
    """One ordering sub-group -> plan() episodes.
    naming='standard': each file gets its normal aired SxxEyy (Jellyfin default order).
    naming='scheme':   S<volume>E<position> (set Jellyfin's display order to match)."""
    out = []
    for e in sub["episodes"]:
        season, ep = (sub["number"], e["pos"]) if naming == "scheme" else (e["orig_season"], e["orig_episode"])
        out.append({"number": e["pos"], "title": e["title"], "runtime": e["runtime"],
                    "season": season, "episode": ep})
    return out
