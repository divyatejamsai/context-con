# Company rules: set without code, enforced when agents act

Admins and owners write rules in the console (**Workspace > Rules**) from four templates. Agaxes enforces them at the
moment an agent acts, in Send Guard, the approval inbox and the runtime, and every block or hold names the rule (and its
version) in the inbox, on the task and in the plain-language ledger.

| Template | Example sentence | Where it's enforced |
|---|---|---|
| Big offers need more approvers | Offers over ₹30L need 2 approvers | Offer letters: the approval stays pending until N **different** people approve. The same person approving twice is refused (409). The amount is read from the compensation line (₹42 LPA, 35 lakh, ₹1.2 Cr, $120k at ₹84/$); an amount that can't be read counts as over (fail closed). An edit restarts the count |
| No outreach at night | No outreach between 20:00 and 08:00 IST; messages wait until then | Sends: a draft in the window goes to the approval inbox even for an agent allowed to send on its own; approving inside the window returns 409 and it stays pending. With effect "block", Send Guard blocks it. A direct MCP `send_message` in the window is blocked |
| Never contact people at these companies | Sourced may never contact people at our clients (Razorpay and Zepto) | Send Guard: a `company_rule` check fails, so the draft never reaches a person. Re-checked at send time, so a draft written before the rule is blocked when approved. Matches the recipient's (guard-verified) company, or the email domain |
| Daily cap | Each AI employee may send at most 20 messages a day | Sends, tasks, Crustdata calls (spend) or AI calls, per agent ("each") or summed over the agents in scope ("together"). A task over the cap waits in the queue; a call over it stops the task; an approval over it is blocked at send |

**Scope.** A rule covers the whole company or named AI employees. It belongs to the writer's workspace; one written in
open mode or by the platform operator covers every company (and company admins can see but not edit it).

**Versions and audit.** Every change bumps the version and keeps the old version in the rule's history (soft delete:
history stays). Ledger kinds: `rule.created`, `rule.updated` (with `before` and `changed`), `rule.enabled`,
`rule.disabled`, `rule.deleted`, and `rule.enforced` every time a rule blocks, holds or asks for more approvers
(`rule_id`, `version`, `sentence`, `effect`, `detail`, `action`, `outcome`, `agent_id`, `to`). `offer.signed` lists the
approvers and the rules that applied. Rules apply when the person or agent acts, so a rule added after a draft still counts.

**Who.** Reads: viewer and up. Create, edit, turn off, delete: admin, owner (or the operator).

## API
```
GET    /api/rules                 rules, templates, recent enforcement, can_edit
POST   /api/rules/preview         {type, params, agents}  -> the sentence, or the error (nothing saved)
POST   /api/rules                 {type, params, agents?, name?, enabled?}
PUT    /api/rules/{id}            {params?, agents?, name?, enabled?, note?}
DELETE /api/rules/{id}
GET    /api/rules/{id}            with version history and its enforcement log
```
Code: `backend/app/rules/engine.py` (store, sentences, checks), `api.py`. Tests: `backend/tests/test_rules.py`.

## Demo (hiring flow)
1. Sign in as the demo admin. **Rules > Suggested rules > "Offers over ₹30L need 2 approvers" > Add this.**
2. **Live work > Start hiring flow** (default compensation ₹42 LPA). The offer card shows the rule and "Approver 1 / Approver 2".
3. **Approve and sign**: "Approved (1 of 2)". Click it again: refused, "You already approved this … ask someone else".
4. A second person approves (another admin, or the platform operator in a second window): the offer is signed.
5. **Ledger**: "demo@… approved Offer's offer: 1 of 2 approvals", the rule line, and "Offer signed the offer … after 2 people approved it".
