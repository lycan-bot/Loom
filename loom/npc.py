"""loom.npc — NPC drives: characters that WANT things, and the moral tension that makes
them dramatic.

A character's want (canon frontmatter `wants:`) held against what opposes it (`bound:` —
a vow, fear, or taboo) becomes a RELATIONAL THREAD the director can pace. This is the
fountain that keeps 1:1 play full: the world's people have their own agendas, so beats
arise from *character*, not just from the scene.

Model-free and legible (after Primarch's moral.evaluate): the tension is structural and
the `because` is a ready-made narration hook — the payoff of a relational thread carries
the character's want and what holds them back, so it lands with dramatic weight.
"""
from __future__ import annotations
from dataclasses import dataclass
from . import canon, threads


@dataclass(frozen=True)
class Moral:
    want: str
    against: str
    tension: bool
    because: str


def moral_read(want: str, bound: str = "") -> Moral:
    want, bound = (want or "").strip(), (bound or "").strip()
    tension = bool(want and bound)
    if tension:
        because = f"wants {want}, but is held back by {bound}"
    elif want:
        because = f"wants {want}"
    else:
        because = ""
    return Moral(want, bound, tension, because)


def drives(world) -> list:
    """Every character with a stated want → (name, Moral, entities-it-touches)."""
    out = []
    for n in canon.load_all(world):
        if n["frontmatter"].get("kind") != "character":
            continue
        want = str(n["frontmatter"].get("wants", "")).strip()
        if not want:
            continue
        bound = str(n["frontmatter"].get("bound", "")).strip()
        entities = [n["name"]] + [l.split("|")[0].strip() for l in n["links"]]
        out.append((n["name"], moral_read(want, bound), list(dict.fromkeys(entities))))
    return out


def relational_threads(world) -> list:
    """A relational Thread per character drive — the character's own agenda as a pending
    dramatic question, with the moral tension baked into its payoff so a paid-off beat
    lands with weight."""
    made = []
    for name, m, entities in drives(world):
        w = m.want[3:].strip() if m.want.lower().startswith("to ") else m.want
        q = (f"Will {name} act on their wish to {w}"
             + (f", against {m.against}?" if m.against else "?"))
        made.append(threads.Thread(
            id=threads.make_id(f"{name} {m.want}"),
            question=q, kind="question", status="dormant", entities=entities,
            seed=f"something in {name}'s manner says they want more than they let on",
            payoff=(f"{name} makes a quiet move to {w}"
                    + (f", torn by {m.against}" if m.against else ""))))
    return made


def sync(world, threads_path, approve=lambda *a: True) -> list:
    """Merge relational threads from character drives into the plan (dedup by id,
    approve-gated). Returns the questions added."""
    th = threads.load(threads_path)
    by_id = {t.id: t for t in th}
    added = []
    for rt in relational_threads(world):
        if rt.id in by_id:
            continue
        if approve("relational", rt.question, rt):
            th.append(rt)
            by_id[rt.id] = rt
            added.append(rt.question)
    if added:
        threads.save(threads_path, th)
    return added
