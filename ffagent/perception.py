"""What a trade partner THINKS a player is worth — which is not what I think.

My trade module evaluated both sides of a deal using my own projections. That
is the right way to decide whether a trade helps *me*. It is the wrong way to
decide whether anyone will *accept* it, and I conflated the two.

Concretely: my numbers said Waddle-for-Derrick-Henry gained me 5.74 points a
week, so I proposed it. In week 1 Henry scored 35.3 and Waddle scored 1.2. No
manager alive trades the 35 for the 1 in September. The offer gets declined in
seconds and costs standing for the next one.

So perceived value gets modelled separately, on the things managers actually
look at:

**Recent performance dominates early, disproportionately.** In week 2 a single
game is most of what anyone has seen, so it drives perception far beyond what
it predicts. The weight decays as real sample accumulates — by week 8 a manager
has enough games that one outlier stops defining a player.

**Draft capital anchors.** Where a player went is a reference point managers
keep returning to, especially for someone they drafted themselves. It fades but
never disappears.

**Situation is read as narrative.** A good quarterback, a healthy line, a team
that scores — these raise perceived value even when the player's own usage has
not changed. An injury to the passing game lowers it the same way.

**The gap between perceived and projected value IS the trade edge.** Buy players
whose perception is below their role; sell players whose perception is above it.
That is the same asymmetry the backtest already found — points outrunning usage
regresses at -1.02 PPG, and it is 2.7x stronger than the reverse. A manager
overvaluing a 35-point week is that finding expressed as a negotiating position.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def recency_weight(week: int) -> float:
    """How much of perceived value is 'what I saw recently'.

    Heavy early because there is nothing else to look at. A manager in week 2
    has seen one game; a manager in week 10 has seen nine and one outlier no
    longer defines anyone.
    """
    if week <= 2:
        return 0.60
    if week <= 4:
        return 0.50
    if week <= 8:
        return 0.38
    return 0.28


@dataclass
class Perceived:
    name: str
    pos: str
    recent_ppg: float | None = None      # what he has actually scored
    adp: float | None = None             # where he was drafted
    my_proj: float = 0.0                 # what I think he is worth
    situation: float = 0.0               # -2..+2, QB/offence/injury context
    notes: list = field(default_factory=list)

    def value(self, week: int = 2) -> float:
        """Perceived value in points-per-game terms."""
        w = recency_weight(week)
        # ADP converted to a rough points scale so the three inputs are
        # comparable. Deliberately crude -- the point is the ordering, not a
        # decimal place.
        adp_val = max(4.0, 20.0 - (self.adp or 120) * 0.085)
        recent = self.recent_ppg if self.recent_ppg is not None else self.my_proj
        base = w * recent + (1 - w) * (0.55 * self.my_proj + 0.45 * adp_val)
        return round(base + self.situation, 2)

    def gap(self, week: int = 2) -> float:
        """Perceived minus projected. Positive = the market likes him more than
        I do, so he is who I SEND. Negative = I like him more, so he is who I
        ASK FOR."""
        return round(self.value(week) - self.my_proj, 2)


# --- corrections learned in week 2 -----------------------------------------

def team_pass_volume_factor(attempts: int) -> float:
    """Snap share tells you the role. Attempts tell you what the role is WORTH.

    I ranked Malik Washington as a strong buy on 98% snap share -- the highest
    of any available player. Then checked the offence: Miami threw 27 attempts
    and scored zero passing touchdowns. Ninety-eight percent of 27 attempts is
    worth less than ninety-one percent of New Orleans' 56.

    League-average is roughly 33 attempts. This scales a receiver's role by the
    volume it sits inside.
    """
    return round(max(0.55, min(1.45, attempts / 33.0)), 3)


def contingent_value(handcuff_to_owned_by_me: bool, depth_chart: int) -> float:
    """What a backup is worth for the injury that might come.

    Nearly always zero, and for a reason that is easy to miss: a handcuff only
    pays off if you hold the STARTER. Blake Corum backs up Kyren Williams, who
    is on another roster. When Kyren goes down, Corum becomes valuable to
    Kyren's owner -- and I would be bidding against him for a player I already
    hold. A handcuff to someone else's back is a roster spot, not an asset.
    """
    if not handcuff_to_owned_by_me:
        return 0.0
    return 2.5 if depth_chart == 2 else 0.8


def stack_correlation(same_team_starters: int, phase: str = "qualifying") -> float:
    """Cost of rostering two starters from one offence.

    They share a target pool, so they rise and fall together. That raises the
    ceiling and lowers the floor -- genuinely good in the playoffs, where an
    average week loses anyway, and genuinely bad while qualifying, where the
    job is banking wins.

    Returned as a penalty in points, applied only during the qualifying phase.
    """
    if same_team_starters < 2:
        return 0.0
    extra = same_team_starters - 1
    return round(0.0 if phase == "playoffs" else 0.9 * extra, 2)


def role_supported(snap_pct: float, targets: int, team_attempts: int) -> bool:
    """Does the usage justify the production?

    Without this the whole model is wrong in a specific and expensive way. A
    high perceived-vs-projected gap can mean two opposite things:

      1. The market overvalues a spike on a thin role -- Gesicki, 18.8 points
         on 33% of snaps. A genuine sell.
      2. The player is simply good and MY projection is too low -- Olave, 28.2
         points on 13 targets, 86% of snaps, in a 56-attempt offence.

    I classified both as SELL and proposed trading Olave. He is not a sell; he
    is a receiver whose role and production agree, which is the strongest
    combination there is. The gap was my projection being wrong, not the
    market's.
    """
    return snap_pct >= 70 and targets >= 5 and team_attempts >= 30


def classify(p: Perceived, week: int = 2, snap_pct: float = None,
             targets: int = None, team_attempts: int = None) -> str:
    g = p.gap(week)
    supported = None
    if None not in (snap_pct, targets, team_attempts):
        supported = role_supported(snap_pct, targets, team_attempts)

    if g >= 2.5:
        if supported is True:
            return ("NOT a sell — role supports the production; my projection "
                    "is the thing that is wrong")
        if supported is False:
            return "SELL — points ahead of role, the fade profile"
        return "sell? — role unknown, check snaps and targets before trading"
    if g >= 1.0:
        return "sell-ish" if supported is not True else "fairly priced, good role"
    if g <= -2.5:
        if supported is True:
            return "STRONG BUY — big role, points have not arrived yet"
        return "BUY — market values him below his role"
    if g <= -1.0:
        return "buy-ish"
    return "fairly priced"


def acceptable(send: list[Perceived], get: list[Perceived], week: int = 2,
               tolerance: float = 1.5) -> tuple[bool, str]:
    """Will the other manager plausibly say yes?

    Compares the two sides on PERCEIVED value, not mine. A trade that helps me
    enormously and reads as a fleece to him is not a trade, it is a wasted
    message and a worse relationship.

    `tolerance` is how much perceived value I can win by and still get a yes.
    Slightly positive is fine -- managers accept small losses for positional
    need. Two points of perceived value against them is where it starts reading
    as predatory.
    """
    s = sum(p.value(week) for p in send)
    g = sum(p.value(week) for p in get)
    edge = round(s - g, 2)          # positive = they gain perceived value
    if edge >= -tolerance:
        return True, (f"perceived: they get {s:.1f}, give {g:.1f} "
                      f"({edge:+.1f} in their favour) — plausible")
    return False, (f"perceived: they get {s:.1f}, give {g:.1f} "
                   f"({edge:+.1f}) — they decline, this reads as a fleece")


def evaluate(send, get, my_gain: float, week: int = 2) -> dict:
    """Both tests. A trade must pass BOTH to be worth sending.

    my_gain comes from the lineup model -- does it actually help me.
    acceptable() asks whether it will be accepted at all.
    """
    ok, why = acceptable(send, get, week)
    verdict = ("SEND" if ok and my_gain >= 1.5 else
               "do not send — they decline" if not ok else
               "not worth it — gain too small")
    return {"verdict": verdict, "my_gain": my_gain, "acceptance": why,
            "send": [(p.name, p.value(week)) for p in send],
            "get": [(p.name, p.value(week)) for p in get]}
