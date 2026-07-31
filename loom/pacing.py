"""loom.pacing — the governor of restraint (layer 2 of the restraint architecture).

Pure, deterministic, no model call. Reads the recent beats and decides whether the
narrator should HOLD (respond, don't inject — the default) or may OFFER one gentle
hook. The whole point is to NOT manufacture conflict: an OFFER fires only on positive
evidence of a genuine STALL (the player has gone passive/searching for a couple of
beats) and never while tension is still elevated. Calm is not boredom; the player owns
escalation.

Fail-safe property: every ambiguity biases toward HOLD. A false-high drive or
false-high tension can only SUPPRESS an offer, never spawn one — the governor errs
on the side of leaving the player alone.
"""
from __future__ import annotations
from dataclasses import dataclass

# low-agency player inputs — the player casting about, not driving the scene
_PASSIVE = {
    "wait", "look around", "looking around", "what now", "what next", "what do i do",
    "hmm", "ok", "okay", "idk", "i don't know", "nothing", "continue", "go on", "...",
    "um", "uh", "yeah", "sure", "i wait", "keep going", "and", "then", "next", "?", "",
}
# cheap intent cues — signs the player is actually doing something (even quietly)
_INTENT = {
    "ask", "tell", "say", "go", "walk", "run", "take", "grab", "open", "close", "look at",
    "search", "examine", "read", "listen", "touch", "pick", "sit", "watch", "study", "sketch",
    "draw", "fight", "attack", "climb", "talk", "give", "buy", "sell", "steal", "follow",
    "enter", "leave", "offer", "show", "remember", "head", "approach", "whisper", "shout",
    "check", "inspect", "pray", "drink", "rest", "wait for", "kneel", "wave", "point",
}
# crude scene-intensity cues, for the decaying tension signal
_TENSE = {"blood", "scream", "attack", "danger", "knife", "sword", "fight", "run ", "death",
          "dead", "kill", "threat", "chase", "monster", "shout", "panic", "fear", "flee",
          "grabbed", "weapon", "struck", "wound", "corpse", "ambush", "blade", "screamed"}
_CALM = {"rest", "quiet", "calm", "warm", "gentle", "peace", "settle", "breathe", "still",
         "soft", "ease", "sleep", "drifted", "murmur", "lull", "hush", "slow", "gently"}


@dataclass(frozen=True)
class Pacing:
    directive: str      # "hold" | "offer"
    tension: float      # 0..1, decayed toward calm
    drive: float        # 0..1, the player's most recent agency
    reason: str


def _drive(text: str) -> float:
    t = (text or "").strip().lower()
    words = t.split()
    if not words:
        return 0.0
    if t in _PASSIVE or (len(words) <= 3 and any(t == p or t.startswith(p + " ") for p in _PASSIVE)):
        return 0.1
    score = min(1.0, len(words) / 10.0)
    if any(v in t for v in _INTENT):
        score = min(1.0, score + 0.35)
    return score


def _intensity(text: str) -> float:
    t = (text or "").lower()
    tense = sum(t.count(c) for c in _TENSE)
    calm = sum(t.count(c) for c in _CALM)
    if tense == 0 and calm == 0:
        return 0.3                          # neutral scene
    return min(1.0, tense / (tense + calm + 1))


def read(transcript_lines, stall_window: int = 2,
         drive_floor: float = 0.3, tension_ceiling: float = 0.45) -> Pacing:
    players = [e["text"] for e in transcript_lines if e.get("role") == "player"]
    narrators = [e["text"] for e in transcript_lines if e.get("role") == "narrator"]

    # tension: an EMA over recent narrator beats that decays toward calm on quiet beats
    tension = 0.3
    for beat in narrators[-6:]:
        tension = 0.6 * tension + 0.4 * _intensity(beat)

    drives = [_drive(p) for p in players[-stall_window:]]
    drive = drives[-1] if drives else 1.0

    stalled = len(drives) >= stall_window and all(d < drive_floor for d in drives)
    if stalled and tension < tension_ceiling:
        return Pacing("offer", round(tension, 2), round(drive, 2),
                      f"{len(drives)} passive beats, tension {tension:.2f} — a gentle hook is warranted")
    reason = ("player is engaged — hold" if not stalled
              else f"stalled but tension {tension:.2f} still high — let it breathe, hold")
    return Pacing("hold", round(tension, 2), round(drive, 2), reason)


_OFFER_CLAUSE = (
    "\n\nPACING: the scene has gone quiet and the player seems to be casting about for direction. "
    "You MAY offer ONE small, low-key hook or detail that invites action — a sound, a passer-by, a "
    "noticed object, a remembered errand — but keep it gentle and easy to ignore. Do NOT introduce "
    "danger, conflict, or a dramatic twist."
)


def prompt_clause(pacing: Pacing) -> str:
    return _OFFER_CLAUSE if pacing.directive == "offer" else ""
