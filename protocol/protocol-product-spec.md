# Product spec — the protocol itself

| | |
|---|---|
| **Profile** | Product ([`protocol.md`](protocol.md) §2) |
| **Why it exists** | The protocol is not exempt from what it demands. A system that audits itself, consolidates itself and offers to build itself, with no proof of value and no abandonment criterion, is in self-referential drift. This spec gives it a Product parent for its technical components and **a death condition**. |
| **Status** | **Invalid.** Field 1 is filled and owned by the arbiter; field 2 still has no date. An empty field makes the spec invalid. |
| **What it restates** | [`protocol.md`](protocol.md) §2 (the seven fields and their fixed identifiers), §5 (the two costs), §6 (the three triggers, the verdict of a sharpening, the withdrawal). A change to these sections reopens it (§6). |
| **Who fills what** | The human writes the breath and sets the **date** of field 2: it commits their rereading, no agent sets it on their behalf. The rest is generated, attacked by the red, then validated by the human, who remains the owner of the spec. |

> **For a project adopting the protocol:** copy this file, fill fields 1 and 2 for *your* project, confirm field 3. The claim validator is the Technical child of this spec — without it, it has no parent.

---

## 1. Breath — *for the arbiter, one sentence*

>  *Pour les communautés qui veulent une technologie de pointe sans exploitation, dont l'intelligence collective reste inutilisée et dont les outils servent ceux qui les possèdent, ce protocole transforme une intention humaine en logiciel vérifié et bénéfique au bien-être collectif, maintenant que des agents peuvent exécuter tout ce qui n'appartient qu'au savoir.*
>
> *For the communities that want frontier technology without exploitation, whose collective intelligence stays unused and whose tools serve those who own them, this protocol turns a human intent into software that is verified and beneficial to collective well-being, now that agents can carry out everything that belongs to knowledge alone.*
>
> Wording wrested from the arbiter's words and validated by them; the original, in French, is theirs.
>
> This breath is **a spec**: implementable, modifiable, improvable — not a sentence carved in stone. It opens twice: it launches the project, and what the project makes of it comes back to sharpen the protocol.
>
> *Invalid if: several sentences, or no named user.*

## 2. Proof of value — *the date: set by default, moved by the arbiter*

> *On **`DD/MM/YYYY`**, **every component delivered under the protocol** has reached, at its first delivery, **the mutation threshold set by its own spec** — and at least one component has been delivered.*
>
> No component, no threshold, no tool is named here: each Technical spec carries its own. Verifiable by anyone with the mutation tool of the project's language.
>
> The date is **the day the arbiter rereads the proof**, not a delivery date. It falls after several components have been delivered and a period of use. Without a date, "not yet" always remains admissible and the proof never falls.
>
> *Invalid if: no figure, no date, or a figure only the human can judge.*

## 3. Abandonment criterion

> **What kills the protocol is having stopped learning.**
>
> *Every failure finding is **recorded as soon as it is made** and produces a **sharpening** at the moment it costs least. Three findings, and three only: (1) a defect on a **written constraint** of the spec escaped delivery; (2) a round cost more human time than the component's initial estimate; (3) a round overran its machine budget estimate, or was interrupted for lack of budget.*
>
> *The protocol is **withdrawn** — agents, log, specs, return to the prior method — if **the same finding recurs after the sharpening meant to prevent it**. A repetition occurring **before** any sharpening does not count: it designates the link and triggers the correction.*
>
> **How sharpening is done** ([`protocol.md`](protocol.md) §6): full audit — text, context, code concerned — then in-place modification, an addition only if nothing covers the case, verifiable zero regression.
>
> **Reading rule**: an overrun of type (2) is **never** read as "by hand would have been better". Human time and machine exploration do not have the same value; what was explored is counted — unanticipated red tests, surfaced decisions. A finding of type (3) is **never** read as "the protocol costs too much": a quota reached says the round was too big for it, and the round is split. Defects on **the unsaid** are not failures of the protocol: they are its product.
>
> *Invalid if: absent, or negotiable. It is the only line that gives the protocol a reason to die, and therefore to live.*

---

## 4. Observable behaviours — *generated, attackable*

*Identifiers assigned once, never reassigned (§2). Deleting a behaviour retires its identifier for good; the list reorders freely.*

**4.1** — **When** a valid spec is handed to the protocol, **then** it produces an implementation that passes all the red's tests without any test having been modified by the green.
**4.2** — **When** a red test is contested by the green, **then** a cold judge settles it on two anchored claims, the arbiter only if a cold judge confirms it depends on them, and it ends with a recorded decision; **when** it is not contested, **then** it does not reach the arbiter.
**4.3** — **When** the code of a component under the protocol is deleted and regenerated from a cold session, **then** the regeneration passes all the tests; **when** two regenerations diverge on the same inputs, **then** a decision is recorded and `k` restarts.
**4.4** — **When** a green agent modifies a test, **then** the mechanical barrier fails and the work is invalidated, whatever the state of the tests.
**4.5** — **When** a round is run, **then** its human time is timed, split between triage, arbitration and reading, and its machine budget is measured then compared to the estimate made before committing.
**4.6** — **When** a step's budget estimate exceeds the remaining quota, **then** the step is not engaged — it is re-cut or deferred; **when** no valid reading exists, **then** no step is refused for want of one — the step bound and the bound on steps in flight are the gate; **when** the quota runs out, **then** the loss is the steps in flight, never a closed step, and it is recorded at its counted size.
**4.7** — **When** a decision is recorded, **then** it carries a parent, a reason, and a test or artefact that protects it — or its status says it is not yet applied.
**4.8** — **When** a failure finding is made, **then** it is recorded immediately with its presumed link; **when** the link is designated by a repetition, **then** the sharpening happens at the latest at the next round that touches that link; **when** the finding prevents the next round, **then** the sharpening happens immediately.
**4.9** — **When** a sharpening is committed, **then** a full audit precedes any modification; **when** the modification is applied, **then** the non-regression barrier passes — otherwise the modification is refused.
**4.10** — **When** the same finding recurs after the sharpening meant to prevent it, **then** the protocol is withdrawn without arbitration; **when** it recurs before any sharpening, **then** the link is designated and the correction is triggered.
**4.11** — **When** a sharpening is applied, **then** it carries the effect it predicts — a measure and a direction — and it is judged by what mechanisms count on the rounds that follow it: the questions misrouted to the arbiter, the defects that escape delivery, what the step register records as consumed and lost; **when** the predicted effect does not appear, **then** it is undone in place and its finding stays recorded.

## 5. Invariants — *generated, attackable*

*Same fixed identifiers as in field 4.*

- **5.1** — The red **never** reads the body of the generated code.
- **5.2** — The green **never** modifies a test.
- **5.3** — No agent **ever** speaks directly to another agent.
- **5.4** — The validator **never** judges the substance of a claim.
- **5.5** — A decision is **never** erased: it becomes `lapsed`.
- **5.6** — The protocol is **never** tied to a language, a platform, a runtime or a product.
- **5.7** — The strict text of the protocol **never** carries past, future, or supposition presented as a rule.
- **5.8** — The protocol is **never** exempt from its own proof of value or its abandonment criterion.
- **5.9** — An agent's silence is **never** a proof.
- **5.10** — A cost overrun **never** concludes in abandonment on its own; it produces a recorded sharpening.
- **5.11** — A round is **never** committed without its machine budget having been estimated.
- **5.12** — The protocol **never** sets a quota, a budget unit or a per-round spending cap: the project declares its own.
- **5.13** — A finding **never** waits to be sharpened before being recorded.
- **5.14** — A repetition occurring **before** any sharpening **never** entails the withdrawal of the protocol.
- **5.15** — The dialogue is **never** engaged before the mechanical barrier has been paid.
- **5.16** — A correction is **never** stacked beside the faulty rule: it replaces it.
- **5.17** — The red, on the spec layer, **never** sees the code, nor the conversation that produced the draft it attacks.

## 6. Derived decisions — *generated, attackable*

| Decision | Parent | Reason |
|---|---|---|
| The protocol is the Product parent of its own technical components, including the validator | Technical → Product lineage | Without this parent, no component of the protocol can have a valid Technical spec |
| Field 3 entails the withdrawal of the agents, the log and the specs, and the return to the prior method | non-negotiable abandonment criterion | An abandonment criterion that does not say what is removed is negotiable |
| Proof of value is measured on components **delivered and regenerated**, not on documents produced | field 2, proof of value | The protocol can produce text about itself indefinitely; only regenerated code counts |
| Time does not have the same value on both sides; the result of a round includes **what was explored** | reading rule of field 3 | Measuring the protocol in human hours alone ignores what those hours buy |
| The machine budget is estimated **before** committing a round, in the unit that constrains; human time is timed during | finding (3) of field 3 | Human time is overrun without preventing completion; the machine budget runs out and interrupts everything. A resource that can stop the round is counted before, not after |

## 7. Acknowledged gaps — *generated, attackable*

- The cost of a full round is unknown, in human time as in machine budget. This spec does not set it; each round estimates it before and measures it after.
- It does not say how a machine budget is estimated as long as no round has been measured — the first estimate is made without a reference, and it is the measured gap that teaches estimation.
- The value of `k` is unknown.
- The technical sealing of the red is partial, and its degree depends on the project's runtime.
- This spec does not say **who** the arbiter is day to day nor how much time they devote to it.
- It does not say how the proof of value is **collected** — by hand, or by a metric of the integration pipeline.
- It does not say what happens to components already delivered under the protocol if field 3 triggers the withdrawal.
