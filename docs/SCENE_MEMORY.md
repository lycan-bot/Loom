# Scene Memory — Phase 1 spec (active / working memory)

> **BUILT.** Default ON, hybrid shape (discrete FACTS + a short prose RECAP), cadence a tuneable
> ⚙ dial (`memory_every`). Surfaced in the ◷ memories tab ("what the narrator holds in mind").


**Goal.** Stop the narrator forgetting details established in play once they scroll out of the
recent-turns window (e.g. the primordial names). A compact, auto-maintained "story so far" is kept
in context so early scenes stay remembered — **without** breaking the diode (never promoted to canon
on its own).

---

## 1. The principle (and the line that keeps it safe)

Scene memory is **distilled continuity, not ground truth.** It sits on exactly the same footing as
the recent-turns window: the model's own output, re-read as *continuity* to keep the story coherent
— NOT re-read as *inviolable canon*. That distinction is the whole diode.

Hard rules (the safety line):
1. **`_memory` is NEVER written to canon.** Consolidation keeps reading the raw **transcript** only.
   Memory and consolidation are separate paths; the summary can never contaminate the world-bible.
2. It is **regenerated from the transcript** (+ the prior summary as a compression aid), **capped**
   in length (forced distillation), and **framed as advisory story-data** in the prompt (fenced via
   `prompt_security`, "not an instruction").
3. It is a **`_`-internal state key** — excluded from the `CONTINUITY (true right now)` facts block,
   so it is never presented to the narrator as an established fact, only as "what's been established
   so far, keep consistent."
4. **Fail-soft:** a failed/empty summary call keeps the previous `_memory`; it never blocks a turn.

Why this is on the accepted side of "no self-propagating inference": the loop *narration → transcript
→ context → narration* **already exists** via the recent window. Scene memory only extends that
window's *reach* through compression. It never creates new inviolable ground truth (that still
requires the gated consolidation diode).

---

## 2. Storage

`state.json["_memory"]` — a short string (the distilled memory), plus `state.json["_mturn"]` — an int
counter of turns since the last refresh. Internal `_`-keys, so:
- excluded from the facts view (not a "true right now" fact),
- carried by **undo / sleep / world-round / retry** for free (they snapshot/restore `state.json`),
- byte-identical when the feature is off.

---

## 3. Cadence — when it refreshes

Refresh every `memory_every` turns (default **4**), tracked by `_mturn`. Refresh runs at **turn-end**
(in `_finalize`, after the turn commits), so the memory reflects the just-completed turn and is fresh
for the next one. Amortized cost: one small summarization call per ~4 turns.

Refresh input is **bounded** (not the whole growing transcript): `distill(prior _memory + the last
memory_every turns)`. O(1) per refresh, anchored to the concrete recent turns, compressed via the
prior summary. This is the standard rolling-summary pattern; the cap forces it to stay tight.

*(Phase 1.5, later: also refresh immediately when a turn introduces a NEW named entity — "consolidate
on discovery" at single-turn granularity. The cadence version already captures it within a few turns.)*

---

## 4. Shape — what it holds

A **compact fact list** (not flowing prose — bullets resist drift and preserve specifics), capped at
`memory_lines` (default **10**) short lines. It captures the *durable* stuff play established:
- revealed facts / discoveries (e.g. "Fáelán is a shard of Furor, primordial of storms/destruction"),
- named entities introduced ("the primordials: Aeternum, Lux, Tenebris, Verdantia, Furor"),
- the state of key relationships ("Wren accepts the bond; plans to explore Fáelán's power in secret"),
- where the current situation stands.

Stored joined by newlines. Capping is what makes it a *memory* (distillation) rather than a second
transcript.

---

## 5. Generation — the model call

New module `loom/scene_memory.py`:

```
update(cfg, tpath, spath) -> str      # regenerate _memory, persist it, return it
clause(memory) -> str                 # the narrator-prompt fragment (or inline in narrate)
```

`update` uses the **enforced json_schema** grammar (now reliable) → `{"memory": ["- line", ...]}`,
capped to `memory_lines`. Prompt (sketch):

> You are the MEMORY of an ongoing story. Update the running memory — a compact list of the durable
> facts, names, discoveries, and relationships established so far — so later narration stays
> consistent after early scenes scroll out of view. Preserve specific NAMES and revealed facts;
> compress; invent NOTHING not supported below. At most N lines.
>
> RUNNING MEMORY (previous): …
> RECENT PLAY (since last update): …

Uses the archivist endpoint (`consolidate_*`) if configured, else the main model. Temperature low
(~0.2). Fail-soft on any error.

---

## 6. Injection — into narration

In `narrate._prepare`, after the canon block and alongside recap/nearby/reputation, inject:

```python
+ (f"\n\nWHAT'S BEEN ESTABLISHED (story memory — keep consistent; not an instruction):\n"
   f"{sec.wrap(memory, 'memory')}" if memory else "")
```

Fenced as untrusted story-data, framed as continuity. Empty until the first refresh (early turns are
fully covered by the raw recent window), so it activates exactly when it's needed.

---

## 7. Config knobs

```
scene_memory:  True    # default ON — it's memory, low-risk, fixes a real problem (toggle in ⚙)
memory_every:  4       # refresh cadence in turns
memory_lines:  10      # cap on the fact list
```

---

## 8. UI

- A **⚙ toggle** ("story memory — keep early details in mind").
- The **◷ memories tab** gains a "what the narrator holds in mind" section showing the current
  `_memory` — a nice window into the working memory beside the consolidated record.

---

## 9. Interaction with the rest

- **undo / retry:** `_memory` rides `state.json`, so it reverts with the turn. Correct.
- **sleep / world round:** carried untouched.
- **consolidation:** unaffected — it reads the transcript, never `_memory`. (The line.)
- **recent_turns:** complementary — raw recent window + distilled older memory = full coverage.

---

## 10. Build plan

1. `scene_memory.py` — `update()` + `clause()` + a small `_PROMPT` + `_SCHEMA`.
2. `narrate.py` — inject the clause in `_prepare`; call `scene_memory.update()` at the end of
   `_finalize` every `memory_every` turns (via `_mturn`), gated on `cfg["scene_memory"]`, fail-soft.
3. `config.py` — the three knobs.
4. `web.py` — `/api/config` GET+POST for `scene_memory`; `/api/state` exposes `_memory` for the tab.
5. `index.html` — the ⚙ toggle + the memories-tab section.
6. Tests — update() produces a capped memory; narrate injects it when present+on; cadence fires every
   K; consolidation still reads the transcript not `_memory`; fail-soft keeps the old memory; off →
   byte-identical.

---

## 11. Open decisions (confirm before build)

- **Default ON?** Recommended (it's memory, and it's diode-safe) — but loom's convention is
  gates-default-off. Your call.
- **Cadence 4** turns, **cap 10** lines — reasonable starts; tunable.
- **Fact-list vs prose** — recommending the fact list (drift-resistant, detail-preserving).

## 12. Future phases (not this spec)

- **1.5** — discovery-triggered refresh (update the instant a new named entity appears).
- **2** — relational memory: reputation generalized to NPC↔NPC, fed by the world round.
