"""Week-by-week history, and *why* each week looked the way it did.

A game log on its own tells you a player scored 3.1 in week 6. That is close to
useless without knowing whether he was hurt, whether his quarterback was hurt,
whether he played twelve snaps, or whether the team simply never trailed and ran
the ball forty times. The number without the cause invites exactly the wrong
inference -- fading a receiver for a week his backup QB threw for 90 yards.

So this builds an annotated log. Every explanation is derived from data rather
than written by hand, which keeps it honest and means it regenerates each week:

  own injury      -- the weekly injury report, status and body part
  missing games   -- gaps in the stat line, cross-referenced against the report
  quarterback     -- who actually threw the ball that week vs the team's usual
                     starter. This is the one most tools ignore and it moves
                     receiver production more than almost anything else.
  usage           -- snap share and target share against the player's own
                     season baseline, so "quiet game" and "benched" are
                     distinguishable
  game script     -- team points for and against, because a blowout suppresses
                     passing volume and inflates rushing volume
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
DATA = Path(__file__).resolve().parent.parent / "data"


def _load(season: int):
    st = pd.read_parquet(f"{BASE}/stats_player/stats_player_week_{season}.parquet")
    st = st[st["week"] <= 18]
    try:
        inj = pd.read_parquet(f"{BASE}/injuries/injuries_{season}.parquet")
    except Exception:
        inj = pd.DataFrame()
    try:
        sn = pd.read_parquet(f"{BASE}/snap_counts/snap_counts_{season}.parquet")
    except Exception:
        sn = pd.DataFrame()
    return st, inj, sn


def _team_qbs(st: pd.DataFrame) -> dict:
    """Primary passer per team per week, and the team's usual starter.

    'Usual' is whoever threw the most attempts across the season, so a week
    where someone else led the team in attempts is a real signal rather than a
    rounding artefact.
    """
    qb = st[(st["position"] == "QB") & (st["attempts"].fillna(0) > 0)]
    weekly = (qb.sort_values("attempts", ascending=False)
                .groupby(["team", "week"]).first()[["player_display_name", "attempts"]])
    # "Usual starter" must be who started the MOST WEEKS, not who threw the most
    # attempts. Ranking by attempts made Tyler Shough the Saints' usual starter
    # over Spencer Rattler, so every one of Rattler's seven starts got flagged as
    # an anomaly -- the opposite of the truth, and exactly the kind of confident
    # wrong annotation that is worse than none.
    wk = weekly.reset_index()
    counts = wk.groupby(["team", "player_display_name"]).size().reset_index(name="starts")
    total = counts.groupby("team")["starts"].transform("sum")
    counts["share"] = counts["starts"] / total
    top = counts.sort_values("starts", ascending=False).groupby("team").first()
    return {"weekly": weekly.to_dict("index"),
            "starter": top["player_display_name"].to_dict(),
            "share": {(r["team"], r["player_display_name"]): r["share"]
                      for _, r in counts.iterrows()}}


@dataclass
class Week:
    week: int
    pts: float | None            # None = did not play
    snap: float | None = None
    targets: float = 0
    carries: float = 0
    note: str = ""
    # Other players named in the note. Emitted as data rather than left for the
    # UI to find with a regex -- "Mike Evans" and "Evans" and a defence called
    # "NE Defense" are not reliably distinguishable from free text, and a
    # linkifier that guesses will eventually link the wrong man.
    refs: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"w": self.week, "p": self.pts, "s": self.snap, "n": self.note,
                "refs": self.refs}


@dataclass
class SeasonLog:
    season: int
    weeks: list[Week] = field(default_factory=list)
    summary: str = ""
    story: str = ""

    def as_dict(self) -> dict:
        return {"season": self.season, "summary": self.summary,
                "story": self.story,
                "weeks": [w.as_dict() for w in self.weeks]}


def build_logs(names_to_gsis: dict[str, str], seasons=(2024, 2025)) -> dict:
    out: dict[str, list] = {n: [] for n in names_to_gsis}
    xwalk_name: dict[str, str] = {}
    for season in seasons:
        st, inj, sn = _load(season)
        for pid, nm in zip(st["player_id"], st["player_display_name"]):
            xwalk_name.setdefault(str(pid), str(nm))
        qbs = _team_qbs(st)
        max_wk = int(st["week"].max())

        inj_idx = {}
        if len(inj):
            for _, r in inj.iterrows():
                inj_idx[(str(r.get("gsis_id")), int(r["week"]))] = (
                    str(r.get("report_status") or ""),
                    str(r.get("report_primary_injury") or ""),
                    str(r.get("practice_status") or ""))

        snap_idx = {}
        if len(sn):
            xw = pd.read_parquet(f"{BASE}/players/players.parquet")[["gsis_id", "pfr_id"]]
            sn = sn.merge(xw, left_on="pfr_player_id", right_on="pfr_id", how="left")
            for _, r in sn.iterrows():
                if pd.notna(r.get("gsis_id")):
                    snap_idx[(str(r["gsis_id"]), int(r["week"]))] = float(r.get("offense_pct") or 0)

        # A team's bye is a week where nobody on it recorded a stat line.
        # Without this every bye reads as a missed game and inflates the
        # "games missed" count that durability depends on.
        tcol = "recent_team" if "recent_team" in st.columns else "team"
        played_wk = st.groupby(tcol)["week"].apply(set).to_dict()
        allw = set(range(1, max_wk + 1))
        team_byes = {t: allw - w for t, w in played_wk.items()}

        # Who on each team was OUT each week, with their usual target volume.
        # A receiver's big week is often somebody else's absence, and that is
        # the difference between a role change worth chasing and a one-week
        # vacancy that closes when the other man returns.
        usual_tgts = st.groupby("player_id")["targets"].median().to_dict()
        pos_of = st.drop_duplicates("player_id").set_index("player_id")["position"].to_dict()
        played_by = {}
        for _, r in st.iterrows():
            played_by.setdefault((r[tcol], int(r["week"])), set()).add(str(r["player_id"]))
        roster_by_team = {}
        for _, r in st.iterrows():
            roster_by_team.setdefault(r[tcol], set()).add(str(r["player_id"]))

        for name, gsis in names_to_gsis.items():
            if not gsis:
                continue
            g = st[st["player_id"] == gsis]
            if not len(g):
                continue
            pos = str(g["position"].iloc[0])
            team = str(g[tcol].iloc[0])
            # nflverse `offense_pct` is a FRACTION (0.86), not a percentage.
            # Printing it with a % sign produced "0% of snaps vs 1% typical" on
            # weeks the player took 86% of them.
            snaps_seen = [snap_idx.get((gsis, w)) for w in g["week"]]
            snaps_seen = [x for x in snaps_seen if x is not None]
            base_snap = pd.Series(snaps_seen).median() if snaps_seen else None
            base_tgt = g["targets"].fillna(0).median()
            pts_series = g["fantasy_points_ppr"].fillna(0)
            pts_mean = float(pts_series.mean())
            pts_sd = float(pts_series.std()) or 1.0
            played = set(int(w) for w in g["week"])
            first = min(played)

            log = SeasonLog(season)
            missed = 0
            for w in range(first, max_wk + 1):
                row = g[g["week"] == w]
                status, part, prac = inj_idx.get((gsis, w), ("", "", ""))
                # pandas turns missing strings into the literal "nan"
                part = "" if part.lower() in ("nan", "none") else part
                status = "" if status.lower() in ("nan", "none") else status
                prac = "" if prac.lower() in ("nan", "none") else prac
                snap = snap_idx.get((gsis, w))
                notes: list[str] = []

                if not len(row):
                    if w in team_byes.get(team, set()):
                        log.weeks.append(Week(w, None, None, note="bye week"))
                        continue
                    missed += 1
                    if status == "Out":
                        notes.append(f"out, {part.lower() or 'injury'}")
                    elif part:
                        notes.append(f"did not play, {part.lower()}")
                    else:
                        notes.append("did not play, no designation")
                    log.weeks.append(Week(w, None, None, note="; ".join(notes)))
                    continue

                r = row.iloc[0]
                pts = float(r.get("fantasy_points_ppr") or 0)
                tgt = float(r.get("targets") or 0)
                car = float(r.get("carries") or 0)

                # ---- anomaly first, explanation second ----
                #
                # The previous version annotated any metric that moved, which
                # produced lines like "0% of snaps vs 1% typical" on weeks where
                # nothing happened. The right question is not "did a number
                # change" but "was this week unusual FOR HIM, and if so why".
                #
                # A week qualifies only if scoring departed from his own average
                # by both a standardised and an absolute margin: 1.2 standard
                # deviations AND four fantasy points. One without the other
                # flags noise — a consistent player fails the second test, a
                # volatile one fails the first.
                refs: list[str] = []
                z = (pts - pts_mean) / pts_sd
                delta = pts - pts_mean
                anomalous = abs(z) >= 1.2 and abs(delta) >= 4.0
                if not anomalous:
                    log.weeks.append(Week(w, round(pts, 1), snap, tgt, car, ""))
                    continue

                # Touchdowns: the most common single reason a week is big, and
                # the least repeatable. Naming it matters because two scores is
                # a fact about last Sunday, not about the player.
                tds = (float(r.get("receiving_tds") or 0)
                       + float(r.get("rushing_tds") or 0)
                       + float(r.get("passing_tds") or 0))

                # Teammate absences at the same position, weighted by how many
                # targets they normally take.
                absent = []
                here = played_by.get((team, w), set())
                for mate in roster_by_team.get(team, set()):
                    if mate == gsis or mate in here:
                        continue
                    if pos_of.get(mate) not in ("WR", "TE", "RB"):
                        continue
                    ut = float(usual_tgts.get(mate) or 0)
                    # 5+ targets a game: below that his absence frees up
                    # roughly nothing and naming him is filler.
                    if ut >= 5:
                        absent.append((ut, mate))
                absent.sort(reverse=True)

                # Causes must point the same way as the anomaly. A big week
                # explained by "played fewer snaps than usual" is not an
                # explanation, it is a contradiction — Nacua scored 12 above
                # his average on 44% of snaps, and reporting the snap dip as
                # the reason inverts what happened. Suppressive causes explain
                # bad weeks; only volume spikes explain good ones.
                down = delta < 0

                # Facts only. Every note here used to carry an interpretation
                # attached -- "the least repeatable part of a big week", "which
                # does not carry to next week", "efficiency, not volume". The
                # reader can draw those conclusions from "2 touchdowns" and
                # "44% of snaps"; spelling them out is padding, and padding is
                # what buries the one line that matters.
                if down and status in ("Questionable", "Doubtful") and part:
                    notes.append(f"{status.lower()}, {part.lower()}")
                elif down and "Did Not Participate" in prac and part:
                    notes.append(f"no practice, {part.lower()}")

                if down and pos in ("WR", "TE", "RB"):
                    wk_qb = qbs["weekly"].get((team, w), {}).get("player_display_name")
                    usual = qbs["starter"].get(team)
                    share = qbs["share"].get((team, wk_qb), 1.0)
                    if wk_qb and usual and wk_qb != usual and share <= 0.35:
                        notes.append(f"{wk_qb} at QB, not {usual}")
                        refs += [wk_qb, usual]

                # Snap share: 15 percentage points is the threshold, because
                # below that the player was on the field for essentially his
                # usual workload and the snaps did not cause anything.
                if down and snap is not None and base_snap:
                    gap = base_snap - snap
                    if gap >= 0.15:
                        notes.append(f"{snap:.0%} of snaps, usual {base_snap:.0%}")
                elif not down and snap is not None and base_snap and base_snap - snap >= 0.15:
                    # Worth saying explicitly: he did MORE on LESS, which is the
                    # opposite of a repeatable performance.
                    notes.append(f"{snap:.0%} of snaps, usual {base_snap:.0%}")

                # Targets: needs to move both relatively and absolutely.
                if base_tgt >= 3:
                    if down and tgt <= base_tgt - 3 and tgt <= base_tgt * 0.6:
                        notes.append(f"{tgt:.0f} targets, usual {base_tgt:.0f}")
                    elif not down and tgt >= base_tgt + 4 and tgt >= base_tgt * 1.5:
                        notes.append(f"{tgt:.0f} targets, usual {base_tgt:.0f}")

                # Touchdowns: the most common reason a week is big and the least
                # repeatable. Two scores is a fact about last Sunday, not about
                # the player, and saying so is the whole point of this panel.
                if not down and tds >= 2:
                    notes.append(f"{tds:.0f} touchdowns")
                elif down and tds == 0 and base_tgt >= 4:
                    notes.append("no touchdown")

                # Somebody else's absence. This is the difference between a role
                # change worth chasing and a one-week vacancy that closes the
                # moment the other man is healthy.
                # Only mentioned on a GOOD week. A teammate being absent does
                # not explain a bad one — "Colby Parkinson was also out" said
                # nothing about why Nacua scored 4.8, and that is the filler
                # this panel exists to avoid.
                if not down and absent:
                    ut, mate = absent[0]
                    nm = xwalk_name.get(mate, "a teammate")
                    notes.append(f"{nm} out, usually {ut:.0f} targets")
                    refs.append(nm)

                if not notes:
                    # Saying "no clear cause" is more useful than inventing one.
                    # Most single-week swings in fantasy are touchdown variance,
                    # which is real, unexplainable from usage, and does not
                    # repeat -- which is exactly what you want to know.
                    notes.append("usage normal")

                head = f"{delta:+.0f} vs his {pts_mean:.1f} average"
                log.weeks.append(Week(w, round(pts, 1), snap, tgt, car,
                                      head + " — " + "; ".join(notes),
                                      refs=sorted(set(refs))))

            scored = [x.pts for x in log.weeks if x.pts is not None]
            if scored:
                log.summary = (f"{len(scored)} games, {sum(scored)/len(scored):.1f} ppg, "
                               f"high {max(scored):.1f}, low {min(scored):.1f}"
                               + (f", missed {missed}" if missed else ""))

            # What defined the season, in one line. Built from the same data
            # rather than written: team changes, injury stretches, and how the
            # scoring was distributed.
            story = []
            teams_played = list(dict.fromkeys(str(t) for t in g[tcol]))
            if len(teams_played) > 1:
                story.append("changed teams: " + " to ".join(teams_played))
            if missed >= 4:
                gaps = [x.week for x in log.weeks if x.pts is None and "bye" not in x.note]
                if gaps:
                    # "weeks 2-18" implied one continuous absence when the
                    # missed games were scattered across the year. Those are
                    # different seasons for a fantasy manager: one is an injury
                    # you can plan around, the other is a player you can never
                    # trust to be there.
                    contiguous = len(gaps) == (gaps[-1] - gaps[0] + 1)
                    if contiguous and len(gaps) > 1:
                        story.append(f"missed weeks {gaps[0]}-{gaps[-1]}")
                    else:
                        story.append(f"missed {missed} games, weeks "
                                     f"{', '.join(str(x) for x in gaps)}")
            elif missed:
                story.append(f"missed {missed} game" + ("s" if missed > 1 else ""))
            if scored and len(scored) >= 6:
                top2 = sorted(scored, reverse=True)[:2]
                share = sum(top2) / sum(scored)
                if share >= 0.32:
                    story.append(f"{share:.0%} of his points came in 2 games")
            log.story = "; ".join(story)
            out[name].append(log.as_dict())
    return out


if __name__ == "__main__":
    import csv
    meta = {r["name"]: r for r in csv.DictReader(open(DATA / "sleeper_meta.csv"))}
    xw = pd.read_parquet(f"{BASE}/players/players.parquet")
    xw = xw.dropna(subset=["gsis_id"])
    by_name = {}
    for _, r in xw.iterrows():
        by_name.setdefault(str(r["display_name"]), str(r["gsis_id"]))
    mapping = {n: by_name.get(n, "") for n in meta}
    logs = build_logs(mapping)
    (DATA / "gamelogs.json").write_text(json.dumps(logs))
    hit = sum(1 for v in logs.values() if v)
    print(f"logs for {hit}/{len(mapping)} players")
