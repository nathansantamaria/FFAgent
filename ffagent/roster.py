"""Roster truth, fetched live and verified. Never hardcoded.

This exists because I hardcoded a roster into `build_dash.py` from a draft-day
screenshot and it went stale the moment a waiver or trade happened. That is the
third time in this project a written-once snapshot has silently gone wrong:
first `dashboard.json` re-rendering an 88-player board for hours, then
`sleeper_meta.csv` capping game logs at 59 of 133 players, now this.

The pattern is always the same and always invisible: the code runs, produces
output, and the output is confidently wrong. So the rule here is that **the
roster is never written down**. It is fetched from Sleeper, and anything the
agent claims about who is on a team is checked against that fetch before it
reaches a recommendation.

Two verification layers:

`fetch_rosters()` gets the truth from the API.

`verify(names)` checks a list of player names against it and returns what
matched, what did not, and — importantly — *near misses*. Sleeper writes
"Harold Fannin"; my board carries "Harold Fannin Jr.". A strict comparison
calls that a missing player when it is a spelling difference, which would
send me hunting a phantom roster move. Near-miss detection distinguishes
"this player is not on the roster" from "this player is on the roster under a
slightly different name", and those need completely different responses.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ROSTER_CACHE = DATA / "rosters.json"


def norm(name: str) -> str:
    """Strip suffixes and punctuation so 'Harold Fannin Jr.' == 'Harold Fannin'."""
    n = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", "", str(name).strip(), flags=re.I)
    return re.sub(r"[^a-z]", "", n.lower())


@dataclass
class Verification:
    matched: dict = field(default_factory=dict)      # claimed -> actual roster name
    missing: list = field(default_factory=list)      # claimed, not on roster at all
    near: dict = field(default_factory=dict)         # claimed -> likely roster name
    extra: list = field(default_factory=list)        # on roster, not claimed

    @property
    def clean(self) -> bool:
        return not self.missing and not self.near and not self.extra

    def report(self) -> str:
        out = [f"{len(self.matched)} matched"]
        if self.near:
            out.append("NAME MISMATCH (on roster, different spelling): "
                       + "; ".join(f"{k!r} -> {v!r}" for k, v in self.near.items()))
        if self.missing:
            out.append("NOT ON ROSTER: " + ", ".join(self.missing))
        if self.extra:
            out.append("ON ROSTER BUT UNCLAIMED: " + ", ".join(self.extra))
        return " | ".join(out)


def load_cache() -> dict:
    if ROSTER_CACHE.exists():
        return json.loads(ROSTER_CACHE.read_text())
    return {}


def save_cache(payload: dict) -> None:
    """Store a fetch. The cache is a CONVENIENCE, not a source of truth --
    every entry carries the timestamp it was fetched at so a stale read is
    visible rather than silent."""
    DATA.mkdir(parents=True, exist_ok=True)
    ROSTER_CACHE.write_text(json.dumps(payload, indent=1))


def my_roster(cache: dict | None = None) -> list[str]:
    c = cache or load_cache()
    return list(c.get("my_roster", []))


def verify(claimed, cache: dict | None = None, cutoff: float = 0.86) -> Verification:
    """Check claimed player names against the live roster."""
    actual = my_roster(cache)
    v = Verification()
    if not actual:
        v.missing = list(claimed)
        return v

    by_norm = {norm(a): a for a in actual}
    used = set()
    for c in claimed:
        k = norm(c)
        if k in by_norm:
            v.matched[c] = by_norm[k]
            used.add(by_norm[k])
            continue
        hit = difflib.get_close_matches(k, list(by_norm), n=1, cutoff=cutoff)
        if hit:
            v.near[c] = by_norm[hit[0]]
            used.add(by_norm[hit[0]])
        else:
            v.missing.append(c)
    v.extra = [a for a in actual if a not in used]
    return v


def assert_rostered(name: str, cache: dict | None = None) -> tuple[bool, str]:
    """Gate for any recommendation about a player I claim to own.

    Returns (ok, message). Call this before advising a start, sit, or drop --
    advice about a player who is not on the roster is worse than no advice,
    because it looks authoritative.
    """
    v = verify([name], cache)
    if v.matched:
        return True, v.matched[name]
    if v.near:
        return True, v.near[name]
    return False, (f"{name} is NOT on the roster. Current roster: "
                   + ", ".join(my_roster(cache)))


FETCH_JS = """
// Run in a browser tab with Sleeper reachable. Returns the payload to save
// into data/rosters.json.
const L = '%s';
const [us, ro, all] = await Promise.all([
  fetch(`https://api.sleeper.app/v1/league/${L}/users`).then(r => r.json()),
  fetch(`https://api.sleeper.app/v1/league/${L}/rosters`).then(r => r.json()),
  fetch('https://api.sleeper.app/v1/players/nfl').then(r => r.json())]);
const tname = {}; us.forEach(u => tname[u.user_id] = u.metadata?.team_name || u.display_name);
const nm = id => { const p = all[id]; return p ? (p.full_name ||
  `${p.first_name||''} ${p.last_name||''}`.trim() || id) : id; };
const teams = {};
ro.forEach(r => teams[tname[r.owner_id]] = (r.players || []).map(nm));
const mine = ro.find(r => /%s/i.test(tname[r.owner_id] || ''));
return JSON.stringify({fetched_at: new Date().toISOString(),
  league_id: L, my_team: tname[mine.owner_id],
  my_roster: (mine.players || []).map(nm),
  my_starters: (mine.starters || []).map(nm), teams});
"""
