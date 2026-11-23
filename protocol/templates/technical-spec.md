# Technical spec — `<component name>`

| | |
|---|---|
| **Profile** | Technical (`protocol.md` §2) |
| **Product parent** | `<link to the Product spec whose abandonment criterion this spec inherits>` — **mandatory**. If the parent is deleted, so is this spec. |
| **Author of the breath** | `<name>` — the human writes field 1; fields 2 to 7 are generated, then attacked by the red. |
| **Stage** | `sketch` · `hardened` — a sketch validates, hardening verifies (`protocol.md` §5) |
| **Consequence class** | `road` · `flight` — flight when a failure is irreversible for someone other than the worker, or the component handles personal data or money; the higher class wins, and while contested the higher applies (§5) |
| **Status** | `invalid` while a field is empty · `attacked` when the red has produced claims · `solid` when the spec barrier is crossed (§2) |

> A spec fits on one page. Seven fields. **An empty field makes the spec invalid.** It is deliberately incomplete: at least one edge case is left unsaid — it is the red that must find it.

---

## 1. Breath — *one sentence; the intent belongs to the arbiter*

> For `<who>`, who has `<what problem>`, this component `<does what>`, now because `<why now>`.

*Invalid if: several sentences, or no named user.*

*The wording can be wrested from the arbiter rather than asked for — `/spec`. The ownership test is not their agreement, it is field 3: if they cannot say what would make them abandon it, this breath is not theirs.*

## 2. Mechanical acceptance criterion

> The check that passes or fails **without arbitration**: `<e.g.: mutation score ≥ 80%; output equivalence with the reference implementation on corpus X; property P verified on 10,000 generated inputs>`.

*To ask while writing it: **which wrong implementation would fail here?** If none comes to mind, the criterion judges something other than the code — the product, the tuning, or nothing.*

*Invalid if: a criterion only the human can judge, or that a trivial implementation satisfies.*

## 3. Renunciation condition

> The fact that would make us abandon this approach, and its measure: `<e.g.: if the conversion cannot be proven faithful character for character, we freeze the old format instead of converting it>`.

*Invalid if: absent, or negotiable.*

## 4. Observable behaviours — *5 to 10, testable from outside*

**4.1** — **When** `<input / situation>`, **then** `<output / observable effect>`.

**4.2** — **When** …, **then** …

**4.3** — …

*Identifiers are assigned once and **never reassigned**. Deleting a behaviour retires its identifier for good; the list reorders freely. Never renumber.*

*Invalid if: a sentence describes the inside of the code, or has no "then".*

## 5. Invariants — *what must never happen*

- **5.1** — `<The component never …>`
- **5.2** — `<… never …>`

*Same fixed identifiers as in field 4: assigned once, never reassigned.*

*This field carries everything that is not free: two conforming implementations may differ on anything that is not here.*
*Invalid if: absent, phrased positively, or without an identifier.*

## 6. Derived decisions

| Decision | Parent | Reason |
|---|---|---|
| `<choice made to write the fields above>` | `<parent field or decision>` | `<why>` |

*Invalid if: a decision without a parent or without a reason.*

## 7. Acknowledged gaps — *what the spec deliberately leaves unsaid*

- `<what the spec deliberately leaves unsaid — an unsaid the red must find>`
- …

*Invalid if: empty list — a complete spec is a lie.*

---

## Spec barrier (§2)

This spec is **solid** only if, on top of the red's silence:

- [ ] each behaviour in field 4 carries at least one test that cites it;
- [ ] each invariant in field 5 carries at least one test that cites it;
- [ ] field 7 is not empty;
- [ ] every decision in field 6 has a parent that exists.
- [ ] each element of the component's public input is named by at least one rule in fields 4 or 5 — *an argument that nothing reads lies about what the component does*.

---

## Reciprocity gate — *not a field: the record that the spec survived it* (`protocol.md` §2)

| Behaviour | End-user | Worker | Environment | Ruling |
|---|---|---|---|---|
| 4.1 | *this actor, in this situation, does or undergoes this, with this consequence* | | | no violation · risk → 5.N · violation upheld → refused |

*Invalid if: a behaviour without its three scenarios, or a violation upheld and open. A violation is never moved to field 7.*
