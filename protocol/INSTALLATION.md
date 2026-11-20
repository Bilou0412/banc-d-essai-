# Installing the protocol in a project

Five steps. None touches production code.

## 1. Attach the protocol

The protocol is **attached** to the project, it is not adopted by it — the project carries it and never edits it (`protocol.md` §6, "The link"). Three things must become true: the project runs on a known state of the protocol, a drift is visible, and a sharpening goes back up to the protocol.

`tools/link.py` makes all three true with plain files — the state is the commit recorded in `protocol/STATE`, a drift is an open update on the project, and an edit made from the project breaks the seal, so a sharpening can only go up:

```bash
python3 <protocol-checkout>/tools/link.py <your-project>
git add protocol .claude && git commit -m "Attach the protocol"
```

It writes `protocol/` and copies the agents and the command into `.claude/`, with the link at the top of each already pointing to `protocol/protocol.md`.

**What is yours never lives in the link.** `protocol/` is overwritten at every update: everything that belongs to you stays outside.

```
<your-project>/
  protocol/                      ← the link. Not edited from the project.
    protocol.md · templates/ · .claude/agents/ · .claude/commands/ · tools/
    STATE                        ← the commit it was taken from, and its seal
  docs/
    decision-log.md              ← yours, copied from protocol/templates/
    product-spec.md              ← your project's Product spec
    protocol-here.md             ← copy of protocol/protocol-product-spec.md;
                                   what the protocol must prove to you, and when you abandon it
  .claude/agents/
    searcher.md · green-spec.md · green.md · red.md · judge.md
                                 ← copied from protocol/.claude/agents/; they are
                                   your binding to the runtime, so they belong to you
```

`history.md` stays in the link: it is the protocol's past, not yours. Your past is your log.

Add the two checks to your continuous integration — they are the *by verification* level of the link:

```bash
python3 protocol/tools/link.py             # the link was not edited from the project
python3 protocol/tools/project-agents.py   # the agents are those of the linked state
```

### Why a copy and not a submodule

A submodule is fetched only by a clone that asks for it. A runtime that clones the project alone — a hosted session, a default continuous-integration checkout — finds an empty folder, **and a session that does not find the protocol does not stop: it works without it.** A privately hosted protocol adds a second failure: no one but its owner can fetch it at all. A copy is there for whoever has the project.

What a copy costs is what `protocol.md` §6 says of every copy: it drifts. The seal and the update below are what pay for it.

### Updating the link

1. **The update never applies itself.** When the protocol changes, `.github/workflows/propagate.yml` opens an update on every project listed in `projects.txt`. Merging it is a decision, recorded in the log like the others, and it is taken **at a round boundary, never during one**: a rule that changes in the middle of a round would have one rule followed in its first half and another in the second, without anything signalling it.
2. **A sharpening starts in the protocol repository, never in `protocol/`.** The seal refuses the other way round. Record the finding in your log, carry it to the protocol repository, and let the update bring it back down.
3. **A check that calls a tool from the link depends on the linked state, not on the current state of the protocol.** Adding the tool to the protocol and the step to the project in the same stroke fails until the update is merged. Add the step **with the update that brings the tool**, never before.

## 2. Paste the context block

The content of [`protocol/templates/CLAUDE.section.md`](templates/CLAUDE.section.md) goes into your project's root context file. It is what every session reads; without it, the protocol is only a folder.

It carries the **Sealing mechanisms** table: for each rule of the protocol ([`protocol.md`](protocol.md) §1), what *your* runtime guarantees it with and at what level — *by construction* (the violation is impossible), *by verification* (a machine detects it after the fact), *by convention* (a text asks for it; nothing checks it). An undeclared level is a convention that does not know itself. This table is rewritten when you change runtime — it is the part most exposed to drift.

This block is also the **only piece of the protocol that names an engine**: the name of the context file and the path of the agents are those of your runtime.

## 3. Write the protocol's Product spec — for your project

Open your copy, `docs/protocol-here.md`. **The arbiter** — you — fills in, alone or with `/spec`:

- **field 1, the breath**: one sentence, for whom, what problem, why now;
- **field 2, the proof of value**: the fact verifiable by a third party, and **the date** on which it is reread — set by default, marked unmeasured, and moved by you if it does not fit your life (§4);
- **field 3, the abandonment criterion**: already written — the protocol dies of having stopped learning; to be confirmed.

An empty field makes the spec invalid. Without it, the protocol has no reason to die, and therefore no reason to live — and none of its technical components has a parent.

## 4. Fill the log before starting

Your `decision-log.md` carries four tables beyond the decisions themselves. Two are filled **before** the first round; two stay empty until there is something to put in them.

**Your runtime's sealing mechanisms.** Each rule of the protocol ([`protocol.md`](protocol.md) §1) declares here what *your* runtime guarantees it with, and at what level — construction, verification, convention. An undeclared level is a convention that does not know itself. It is the part that depends on the engine, and the most exposed to drift: it is rewritten when you change runtime.

**The measured references.** The protocol is justified only by numbers. Measure, with your language's tooling:

| Reference | How |
|---|---|
| Mutation score per component | your language's mutation tool |
| Line and branch coverage | your language's coverage tool |
| Number of tests and suite duration | your runner's listing option |
| Compilation warnings | frozen, not to be increased |

These values are the **reference thresholds**: no modification lowers the mutation score of the component it touches.

**The machine budget.** The protocol runs agents, and these agents consume a quota. Declare yours in the unit that really constrains you — if your quota replenishes in windows, declare the short window **and** the long period: a round that fits comfortably in one can exhaust the other in a few rounds. Set the share beyond which a round is not committed, and your splitting order. Then give this rule a **mechanism**, as for a sealing rule: a register of the steps engaged and not closed, read by every session that opens, into which each run's reported consumption is counted (a run that reports nothing counts at its estimate); a bound on the steps in flight; each quota reading recorded the moment it exists, with its window and when that window resets, lapsing at the reset; the projection computed from a valid reading; and the model class of each role set from a ladder you declare, with a default for when there is no projection. A reading is never required: without one, the step bound and the bound on steps in flight are the gate, and an interruption loses at most those steps. A budget kept in a session's memory is kept until the next reminder is forgotten.

A round committed without an estimate can be interrupted for lack of budget: the work not yet closed is lost, the quota too, and nothing has been learned. It is the only way to spend without learning anything.

**The findings awaiting sharpening.** The table stays empty until the first finding. It is what guarantees that waiting for the right moment does not mean forgetting.

**The rounds run.** The table stays empty until the first round.

## 5. The first round

0. **Estimate the cost before committing**: the human time you expect to spend on it, and what the round will consume of your quota — as a share of the short window and of the long period. Cut the round into **small steps**, each under the bound you declared, each estimated and closed by one indivisible record when it completes (§5): an interruption then loses only the step in progress. A step whose estimate exceeds what remains is not engaged; an interrupted step is re-cut smaller before any retry.
1. **Choose a component**: small, pure, no I/O, rich in edge cases, independent of the rest. The first round tests the protocol, not the component.
2. **Produce its spec** with `/spec`, in the §2 format ([`templates/technical-spec.md`](templates/technical-spec.md)) — deliberately incomplete, at least one edge case unsaid. The command runs the theoretical layer — searcher, green against red on two different models, cold judge, reciprocity gate — and asks you only what can be found nowhere but in you: what comes out is **valid, not solid**. Declare in your log the bound on attack rounds; it is unmeasured until read. Record in the spec the component's **stage** — sketch, then hardened — and its **consequence class** — road, or flight when a failure is irreversible for someone other than you or it handles personal data or money (§5).
3. **Invoke the red** with the spec and the public signatures *pasted into the prompt* — it has no read tool. It writes tests. **If tests already exist, remove them first**: deprived of reading, it cannot overwrite them, and it will drop its work beside them.
4. **Triage**: read the red tests **one by one**, and give each a verdict. A rejection is justified by a reason that refines the spec. **Zero rejections is a result** — provided you can say why: the defects were found earlier, and where. If you cannot say it, you have not triaged. A refined spec **goes back to the red** before going to the green (§1).
5. **Invoke the green** with the code, the retained tests and the **searcher's technical dossier** — run the `searcher` on the spec for it, as `/spec` step 8 does. It chooses what the spec leaves free from that dossier, inside the invariants. It implements. It does not touch the tests.
6. **Mechanical barrier**: green tests are the prerequisite; the barrier is the three conditions of §3 — mutation score ≥ the spec's threshold, empty diff on the tests, the spec and the log, no neighbouring component regressed. In a sketch, the mutation score is recorded, not enforced; it is enforced at hardening, at the threshold of the component's class (§5).
7. **Arbitrate** what is contested. **Record** each decision in the log — parent, reason, what protects it — **and in the context** if it changes a working rule. A recorded decision **goes back to the red** (§1).
8. **Time** your human time — triage, arbitration, reading. Without this measurement, the second sharpening trigger cannot be evaluated.
9. **Measure the machine budget actually consumed**, and compare it to the step 0 estimate. It is the gap, not the absolute value, that teaches you to estimate.
10. **Note the round** in your log: component, human time, estimated and measured budget, what was explored, sharpening triggered or not.

## Then: sharpening

Reread [`protocol.md`](protocol.md) §6. Three findings, and three only, trigger a sharpening:

1. a defect on a **written constraint** of the spec escaped delivery;
2. the round cost more human time than your initial estimate for the component;
3. the round overran its machine budget estimate, or was interrupted for lack of budget.

A defect on **the unsaid** is not one: it is the product of the protocol, and it becomes a decision in your log.

**Record the finding right away; do not sharpen right away.** Note it in the "Findings awaiting sharpening" table of your log, with the link you suspect. An isolated finding is only a hypothesis: correcting the wrong link makes it come back, and a finding that comes back after correction entails the withdrawal of the protocol. A repetition on the same link **designates** it — and only then is the correction sure to aim right.

Three cases end the wait: a finding that **prevents the next round** is sharpened immediately; a **designated link** is sharpened at the latest at the next round that touches it — you are already there, everything is loaded, it is the cheapest moment and it is the last one allowed; otherwise, it waits.

A finding is not corrected with a patch: full audit — text, context, code concerned —, modification **in place** of the faulty rule, an addition only if nothing covers the case, zero regression. **Report the sharpening to the protocol repository**: that is how it learns.

**A sharpening is kept only if its predicted effect appears** (§6). It writes that effect first — which measure, in which direction — and is judged by what your mechanisms count on the rounds that follow it: the questions misrouted to you, the defects that escape delivery, what your step register records as consumed and lost. No measure in its verdict is written by the session that sharpened. If the effect does not appear, the sharpening is undone in place, and its finding stays recorded.

A cost overrun is never read as "by hand would have been better". Count what was explored — unanticipated red tests, surfaced decisions.

---

## What is not provided

- **The claim validator.** Its schema is in `templates/claim.yaml`; it is not built. The first round is done with the arbiter in that role, by hand.
- **A mutation tool.** Choose your language's; the protocol does not depend on the tool, only on the score.
- **A guarantee that it works.** The protocol has run twice and has been sharpened each time. **Only one round has been measured** — a pure function of eighty lines, 8 h 29 of wall-clock time, 1 h 30 of human time, 6 points of a weekly quota — and it produced a component that passes its own barrier. One measurement point is not a law: do not extrapolate to a component that does input/output. What you say about it after **your** round will be worth more than this repository.
