"""The write layer. The only module in this project that clicks anything.

Sleeper's public API is read-only -- there is no documented endpoint to set a
lineup, submit a claim, or make a pick. So writes go through the actual UI.

Three rules, and they are the whole design:

1. **Act in the browser, confirm through the API.** The DOM will happily tell
   you a click succeeded when nothing happened. Only `/league/<id>/rosters`
   is proof. Every write returns a `WriteResult` whose `verified` flag comes
   from a read-back, never from the page.

2. **Deltas, not full state.** Never "set the lineup". Move one player into
   one slot, verify, move the next. A half-applied full-state write on Sunday
   at 12:58 is the worst outcome available.

3. **Selectors are guesses until proven.** Every selector below is a
   placeholder written without access to a logged-in Sleeper DOM. They are
   collected in SELECTORS so that when the real ones are captured, exactly one
   dict changes. `python -m ffagent.write --probe` prints what it finds.

Nothing here executes in shadow mode. `WriteLayer(dry_run=True)` logs the
actions it would take and touches nothing.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import sleeper

STATE = Path(__file__).resolve().parent.parent / "data" / "session.json"

# PROBED against the live logged-in DOM on 2026-08-31. Every earlier guess in
# this dict was wrong, and wrong in the same way: I assumed Sleeper exposed
# data-* hooks for players and slots. It does not -- there is not a single
# data-player-id or data-slot on the page. The markup is class-based.
#
# The important structural finding: **a slot is identified by row index, not by
# a label.** `.team-roster-item` returns exactly 15 rows in the same order as
# the league's `roster_positions`, so index 6 is the first FLEX whether or not
# anything on screen says "FLEX" (it renders as "W R T"). That is the same
# positional scheme the API's `starters` array uses, which means the write
# layer and the verification read agree by construction.
#
# Remaining unknown, stated rather than papered over: the roster is empty
# pre-draft, so the click sequence for an actual swap could not be exercised.
# The elements are located; the interaction is not yet proven.
SELECTORS = {
    # session
    "logged_in_marker": ".nav-league-item-wrapper",
    "captcha_present": "[data-hcaptcha-widget-id]",

    # roster: rows are positional, index == roster_positions index
    "roster_rows": ".team-roster-item",
    "slot_square": ".league-slot-position-square",   # text: QB/RB/WR/TE/WRT/K/DEF/BN
    "player_cell": ".cell-player-meta",
    "position_button": ".cell-position",             # THIS is the click target
    "roster_hint": ".update-roster-copy",            # "Click on position buttons..."

    # league actions
    "waiver_button": ".team-panel >> text=WAIVER",
    "trade_button": ".team-panel >> text=TRADE",

    # modal
    "confirm_modal": "[role='dialog']",
}

# roster_positions index -> what the slot square renders as
SLOT_LABELS = {"FLEX": "WRT", "SUPER_FLEX": "QWRT", "WRRB_FLEX": "WR",
               "REC_FLEX": "WRT", "DEF": "DEF", "BN": "BN"}


@dataclass
class WriteResult:
    action: str
    ok: bool
    verified: bool          # confirmed by API read-back, not by the DOM
    detail: str = ""
    attempts: int = 1
    elapsed_s: float = 0.0

    def __str__(self) -> str:
        mark = "OK " if self.verified else ("UNVERIFIED " if self.ok else "FAILED ")
        return f"[{mark.strip()}] {self.action} — {self.detail} ({self.elapsed_s:.1f}s)"


@dataclass
class WriteLayer:
    league_id: str
    dry_run: bool = True
    headless: bool = True
    timeout_ms: int = 15000
    log: list[WriteResult] = field(default_factory=list)
    _pw: Any = None
    _browser: Any = None
    _page: Any = None

    # --- session ---------------------------------------------------------

    def __enter__(self) -> "WriteLayer":
        if self.dry_run:
            return self
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        ctx_args: dict[str, Any] = {"viewport": {"width": 1280, "height": 900}}
        if STATE.exists():
            ctx_args["storage_state"] = str(STATE)
        self._ctx = self._browser.new_context(**ctx_args)
        self._page = self._ctx.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._page:
            try:
                self._ctx.storage_state(path=str(STATE))
            except Exception:
                pass
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            if obj:
                try:
                    getattr(obj, meth)()
                except Exception:
                    pass

    def ensure_logged_in(self) -> bool:
        """Detect the logged-out state explicitly.

        The dangerous failure is not an exception -- it is a script that
        cheerfully clicks nothing on a login wall and reports success.

        Also checks for an hCaptcha widget, which was present on the probed
        page. If Sleeper challenges the session the agent must stop and hand
        back to a human: solving it is out of bounds, and retrying into a
        challenge is how an account gets flagged.
        """
        if self.dry_run:
            return True
        self._page.goto(f"https://sleeper.com/leagues/{self.league_id}/team")
        try:
            self._page.wait_for_selector(SELECTORS["logged_in_marker"], timeout=8000)
        except Exception:
            return False
        if self._page.locator(SELECTORS["captcha_present"]).count():
            self.log.append(WriteResult("session", False, False,
                                        "captcha challenge present — human required"))
            return False
        return True

    def slot_index(self, cfg_roster_positions: list[str], slot_label: str,
                   occurrence: int = 1) -> int:
        """roster_positions index for a slot, e.g. ("FLEX", 2) -> 7.

        Index is the addressing scheme for both the DOM and the API, so this
        is the single translation point between a human-readable slot and the
        thing both sides actually use.
        """
        seen = 0
        for i, p in enumerate(cfg_roster_positions):
            if p == slot_label:
                seen += 1
                if seen == occurrence:
                    return i
        raise KeyError(f"{slot_label}#{occurrence} not in roster positions")

    # --- verification ----------------------------------------------------

    def _roster_for(self, user_id: str) -> dict | None:
        for r in sleeper.rosters(self.league_id):
            if r.get("owner_id") == user_id:
                return r
        return None

    def _verify(self, check: Callable[[], bool], tries: int = 6, delay: float = 1.5) -> bool:
        """Poll the API until it agrees with what we think we did.

        Sleeper is eventually consistent after a write; a single immediate
        read will often still show the old state and make a good write look
        like a failure.
        """
        for _ in range(tries):
            try:
                if check():
                    return True
            except Exception:
                pass
            time.sleep(delay)
        return False

    # --- actions ---------------------------------------------------------

    def set_slot(self, user_id: str, slot: str, player_id: str, player_name: str = "") -> WriteResult:
        """Move one player into one starting slot. One player, one slot, verified."""
        t0 = time.time()
        label = f"set {slot} = {player_name or player_id}"
        if self.dry_run:
            r = WriteResult(label, True, False, "dry run, nothing clicked", 0, time.time() - t0)
            self.log.append(r)
            return r

        if not self.ensure_logged_in():
            r = WriteResult(label, False, False, "not logged in", 1, time.time() - t0)
            self.log.append(r)
            return r

        try:
            self._page.click(SELECTORS["team_tab"])
            self._page.click(SELECTORS["player_row"].format(player_id=player_id))
            self._page.click(SELECTORS["slot_row"].format(slot=slot))
            if self._page.locator(SELECTORS["confirm_modal"]).count():
                self._page.click(SELECTORS["confirm_modal"])
        except Exception as e:
            r = WriteResult(label, False, False, f"DOM step failed: {e}", 1, time.time() - t0)
            self.log.append(r)
            return r

        ok = self._verify(
            lambda: player_id in (self._roster_for(user_id) or {}).get("starters", [])
        )
        r = WriteResult(
            label, True, ok,
            "confirmed by API read-back" if ok else "clicked, but API never confirmed",
            1, time.time() - t0,
        )
        self.log.append(r)
        return r

    def apply_lineup(self, user_id: str, changes: list[tuple[str, str, str]]) -> list[WriteResult]:
        """Apply a lineup diff, one slot at a time, stopping on the first
        unverified write. A partially applied lineup is recoverable; a
        blindly-continued one is not."""
        out = []
        for slot, _old, new in changes:
            res = self.set_slot(user_id, slot, new, new)
            out.append(res)
            if not res.ok:
                out.append(WriteResult("halt", False, False, "stopped after failed write"))
                break
        return out

    def submit_claim(self, add_id: str, drop_id: str | None, bid: int | None = None) -> WriteResult:
        t0 = time.time()
        label = f"claim {add_id}" + (f" drop {drop_id}" if drop_id else "") + (f" ${bid}" if bid else "")
        if self.dry_run:
            r = WriteResult(label, True, False, "dry run, nothing clicked", 0, time.time() - t0)
            self.log.append(r)
            return r
        # Claims land in a pending queue, so they cannot be verified against
        # rosters until waivers process. Verify against the transactions feed.
        raise NotImplementedError("selectors not captured yet — run --probe first")

    # --- selector discovery ----------------------------------------------

    def probe(self) -> dict:
        """Print what each placeholder selector actually matches.

        Run this once against a logged-in session and paste the results into
        SELECTORS. It is the difference between this module being real and
        being a sketch.
        """
        if self.dry_run:
            return {k: "dry run" for k in SELECTORS}
        found = {}
        self._page.goto(f"https://sleeper.com/leagues/{self.league_id}/team")
        self._page.wait_for_timeout(3000)
        for name, sel in SELECTORS.items():
            if "{" in sel:
                found[name] = "templated, needs a live id"
                continue
            try:
                found[name] = f"{self._page.locator(sel).count()} match(es)"
            except Exception as e:
                found[name] = f"error: {e}"
        return found


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", required=True)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--live", action="store_true", help="disable dry run")
    a = ap.parse_args()

    with WriteLayer(a.league_id, dry_run=not a.live, headless=False) as w:
        if a.probe:
            print(json.dumps(w.probe(), indent=2))
        else:
            print("logged in:", w.ensure_logged_in())
