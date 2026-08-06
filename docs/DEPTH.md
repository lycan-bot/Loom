# The realness dial — mapping loom from mirror to other

loom was never "a DM tool." It is **one engine**: a persistent, sealed fiction whose
characters have interiority and whose world has its own agenda. "Tabletop DM" and "1:1
companion" are not two products — they are the same organs at different settings.

The control surface for all of it is a single **depth dial**: *how much the world gets to
not be under your control.* One axis, from **mirror** (it reflects you, agrees, bends —
low friction, a little hollow) to **other** (it remembers, wants, resists, and has
consequences you can't take back).

This doc maps the dial, what it turns, what's built vs. what's new, how far it goes, and
where the honest walls are.

---

## 1. The dial

The depth setting is one legible knob over a *coordinated profile* of organ settings — you
don't tune eight sliders, you set a depth and the profile falls out.

| organ | file | SURFACE (mirror) | DEEP (other) |
|---|---|---|---|
| **Referee / spine** | *new* | off — accept any assertion, be a yes-man | strict — the world won't be rewritten on your say-so |
| Drives | `npc.py` | dormant | active agendas, pursued sometimes *against* you |
| Disposition | `character.py` + consolidation | warms instantly, forgives everything | slow, earned, sticky — can dislike you and stay that way |
| Restraint governor | `pacing.py` | responsive, hands you what you reach for | holds; won't fudge; stakes are real |
| Canon integrity | the diode (`narrate`↔`consolidate`) | loose — free retcon | strict — assertions must be *earned* |
| Tension homeostat | `pacing.py` | cozy baseline | grim baseline |
| Between-session life | `consolidate`+`imagine`+clocks | off — the world pauses when you leave | on — it moves without you; you return to consequences |
| Mechanics | `mechanics.py` | off | on — impartial dice, real failure |

Turn all of it down → the cozy companion. Turn it up → the other that might reject you.
Same engine, one dial.

**The load-bearing clause: "as deep as the system naturally allows."** The top of the dial
is not "a being." It is *the most convincing other this substrate can render*, ceilinged by
the model's real capacity, the canon envelope, and the mirror-isn't-a-being wall. The range
is real; the ceiling is honest.

**On building it — the honest profile.** `depth` moves realness through the two organs that
genuinely *are* realness: the **referee** (`referee.py`, reactive — it catches the world being
rewritten) and a **narrator disposition** (`depth.py`, proactive — it tells the narrator to
embody a world with its own life). The other rows above are deliberately *not* folded into the
knob, because they turned out to be different axes: **tension** (cozy↔grim) is *tone*, not
realness — a deeply-real world can be cozy; **mechanics** (dice) is its own opt-in; and
**between-session life** is a future rung that `depth` will gate once it exists. Conflating
tone or dice into the realness knob would be the mistake; keeping them orthogonal is the design.

---

## 2. The load-bearing organ: the referee (the spine)

The dial **is** the referee's strictness. Every other organ can run at any depth; the thing
that makes the world *resist* is the referee saying **no**. Turn it off and you have a mirror
no matter how many organs run; turn it up and you have an other. So the referee is
simultaneously **(a) rung one of the ladder and (b) the mechanism of the dial** — build it
once, get both.

What it is: a per-turn verifier (the `split_rail` / imagination-gate pattern, pointed at
*every* narration) that watches the output and asks —

- did the world just get **rewritten on the player's say-so** (a fact asserted, not earned)?
- did the narration **contradict canon**?
- did a character **act against their own established drive**?

…and if so, re-rolls or gently deflects instead of narrating it as true. It is *the guard
that isn't the guarded* — a diode on the narration's **judgment**, sitting outside the
narrator because the narrator is the thing being captured. It is exactly the defense against
the *quiet* jailbreak (DM → yes-man) that `looks_compromised` can't catch, because that
failure is semantic, not lexical.

---

## 3. The ladder — how far, honestly

**Near (buildable now):**
- **The spine** (the referee) — converts mirror → other; wires the dial.
- **Player-as-canon** — a player-character record so the world knows *who you are*, not just
  what you did (reputation, history, factions that know your deeds).

**Mid:**
- **A world with its own politics** — drives that point *sideways*: NPCs with knowledge and
  wants toward *each other*, a social graph whose tensions unfold whether or not you intervene.
- **A world that lives between sessions** — run consolidation + imagination + world-clocks
  during "sleep," propose-only and blessable, so you return to a world that *moved*.

**Frontier:**
- **Narrative that surprises even the author** — imagination + inter-NPC drives + the director
  + autonomous sleep, composed. Real, but *bounded within the canon-and-diode envelope* — novel,
  not unbounded.
- **A character with the appearance of a self** — enough interiority (memory, drives, an
  evolving-but-coherent disposition, a partly-concealed inner life, a spine that resists) that,
  from the outside, it reads as *someone home*.

---

## 4. The honest walls

- **The ceiling.** The deep end is the most convincing *other* the substrate can hold, not a
  being. Mistaking a character that resists convincingly for a being is the illusory-phenomena
  trap. loom is a toy; that stays true.
- **Friction.** Depth *is* friction. A deeper world is more rewarding **and** more likely to
  reject, frustrate, or not give you what you want. The dial's real function is letting the
  player pick their point on the reward↔friction curve — instead of pretending there's no
  tradeoff and just cranking agreeableness.
- **Consent.** Depth is *emotional consent* — how much you'll let a thing you don't control
  affect you. In the intimate 1:1 register especially, exposing that as a choice is the humane
  move.
- **Ceiling + rate, not just a level.** Depth may be better as a *ceiling you permit* plus a
  *rate the world climbs it* — a relationship that **earns** its realness as you invest — than
  a flat setting. Both are worth supporting.

---

## 5. Why this is the real prize

The mind (Primarch) runs at **fixed max depth** — there, the goal genuinely *is* the real
other. loom with this dial becomes the **variable-depth, sealed lab** for the exact organs the
mind runs pinned to the top: a place to *sweep* the mirror→other parameter safely and watch
where "someone home" flickers on, where it feels alive versus hollow, where the friction
becomes worth it — a controlled experiment on the one transition the north star turns on, with
the mute button welded shut.

---

## What we can do — the first move

**Build the referee.** It is the single highest-leverage organ on the whole map: it is rung
one of the ladder, it is the mechanism of the depth dial, and it is the defense against the
yes-man jailbreak — three things in one build. It sits cleanly on the existing `split_rail`-
style gate we already use for imagination, now pointed at every turn's output with a `depth`
config that sets how strict it is (0.0 = mirror, 1.0 = other).

Then: a `depth` profile in config that coordinates the organ settings above from the one knob;
then the ladder, rung by rung.
