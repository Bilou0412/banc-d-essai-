# Protocol — context-driven development with adversarial agents

This text is the **current state** of the protocol and its **only normative text**: what it is, and why it is so. It carries neither its past, nor promises, nor suppositions presented as rules; what is unknown is said to be unknown.

A **software production system in which the human no longer maintains the code but the protocol that produces it**: agents with disjoint contexts, put into organised friction, whose disagreements bring up to a human arbiter only what can be found nowhere but in them. The code is disposable: it is regenerated from four maintained artefacts — **spec, context, tests, decision log** — and the code satisfies every stated constraint; what is not stated is free.

**Objective: build only what is beneficial to collective well-being.** *Do not do unto others what you would not want done to you.* An adversarial exchange without something it can fail against converges on what persuades, not on what is true: the reciprocity gate is the oracle of the spec (§2), the mechanical barrier the oracle of the code (§3).

**The protocol carries the method and no technology.** No language, platform, runtime or product enters this text: a rule that names a technology dies with it. A project carries its technology and declares, in its **context** — the artefact every session reads —, the mechanism that executes each rule below and its level. A rule without a declared mechanism is not executed; a mechanism without a rule is not auditable.

**The protocol invents no method.** It condenses methods that have a name, so that anyone can check a rule at its source.

| What the protocol does | What it condenses |
|---|---|
| The red attacks, and its silence proves nothing | **Advocatus diaboli**, **red teaming**; **falsifiability** — Popper |
| Everything is pooled, each side forms its position alone | **Hidden profiles** — Lu, Yuan & McLeod, 2012; **Delphi** — Rowe & Wright, 1999 |
| A proposal is attacked, then judged by someone who took no part | **Devil's advocacy and dialectical inquiry** — Mason, 1969; Schwenk, 1990 |
| The arbiter is asked only what depends on them; the rest is answered by a named method, recorded with its evidence | **Pattern languages** — Alexander, 1977; **evidence-based practice** — Sackett et al., 1996; **GRADE Evidence-to-Decision** — Alonso-Coello et al., 2016 |
| What is optimised is the arbiter's time | **Theory of constraints** — Goldratt |
| No feature is built that its builder would not accept undergoing | **The ethic of reciprocity** — the golden rule |
| Roles with disjoint contexts; *by construction* | **Separation of duties**; **Chinese wall**; **poka-yoke** — Shingo |
| Mutation rather than coverage | **Mutation testing** — DeMillo, Lipton & Sayward, 1978 |
| The log: parent, reason, never erased | **ADR** — Nygard, 2011 |
| The cheapest check first | **Ordering by increasing cost** |
| Sketch, then hardening; rigour by consequence | **Stage-Gate** — Cooper, 1990; **validation versus verification** — Boehm, 1984; **software safety classes** — IEC 62304, DO-178C; **technical debt** — Cunningham, 1992 |
| The audit goes back to the faulty rule; it waits for the link to be designated | **Double-loop learning** — Argyris & Schön; **five whys**; **batch size** — Reinertsen |

---

## 1. Roles and what each one sees

| Role | Objective | Sees | Never sees |
|---|---|---|---|
| **Searcher** | Pool everything the collective knowledge holds on the question, each piece read at its source; choose nothing | The arbiter's words or the spec; published sources | Any proposal; the code |
| **Green** (constructor) | Build the work of its layer so that it survives its oracle | Spec layer: the arbiter's words, the dossier, the attacks. Code layer: the rules of the spec, the red tests, the technical context | Spec layer: the code. Code layer: the business justification of each test |
| **Red** (attacker) | Make the work of its layer fail for a good reason | Spec layer: the arbiter's words, the dossier, the proposal or the spec. Code layer: the spec and the public interfaces | The body of the code; the conversation that produced a draft |
| **Cold judge** | Rule on one contested claim at a time | The claim, its anchors, the entries they quote | The exchange; who made the claim |
| **Generator** | Regenerate the component with identical intent | The four artefacts only | The conversation and any earlier implementation |
| **Arbiter** (human) | Describe what the component encodes; answer what depends on them (§4); read tests and decisions | Everything | — |

**One machine, two layers.** The theoretical layer produces the spec, the technical layer the code; on both, the green builds and the red attacks. What changes is what is injected, the conditions each side works under and the oracle. The order follows the cost: the red attacks the spec before any test is written, then the code through tests — a defect found on the text costs a sentence, after delivery a sharpening.

**The exchange.** The searcher's dossier goes to both sides, and each forms its position alone before seeing the other's. What an agent receives is built from the recorded files, never typed by the session. Every claim quotes the arbiter's words or a dossier entry, and the quotation is checked by the machine against its source before any model reads it: a quotation that matches nothing is the author's own choice, and is attacked first. The green answers each attack: it accepts and amends, refutes with a quotation, or declares the point not resolvable — an exit that keeps the impossible from being dressed as solved. The rounds are bounded by the project; what stays contested beyond the bound goes to a cold judge. Agreement between the two stops nothing: the oracle does. The red is one agent, told its layer at each invocation; every claim names its layer, and a claim off its layer is void. It is drawn from another origin than the green — two of one origin share their errors —, and a run where no other origin is available is marked as such.

**Sealing.** Each rule of who-sees-what declares, in the project context, its mechanism and its level:

| Level | What it means |
|---|---|
| **By construction** | the runtime makes the violation impossible |
| **By verification** | a machine detects the violation after the fact |
| **By convention** | a text asks for it; nothing checks it |

An undeclared level is a convention that does not know itself. A condition that only a means can enforce is not left to an instruction: the red and the spec-layer green are given no means to read code, and the green then has one profile per layer. Total sealing does not exist — a public signature already carries intent.

**An agent deprived of reading cannot replace an artefact it produced.** It writes a new one alongside, and the arbiter removes the old one; that cost is paid on every round after the first.

**Nothing here protects against an agent that knows a rule and chooses to override it.** Such a violation is neither prevented nor detected; it reaches the arbiter only if the agent declares it, and that declaration is verifiable by nothing.

---

## 2. The spec

**Intent is the only thing the agents cannot produce; the sentence that carries it, they can.** The breath may be wrested from the arbiter rather than asked of them. What shows that it is theirs is field 3: **the arbiter can say what would make them abandon.** If they cannot, the breath is not theirs. The commitment to abandon is theirs; the threshold that measures it is derived from their intent and the evidence, settled like any derivable choice (§4), and shown to them, never asked.

A spec is a causal chain of decisions, on one page. **Seven fields; an empty field makes it invalid.** A product profile and a technical profile differ in fields 2 and 3; a technical spec has a Product parent and inherits its abandonment criterion — the parent deleted, so is the child.

| Field | Content | Invalid if |
|---|---|---|
| 1. Breath | One sentence: for whom, what problem, why now | several sentences, or no named user |
| 2. Proof of value / acceptance criterion | Product: a figure and a date. Technical: passes or fails without arbitration, and **a wrong implementation fails it** | no figure or date; a criterion only a human can judge; one a trivial implementation satisfies |
| 3. Abandonment criterion | The threshold, or fact, below which the spec is deleted — code, tests, spec — without arbitration | absent or negotiable |
| 4. Observable behaviours | 5 to 10 "when X then Y", testable from outside, **each with a fixed identifier** | describes the inside of the code; a reassigned identifier |
| 5. Invariants | What must never happen; carries everything that is not free; **each with a fixed identifier** | absent, phrased positively, or without identifier |
| 6. Derived decisions | Each choice with its reason and its parent | no parent or no reason |
| 7. Acknowledged gaps | What the spec deliberately does not say | empty — a complete spec is a lie |

**An acceptance criterion is falsified like the behaviour it measures.** One question, asked while writing it: *which wrong implementation would fail here?* A criterion that an inert component satisfies better than the correct one does not measure the code.

**An identifier is not a rank.** It is assigned once and never reassigned; deleting an element retires it, reordering changes none. A test citing a rank keeps passing while protecting something else: the only way to break without any test failing.

### The reciprocity gate

**No spec is valid before it survives the objective.** Each feature carries three anchored scenarios — **the end-user, the worker, the environment**: *this actor, in this situation, does or undergoes this, with this consequence.* A feature violates when its value **relies on** **cognitive exploitation**, a **dark pattern**, **biological exhaustion** or **ecological degradation** — each defined by a source the searcher retrieved, and the violation quotes the definition it meets. A harm that is possible without being relied on is a risk: it becomes an invariant, and a test. The spec is refused while an upheld violation is open; an open violation is never an acknowledged gap. Field 2 names who is better off, by an indicator an exploiting implementation would fail; field 3 names what is abandoned if, after delivery, a measured harm appears on any of the three sides.

### Valid, not solid

**A spec that survives the red is valid, not solid.** The red's silence would make its fatigue a proof. A spec is solid when, in addition: each behaviour of field 4 and each invariant of field 5 is cited by at least one test; field 7 is non-empty; every decision of field 6 has an existing parent; **each element of the component's public input is named by a rule of field 4 or 5** — an argument nothing reads passes every invariant and lies about what the component does; and no upheld violation of the gate is open. A spec is a hypothesis: it holds until a fact contradicts it.

---

## 3. The barrier

**A test cites the rule or decision it protects**, in its name, by the identifier the spec carries. A test that cites nothing is a phantom — the green's silence lets it through —, and a rule no test cites is not applied. Citation checking is mechanical: it reads names, never bodies, and compares them with the spec and the log.

**The red's silence proves nothing.** It can mean "the code is correct" or "the red did not look". On the code layer the red writes tests that fail, from the spec and the public interfaces; **it never sees the body of the code**: the spec and the signatures are given to it, and it has no means to read the rest. Three conditions, checked by the machine, conclude instead:

- **mutation score ≥ the threshold of the component's class**, enforced at hardening, recorded in a sketch (§5) — **coverage proves nothing, mutation does**: coverage is the easiest metric to game;
- **the green modifies nothing it may not touch** — an empty diff on the tests, the spec and the log; a test it judges out of spec is reported, never neutralised;
- **no regression** on neighbouring components.

**The barrier is paid before the dialogue.** The machine is almost free, an exchange of claims is the most expensive thing the protocol has: a crossed barrier settles what a dialogue would discuss, a failed one says where.

**The log.** Each arbitration, with parent and reason. A decision is never erased: it moves to `lapsed` with a reason, because tests cite it. Statuses: `solid` · `provisional` · `to-decide` · `lapsed`.

**Cold regeneration.** A component is regenerated by a generator that receives only the four artefacts, varied in whatever can change its output. Regenerations that pass the tests are compared with one another on inputs outside the tests; a divergence, or an arbitration a regeneration triggers, is a decision that lived in the code — it goes into the log. `k` counts consecutive regenerations without either. A regeneration that fails the tests does not reset `k`: it counts in the generator's failure rate, since it says something about the generator, not the artefacts. The threshold at which a component is declared disposable is set by its spec.

---

## 4. What reaches the arbiter

**Only what can be found nowhere but in the arbiter is asked of them.** One test: *would two equally competent arbiters, with different lives, answer differently?* If not, the answer exists outside them, and the system gives it — the searcher retrieves, the green builds from it, a cold judge settles what stays contested.

What remains is of three classes, and no other:

- **a fact of their life** — a commitment, a practice they actually have, a resource only they can say they hold;
- **their intent, where two of their statements, quoted, give two answers to the case** — the derivation from what they said is attempted first and written; only where it fails is the intent asked, never the judgement;
- **an action no one can undo by the time they read about it, or that goes outward** — on their account, under their name, to someone else, into what propagates beyond the project. A reversible step is executed and reported, never put to them as a permission.

Everything else has another answer: **the collective knowledge**, read at its source, never recalled — an answer that could not be retrieved says so, and is attacked first; **a derivation** from their stated words — a value judgement or a threshold their intent decides; **a default** — a figure or a date with no measurement behind it is set from a published norm when one exists, marked unmeasured, and moved at the first reading; the date stays mandatory, its existence is what keeps "not yet" from lasting forever; **the text of the protocol**. What a mechanism measures or the machine can try — a quota reading, a key, what an account offers — is read or tried, never asked. A question that mixes knowledge and one personal parameter is **split**: only the parameter goes up.

**Routing is executed by a mechanism, never by the session that asks.** Before any question reaches the arbiter it states its class and its anchor — the quotations, the derivation attempted, the action and why it cannot be undone. A cold judge, given only this section and the question, confirms that it is theirs, or names what answers it instead. What it does not confirm is answered as a `provisional` decision — its source, what would refute it, the alternative set aside —, shown to the arbiter, never asked; they can reclaim it at any time. A question that reaches them without that confirmation is misrouted, and counted.

**The form.** A question confirmed as theirs fits in five lines and is answered with one letter; one question at a time:

```
[class, anchor]
QUESTION: one sentence, with no protocol term.
A: the option — what it costs.
B: the option — what it costs.
I recommend A, because <one sentence>. I would change my mind if <a fact>.
```

No word the arbiter does not use themselves enters it. A request is phrased so that all its answers cost the same: "what is wrong here?" manufactures a defect. **Where the component encodes a practice the arbiter has**, nothing it frames — an option, a method, a model of the domain — is answered before they have described it in their own words: what is injected first frames the answer instead of collecting it. Where they have a word, theirs stays in the spec. **Triage** is not a question put to them, and passes no routing: it is their reading of the red's tests (§1). It comes one test at a time, in their words, without code; it ends when every test has a verdict, and zero rejections is a result when its cause can be named.

---

## 5. Cost

A round consumes two resources. **Human time** is overrun — the round completes, and it is timed. **The machine budget** runs out — the work in progress is lost. The second is **estimated before**, in the unit that really constrains the quota, over the short window and the long period when both exist.

**A round is a stack of small steps; the step is what is estimated, gated and saved.** No step's estimate exceeds the step bound the project declares, and the steps in flight are bounded too: an interruption loses at most that bound times the step bound, never a closed step. A step is closed by one indivisible record; an incomplete record is discarded, and a later session resumes after the last closed step. An interrupted step is re-cut smaller before any retry. A step is shortened while the work redone after an interruption costs more than closing a step; below that point, shortening only adds overhead.

**The step register** holds the steps engaged and not closed, with the consumption each run reports — a run that reports nothing counts at its estimate —, and every session that opens reads it. **The gate**: what remains is the last valid reading of the quota, minus what the step register counted since it, minus the estimates of the steps engaged and not closed; a step whose estimate exceeds it is not engaged. A reading names its window and lapses at its reset; it is recorded the moment it exists and is never required: without one, the gate is the step bound and the bound on steps in flight.

**The budget rule is executed by a mechanism, never by the session's memory.** The **projection** is computed, not judged, from a valid reading: the share consumed divided by the share of its period elapsed. The model class of each role follows from it by a ladder the project declares, at its default without one. The arbiter's word about the budget starts the computation; it does not replace it.

**Proportion.** Each unit has a **stage** and a **class**. A **sketch** validates — *the right thing?*: its spec is attacked once, through the gate; only the tests are lightened, and mutation is recorded, not enforced. **Hardening** verifies — *built right?*: code regenerated from the attacked spec, never promoted; a fresh red suite; the class's threshold enforced; providers before dependents. A unit is **flight** when a failure is irreversible for someone else, or it handles personal data or money — reads, adds, transforms or forwards it — a higher threshold, more than one judge, from its sketch on — and **road** otherwise; the higher class wins while contested. What a sketch leaves known to be wrong is in a **debt register**, repaid before release; nothing is sold or promoted before every unit is hardened. The stage lightens the tests, never the spec nor the gate. The values are the project's, declared in its log.

---

## 6. Sharpening

**The protocol is sharpened by producing.** It has no version and no freeze: a current state. Each round on a real project trains it.

Three findings, and three only, trigger a sharpening:

1. a defect on a **written** constraint escaped delivery;
2. a round cost more human time than its initial estimate;
3. a round exceeded its machine-budget estimate, or was interrupted for lack of budget.

A defect on **the unsaid** is not one: it is the product of the protocol, and becomes a project decision.

**The finding is recorded at once; the sharpening waits.** An isolated finding is a hypothesis about its link; **a repetition on the same link designates it**. A finding that blocks the next round is sharpened immediately; a designated link at the latest at the next round that touches it; otherwise it waits, recorded with its presumed link. The cheapest moment is also the last one allowed.

**How.** A full audit — text, context, code concerned —, **traced back to the link**: where the breakage shows and where the logic gave way are rarely the same. The faulty rule is modified **in place**; an addition only if nothing covers the case. **Zero regression**: the suite stays green, no mutation score falls below its reference, no `solid` decision is contradicted without moving to `lapsed`, every sealing rule keeps its mechanism, and **every document that restates a changed rule is reopened** — a copy drifts silently, so each document declares what it restates, by a mechanism. A sharpening is a round: it is estimated before. It writes its predicted effect first — which measure, in which direction —, and is judged by what mechanisms count on the rounds that follow it: the questions misrouted to the arbiter, the defects that escape delivery, what the step register records as consumed and lost. No measure in a verdict is written by the session that sharpened. A sharpening whose predicted effect does not appear is undone in place, and its finding stays recorded.

**The link.** A project runs on a known state of the protocol, a drift between them is visible, and a sharpening goes back up to the protocol: whatever tool carries the link must make those three things true. What belongs to the project — spec, log, context, agents — never lives in the link. The current state absorbs what is learned; its story lives in a separate compartment that nobody needs in order to apply it.

**What kills the protocol.** Not cost, nor an exhausted budget: a quota reached means the round was too big. **The same finding recurring after the sharpening meant to prevent it** withdraws the protocol — agents, dialogue, barrier —, and the project returns to its previous method. **Its artefacts stay with it**: spec, tests and log are the project's, and a decision is never erased. A repetition **before** a sharpening designates the link; **after**, it withdraws the protocol. Withdrawal fires without arbitration, like any field 3: the arbiter's commitment is given in advance, and setting it aside is recorded as a lapse of the criterion, with its reason. The protocol carries its own Product spec, with its abandonment criterion.
