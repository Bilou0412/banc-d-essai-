# Decision log — `<project name>`

First-class artefact of the [protocol](../protocol/protocol.md). **It lives outside the link**: the link is overwritten at every update, this log must never be found in it. Maintained by the human arbiter, never regenerated.

Each decision carries its parent and its reason. **Solid** does not mean final: a decision holds until a fact contradicts it. A decision without a test protecting it is not yet applied; a test without a cited decision is suspect. A decision is never erased: it moves to `lapsed`, with its reason.

Statuses: `solid` · `provisional` · `to-decide` · `lapsed`.

This project numbers its decisions `D1…`. A decision that relies on the protocol cites **the section of `protocol.md` that grounds it** — never a decision number from the protocol's history, which is not copied into a project.

---

## Decisions

| # | Decision | Parent | Reason | Protected by | Status |
|---|---|---|---|---|---|
| **D1** | | | | | |

## Lapsed decisions

| Decision | Why lapsed |
|---|---|
| | |

---

## References measured before the first round

No change brings the **mutation score** of the component it touches below its value here — it is the only one of these lines that is a floor. Warnings must not increase; the others are state readings.

| Reference | Value | Measured on |
|---|---|---|
| Mutation score, per component | | |
| Line and branch coverage | | |
| Number of tests, suite duration | | |
| Compilation warnings | | |

## Proportion — stage and consequence

Verification is proportioned by stage and by consequence class ([`protocol.md`](../protocol/protocol.md) §5). The protocol sets the method; the values are this project's — derived from its aim and the evidence, recorded as `provisional` decisions, shown to the arbiter, never asked (§4).

| Value | Setting | Source | Refuted by |
|---|---|---|---|
| Mutation threshold at hardening — road | | | |
| Mutation threshold at hardening — flight (strictly higher) | | | |
| Bound on spec rounds — the rounds of the exchange before a cold judge | | | |
| Model classes available, ranked, with their price in the budget unit | | | |
| Default class — sketch construction and tests | | | |
| Default class — verdicts and orchestration | | | |
| When the sketch stage is abandoned for this project | | | |

**The debt register** — what is known to be wrong in a sketch, repaid before release. An entry closes when a hardening test covering it passes on the regenerated code.

| # | Unit | Known defect | Found by | Closed by test |
|---|---|---|---|---|
| | | | | |

---

## Findings awaiting sharpening

A finding is recorded **as soon as it is made**; the sharpening waits for the moment it costs the least ([`protocol.md`](../protocol/protocol.md) §6). This table is what guarantees that waiting does not mean forgetting.

A link is **designated** as soon as it carries more than one finding: it is then sharpened at the latest at the next round that touches it.

| # | Finding | Presumed link | Designated? | Prevents the next round? | Sharpened at round |
|---|---|---|---|---|---|
| | | | | | |

**Mind the meaning of a repetition.** Before any sharpening, it designates the link and triggers the correction. After a sharpening, it means the correction did not target the right link — and entails the withdrawal of the protocol. So always note whether a sharpening has already been attempted on this link.

---

## The link with the protocol

The protocol is attached, not copied ([`protocol.md`](../protocol/protocol.md) §6). What this project guarantees, and how:

| What the link must make true | Mechanism in this project | Level |
|---|---|---|
| The project runs on a known state of the protocol | | |
| A drift is visible | | |
| A sharpening goes back up to the protocol | | |

Every update of the protocol is a **decision** — never a side effect — and is recorded above.

| Date | Protocol state before | after | Why now |
|---|---|---|---|
| | | | |

---

## Machine budget — the unit that constrains this project

A round is estimated **before** it is committed ([`protocol.md`](../protocol/protocol.md) §5). The protocol knows no quota: this project declares its own here, in the unit that really constrains it.

If the quota replenishes in windows, both periods are declared — a round that fits in the short window can exhaust the long period in a few rounds.

| | Short window | Long period |
|---|---|---|
| Length of the period | | |
| What a full round consumes, as a share of the period | | |
| Share beyond which a round is not committed and is split | | |
| Bound on a step's estimate — no step exceeds it (§5) | | |
| How a step is closed — the one indivisible record a later session resumes from | | |
| Bound on the steps in flight — an interruption loses all of them (§5) | | |
| How a reading is recorded — its window, when that window resets — and the mechanism that records it; a reading is never required | | |
| Where the steps engaged and not closed are registered — each with its estimate, the consumption its runs report and its round; each round with its stage, what it waits on and the share the arbiter grants it — and how a session that opens reads them | | |
| Projection beyond which every role steps down its ladder | | |

**Ladder per role** — the model classes a role may run on, from the first to the last; the mechanism picks the step from the projection of a valid reading, the session never does; without a projection, the role runs on the default declared here.

| Role | Ladder | Default without a projection | Mechanism |
|---|---|---|---|
| `<red>` | `<…>` | `<…>` | `<…>` |

**Splitting rule.** When a step's estimate exceeds the remainder, it is not engaged and the round is reduced. An interrupted step is re-cut smaller before any retry. In order of preference in this project:

1. `<e.g.: red alone on the existing invariants>`
2. `<e.g.: narrower scope — a single component>`
3. `<e.g.: fewer agents in parallel>`
4. `<wait for the quota to replenish>`

## Verdicts on sharpenings

A sharpening is kept only if its predicted effect appears ([`protocol.md`](../protocol/protocol.md) §6): the effect is written before it is applied, and judged by what this project's mechanisms count on the rounds that follow it — never by a measure the sharpening session writes.

| Sharpening | Predicted effect — measure, direction | What the mechanisms counted, and on which rounds | Kept / undone |
|---|---|---|---|
| | | | |

---

## Rounds run

A round that triggers a sharpening of the protocol ([`protocol.md`](../protocol/protocol.md) §6) notes it here, and reports it to the protocol repository.

| Round | Component | Human time — triage / arbitration / reading | Machine budget — estimated / measured | What was explored | Sharpening triggered |
|---|---|---|---|---|---|
| | | | | | |
