## Working method — adversarial protocol

This repository applies the **context-driven development protocol with adversarial agents**: [`protocol/protocol.md`](protocol/protocol.md).

> **Technical binding.** This block is the only piece of the protocol that names a tool: the link through which the protocol is attached to this project, the context file that sessions read and the agents' path are the ones used here. A project on other tooling replaces them with its own — the protocol itself knows none.

Four artefacts are maintained — **spec, context, tests, decision log**. Code is not one of them: it can be regenerated from the other four. The human arbitrates and reads; they do not write the code.

**The protocol is attached, never edited here** (`protocol.md` §6, "The link"). It lives in `protocol/` and is not edited from this project. What belongs to us — spec, log, context, agents — lives **outside** the link: the link is overwritten at every update. A sharpening is carried to the protocol repository, then an update of the link is merged here, and that is a decision recorded in the log.

**Two planes, compartmentalised.** The protocol carries the method and no technology. This project carries the technology and remains a project: the protocol establishes the method in it, never the tool. Nothing specific to this project — language, framework, runtime, thresholds — goes up into the text of the protocol.

| To read | When |
|---|---|
| [`protocol/protocol.md`](protocol/protocol.md) | The current state of the protocol. Before taking a ticket. |
| [`docs/decision-log.md`](docs/decision-log.md) | Before reopening a decision — and after taking one. It also carries the reference thresholds and the findings awaiting sharpening. |
| [`.claude/agents/searcher.md`](.claude/agents/searcher.md) · [`green-spec.md`](.claude/agents/green-spec.md) · [`judge.md`](.claude/agents/judge.md) · [`red.md`](.claude/agents/red.md) · [`green.md`](.claude/agents/green.md) | Before invoking an agent of the protocol. |

**The protocol is sharpened by producing** (`protocol.md` §6). It has neither version nor freeze: a current state. Three findings, and three only, trigger a sharpening — a defect on a **written** constraint that escaped delivery; a round more costly in human time than the component's initial estimate; a round that overruns its machine budget estimate or is interrupted for lack of budget. A defect on the **unsaid** is not one: it is the product of the protocol, it becomes a decision of this project.

**The finding is recorded at once; the sharpening waits for the right moment** (`protocol.md` §6). An isolated finding is only a hypothesis about the link; a repetition on the same link **designates** it. A finding that prevents the next round goes immediately; a designated link goes at the latest at the next round that touches it; otherwise it waits, recorded in the log with its presumed link. Beware: a repetition **before** sharpening designates the link, **after** it withdraws the protocol.

**Estimate before committing** (`protocol.md` §5). A round consumes human time, which is overrun without preventing completion, and a machine budget, which runs out and interrupts everything. The latter is estimated **before**, in the unit that really constrains this project's quota — short window and long period if both exist. A round is a stack of small steps, each under the bound declared in the log and closed by one indivisible record: an interruption loses the step in progress, never a closed step. What remains is the last valid reading minus what the register counted since it and the estimates of the steps already engaged and not closed; a step that exceeds it is not engaged. A reading is never required: without one, the step bound and the bound on steps in flight are the gate. An interruption loses the steps in flight, at most their bound times the step bound, and an interrupted step is re-cut smaller before any retry: splitting costs a little, the loss is one step. This rule is executed by the mechanism declared in the table below, never by the session's memory.

**The barrier is paid before the dialogue** (`protocol.md` §3) — the machine before the model: a crossed barrier settles what a dialogue would discuss, a failed one says where.

**Verification is proportioned** (`protocol.md` §5). Each unit carries a stage — sketch (validation, the spec attacked once, few tests, mutation recorded) then hardened (verification, code regenerated, the class's threshold enforced) — and a consequence class — road or flight. Flight and the reciprocity gate are never deferred; nothing is sold or promoted before every unit is hardened. This project's values are in its log.

**A sharpening is not fixed with a patch**: full audit first — text, context, code concerned —, tracing the causal chain back to the **link**, then modification **in place** of the faulty rule, addition only if nothing covers the case, and **zero regression**: green suite, no mutation score below its reference, no `solid` decision contradicted without moving to `lapsed`, every sealing rule keeps its declared mechanism.

**A sharpening is kept only if its predicted effect appears** (`protocol.md` §6): the effect written first — a measure and a direction —, judged by what mechanisms count on the rounds that follow (questions misrouted to the arbiter, defects that escape delivery, what the step register records as consumed and lost), never by a measure the sharpening session writes; otherwise undone in place.

**Only what can be found nowhere but in the arbiter is asked of them** (`protocol.md` §4). The rest is execution: the searcher retrieves, the green builds, the red attacks, a cold judge settles — on both layers, one machine. **The session that asks does not route its own question**: before any question reaches the arbiter, it states its class — a fact of their life, their intent where two quoted statements contradict, an outward or irreversible action — with its anchor, and a cold judge who sees neither the exchange nor who asks confirms it is theirs; what it does not confirm is answered as a `provisional` decision with its trace. This rule is executed by the mechanism declared in the table below.

**The reciprocity gate** (`protocol.md` §2): no spec is valid while a feature relies on cognitive exploitation, a dark pattern, biological exhaustion or ecological degradation — simulated from the end-user, the worker and the environment.

Four rules that override comfort:

- **The red never sees the body of the code.** Invoke it with the spec and the signatures pasted into the prompt — it has no read tool.
- **The green never modifies a test, the spec or the log.** The diff on them must be empty after it has passed; otherwise all its work is invalidated.
- **A test cites the spec rule or the decision it protects**, in its name: `Rule_4_7_…`, `Invariant_5_3_…`, `Decision_D12_…`. The number is **the identifier the spec carries**, never a rank recounted in the list. A decision without a test is not applied; a test without a decision is suspect.
- **Coverage proves nothing, mutation does.** Never present a coverage percentage as a guarantee.

## Sealing mechanisms — what this runtime guarantees

Each sealing rule of the protocol ([`protocol.md`](protocol/protocol.md) §1) declares here the mechanism that guarantees it in **this** project, and its level: *by construction* (the runtime makes the violation impossible), *by verification* (a machine detects the violation after the fact), *by convention* (a text asks for it; nothing checks it).

An undeclared level is a convention that does not know itself. This table is rewritten when the project changes runtime.

| Rule | Mechanism in this project | Level |
|---|---|---|
| The searcher does not see any proposal | | |
| The green and the red form their positions alone, do not know each other's identity, and run on different models | | |
| The green on the spec layer has no means to read code | | |
| Every claim names its layer; a claim off its layer is void | | |
| Every quotation of the theoretical layer is checked against its source | | |
| The cold judge sees neither the exchange nor the names | | |
| The red, on the spec layer, sees neither the code nor the conversation that produced the draft | | |
| The red does not see the body of the code | | |
| The green does not modify the tests | | |
| The green does not see the business justification | | |
| The agents do not speak to each other | | |
| The budget rule (§5): the register of steps engaged and not closed, with the consumption each run reports, read by every session that opens; the bound on steps in flight; each quota reading recorded with its window, lapsing at its reset, never required; the projection computed from a valid reading; the model class of each role set by the declared ladder, at its default without a projection | | |
| Routing (§4): no question reaches the arbiter without its class, its anchor and a cold judge's confirmation that it is theirs | | |
| The validator does not judge the substance | | |
| The context is read by every session | | |
| A document that restates a rule is reopened when the rule changes (§6) | | |
