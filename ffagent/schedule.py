"""When the agent wakes up.

A daily cron is the obvious design and the wrong one. It burns runs Monday
through Wednesday and misses the moments that decide games. Fantasy is
event-driven: five windows a week, each with a different job.

The trap in here is timezones. Every deadline is quoted in Eastern, and ET is
UTC-4 in September and UTC-5 in December. Hardcode an offset and every window
silently slips an hour on the first Sunday in November -- which lands in the
playoff push, when a missed inactive sweep is most expensive. We resolve
through the IANA zone every time so the transition is handled for us.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


@dataclass(frozen=True)
class Window:
    key: str
    weekday: int
    hour: int
    minute: int
    job: str
    why: str
    critical: bool = False
    kind: str = "job"          # "job" | "refresh"
    lead_min: int = 0          # minutes before the deadline this fires

    def next_after(self, now: datetime) -> datetime:
        """Next occurrence strictly after `now`, resolved in ET then returned UTC."""
        local = now.astimezone(ET)
        days = (self.weekday - local.weekday()) % 7
        cand = local.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        cand += timedelta(days=days)
        if cand <= local:
            cand += timedelta(days=7)
        # Re-resolve through the zone so a DST boundary inside the offset is
        # applied to the wall-clock time we actually want.
        cand = cand.replace(tzinfo=None).replace(tzinfo=ET)
        return cand.astimezone(timezone.utc)


# Deadlines the agent must never be caught cold by. Each gets an automatic
# T-minus-60 refresh so every source is current when the decision is made --
# data pulled at 07:00 is eight hours stale by a 15:00 waiver lock, and stale
# data at a deadline is worse than no data because it looks current.
DEADLINES = [
    ("waiver_lock", TUE, 23, 0, "Waiver claims lock"),
    ("tnf_kick", THU, 20, 15, "Thursday night kickoff"),
    ("sun_early", SUN, 13, 0, "Sunday early slate"),
    ("sun_late", SUN, 16, 5, "Sunday late slate"),
    ("snf_kick", SUN, 20, 20, "Sunday night kickoff"),
    ("mnf_kick", MON, 20, 15, "Monday night kickoff"),
]


def _minus(hour: int, minute: int, lead: int) -> tuple[int, int]:
    t = hour * 60 + minute - lead
    return (t // 60) % 24, t % 60


WINDOWS: list[Window] = [
    # Daily baseline. Everything refreshed before the day starts, so a manual
    # check at any hour is looking at something no more than a day old.
    Window("daily_refresh", MON, 7, 0, "refresh_all",
           "Morning refresh: all sources pulled, board rebuilt, news re-gated.",
           kind="refresh"),
    Window("waiver_submit", TUE, 22, 0, "queue_claims",
           "Claims lock at 23:00 ET. Submit with an hour of slack, not on the buzzer.",
           critical=True),
    Window("waiver_process", WED, 4, 0, "read_results",
           "Waivers have run. Read what cleared, re-score the wire."),
    Window("practice_report", THU, 12, 0, "injury_scan",
           "Wednesday and Thursday practice participation is the first real injury signal."),
    Window("tnf_lock", THU, 16, 30, "lock_check",
           "Thursday night kickoff. Any TNF player must be resolved.", critical=True),
    Window("weekend_prep", SAT, 10, 0, "reproject",
           "Refresh projections and flag anything questionable for Sunday."),
    Window("inactives", SUN, 11, 30, "inactive_sweep",
           "Official inactives drop 90 minutes before kickoff. Highest-value window "
           "of the week: a starter ruled out at 11:45 and replaced by 12:55 is worth "
           "more than every other automation combined.", critical=True),
    Window("main_lock", SUN, 12, 50, "final_check",
           "Last look before the main slate locks.", critical=True),
]


# One refresh 60 minutes before every deadline, on top of the daily.
for _key, _wd, _h, _m, _why in DEADLINES:
    _hh, _mm = _minus(_h, _m, 60)
    WINDOWS.append(Window(
        f"pre_{_key}", _wd, _hh, _mm, "refresh_all",
        f"T-60 before {_why.lower()} — refresh every source, re-check availability.",
        critical=True, kind="refresh", lead_min=60))

# The daily refresh runs every day, not only Monday. Expanded here rather than
# written out seven times so the cadence is obvious and editable in one place.
for _wd in (TUE, WED, THU, FRI, SAT, SUN):
    WINDOWS.append(Window("daily_refresh", _wd, 7, 0, "refresh_all",
                          "Morning refresh: all sources pulled, board rebuilt.",
                          kind="refresh"))


def next_runs(now: datetime | None = None) -> list[tuple[Window, datetime]]:
    now = now or datetime.now(timezone.utc)
    runs = [(w, w.next_after(now)) for w in WINDOWS]
    return sorted(runs, key=lambda t: t[1])


def due(now: datetime | None = None, grace_min: int = 20) -> list[Window]:
    """Windows whose moment has just passed, for a scheduler that ticks
    every few minutes. Grace covers a late or slow tick without firing a
    window twice."""
    now = now or datetime.now(timezone.utc)
    out = []
    for w in WINDOWS:
        prev = w.next_after(now - timedelta(days=7))
        if timedelta(0) <= (now - prev) <= timedelta(minutes=grace_min):
            out.append(w)
    return out


def crontab() -> str:
    """Emit real cron lines. Cron has no notion of DST-correct ET, so we set
    CRON_TZ and let the system resolve it -- same reason as above."""
    days = "mon tue wed thu fri sat sun".split()
    lines = ["CRON_TZ=America/New_York", "# ffagent windows"]
    for w in WINDOWS:
        lines.append(
            f"{w.minute} {w.hour} * * {days[w.weekday]}  "
            f"cd $FFAGENT && python run.py --league-id $LEAGUE --window {w.key}"
        )
    return "\n".join(lines)


def agenda(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    rows = []
    for w, when in next_runs(now):
        local = when.astimezone(ET)
        delta = when - now
        hrs = delta.total_seconds() / 3600
        mark = "!" if w.critical else " "
        rows.append(
            f" {mark} {local:%a %H:%M} ET  in {hrs:5.1f}h  {w.key:<16} {w.job}"
        )
    return "\n".join(rows)
