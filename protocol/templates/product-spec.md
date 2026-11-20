# Product spec — `<name>`

| | |
|---|---|
| **Profile** | Product (`protocol.md` §2) |
| **Author of the breath** | `<name>` — the human owns field 1; the **dates** of fields 2 and 3 are set by default by the constructor, marked unmeasured, and the human moves them by saying they do not fit their life — never asked (`protocol.md` §4). The rest is generated, attacked by the red, then validated by the human, who remains the owner of the spec. |
| **Status** | `invalid` while a field is empty · `attacked` · `solid` when the spec barrier (§2) is crossed |

> A spec fits on one page. Seven fields. **An empty field makes the spec invalid.** It is deliberately incomplete: at least one edge case is left unsaid.

---

## 1. Breath — *one sentence; the intent belongs to the arbiter*

> For `<who>`, who has `<what problem>`, `<this>` `<does what>`, now because `<why now>`.

*Invalid if: several sentences, or no named user.*

*The wording can be wrested from the arbiter rather than asked for — `/spec`. The ownership test is not their agreement, it is field 3: if they cannot say what would make them abandon it, this breath is not theirs.*

## 2. Proof of value

> On **`DD/MM/YYYY`**, `<the figure>` — a measure a third party can verify without asking the author's opinion — and **who is better off**: `<end-user | worker | environment>`, by `<an indicator an exploiting implementation would fail>`.

*Invalid if: no figure, no date, a figure only the human can judge, or a benefit that would improve just as well if the user were exploited.*

## 3. Abandonment criterion

> If on **`DD/MM/YYYY`** `<the proof of value>` is below `<the threshold>`, this is deleted — code, tests, spec — without discussion. **And** if, after delivery, a measured harm appears on the side of the end-user, the worker or the environment: `<what is abandoned>`.

*The arbiter owns the principle — what this is for, and that it dies when it does not serve that. The threshold is derived from that aim and from the evidence, settled by the machine (constructor, red, cold judge) as a provisional decision, and shown to the arbiter — never asked. Invalid if: absent, negotiable, or without an aim the arbiter has stated. It is the only line that gives the thing a reason to die, and therefore to live.*

## 4. Observable behaviours — *5 to 10, testable from outside*

**4.1** — **When** `<situation>`, **then** `<observable effect>`.

**4.2** — …

*Identifiers are assigned once and **never reassigned**. Deleting a behaviour retires its identifier for good; the list reorders freely. Never renumber.*

*Invalid if: a sentence describes the inside, or has no "then".*

## 5. Invariants — *what must never happen*

- **5.1** — `<… never …>`

*Same fixed identifiers as in field 4: assigned once, never reassigned.*

*Invalid if: absent, phrased positively, or without an identifier.*

## 6. Derived decisions

| Decision | Parent | Reason |
|---|---|---|
| | | |

*Invalid if: a decision without a parent or without a reason.*

## 7. Acknowledged gaps

- `<what the spec deliberately leaves unsaid>`

*Invalid if: empty list.*

---

## Spec barrier (§2)

This spec is **solid** only if, on top of the red's silence:

- [ ] each behaviour in field 4 carries at least one test that cites it;
- [ ] each invariant in field 5 carries at least one test that cites it;
- [ ] field 7 is not empty;
- [ ] every decision in field 6 has a parent that exists.
- [ ] each element of the component's public input is named by at least one rule in fields 4 or 5 — *an argument that nothing reads lies about what the component does*.

---

## Technical children

Every Technical spec that descends from this one inherits its abandonment criterion. If this spec is deleted, its children are too.

| Technical spec | Component |
|---|---|
| | |

---

## Reciprocity gate — *not a field: the record that the spec survived it* (`protocol.md` §2)

| Behaviour | End-user | Worker | Environment | Ruling |
|---|---|---|---|---|
| 4.1 | *this actor, in this situation, does or undergoes this, with this consequence* | | | no violation · risk → 5.N · violation upheld → refused |

*Invalid if: a behaviour without its three scenarios, or a violation upheld and open. A violation is never moved to field 7.*
