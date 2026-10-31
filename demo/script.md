# 2-minute demo video script (v4: Sourced, run by Agaxes)

**Story:** companies are hiring AI employees. **Agaxes** (agent access) gives each one a **passport**, which is an
**ID badge and a permission slip** in one. It says who the agent works for, which real person vouches for it, and
what it's allowed to do. Agaxes checks that person live on Crustdata, every time it matters. **Sourced**, the hiring
agent, is AI employee #1.

**The four highlights, in order:**
1. A messy brief ("junior quant trader, prestige college in india") is understood correctly (PRs #38, #41, #42).
2. The **hiring flow** chains four agents. The passport is checked at every handoff, two agents are refused, and the offer is signed only after a human approves (#39).
3. The signed offer lands in a real inbox. **Verify** shows **Genuine**. Suspend the agent, and the same link turns red.
4. The **ledger** tells the whole story in plain sentences, and the chain is intact.

Recorded **live** (`CRUSTDATA_MODE=cache`, `LLM_MODE=live`). Target **1:55**. Two browser tabs: `localhost:3000` (Agaxes) and Gmail.
Labels were checked against `frontend/src/app/` on main at 69f4984.

## Before recording (about 15 min, on the Mac)
```bash
git pull
# backend/.env: SMTP_HOST/SMTP_USER/SMTP_PASSWORD (or RESEND_API_KEY), OUTBOUND_TEST_TO=<your Gmail>, AGAXES_PUBLIC_URL=http://localhost:3000
backend/scripts/demo_up.sh
```
- [ ] Mail works: `cd backend && python scripts/send_signed_email.py`. A signed note arrives in your Gmail, and its **Verify** link opens a green **Genuine** page.
- [ ] Log in: `localhost:3000/login` > **Try the demo as** > **Agaxes operator (full view)**. Only this login sees every agent.
- [ ] Warm-up (fills the Crustdata cache, so the take is fast):
  - Sidebar **Agent apps > Sourced**, run the quant brief once.
  - **Live work > Hiring flow > Start hiring flow** with the same brief, all the way to **Approve and sign**. Check that the offer email arrived.
  - Then reload both pages so the take starts clean.
- [ ] **Ledger** says **Chain intact**. Turn on Focus mode, close other tabs, and set zoom to 110-125%. In Gmail, archive the warm-up mails so the new one is on top.

**Brief** (messy on purpose):
```
need a junior quant trader, prestige college in india
```

## Run of show

| # | Time | On screen | Say (roughly) |
|---|---|---|---|
| 1 | 0:00-0:12 | Agaxes **Dashboard**: six agents, each with its sponsor and status | "Companies are hiring AI employees. Agaxes gives each one a passport: an ID badge and a permission slip. It says who the agent works for, which real person vouches for it, and what it may do, checked live on Crustdata." |
| 2 | 0:12-0:35 | Sidebar **Agent apps > Sourced**. Paste the brief, run. Point at **Understood as**: quant trader, junior, the schools it expanded "prestige college in India" into, India. Then the shortlist: open one candidate and show the **Education** claim and the experience claim, each with its source | "This is Sourced, our hiring agent. A one-line, messy brief: it reads 'prestige college in India' as IITs, ISI and BITS, searches Crustdata for them, and ranks real quant traders. Every claim is checked and cited. It doesn't even count campus clubs as experience." |
| 3 | 0:35-1:05 | **Live work > Hiring flow > Start hiring flow** with the same brief. Walk down the stages as they land: Shortlist (Sourced) → Verify records (a different agent; **Sourced refused**) → Schedule interviews (Scheduler, invites wait for approval) → Offer (**Scheduler refused**: no `contract.sign`; the Offer agent drafts it). Click **Approve and sign** | "Now the whole hire. Four agents, and at every handoff Agaxes checks the passport for that job. Sourced isn't allowed to check its own shortlist, so it's refused. The Scheduler can book interviews but can't sign contracts, so it's refused for the offer. The Offer agent drafts it, and nothing is signed until I approve." |
| 4 | 1:05-1:30 | Gmail: the signed offer email, ending "Sent by Offer, AI agent for …, vouched for by …. Verify: …". Click **Verify**: green **Genuine**, with the checks listed. Back to Agaxes: **Agents > Offer > Suspend and revoke passport**. Reload the verify tab: **red** | "Here's what the candidate gets, signed. Anyone can click Verify, with no login: it's genuine, from a real agent, vouched for by a real person, and the text hasn't been changed. Now I suspend that agent… and the same link turns red. Its word is only good while its passport is." |
| 5 | 1:30-1:48 | **Ledger**: the flow told as plain sentences (who did what, to whom, the outcome), with the two refusals and the signed offer. **Chain intact**. Open one entry's **Details** to show the Crustdata sources | "And every step is on the ledger as a readable story: each passport check, both refusals, my approval, the signature. It's hash-chained, so editing one line breaks it, and every fact links back to its Crustdata source." |
| 6 | 1:48-1:58 | Back to the **Dashboard** | "A messy brief in, a signed, verifiable offer out. Every AI employee is backed by a real person, kept to its permissions, and on the record. That's Agaxes." |

## Cut order if over 2:00
1. Beat 2: show only **Understood as** and one claim, then fast-forward the search 2x (say "sped up").
2. Beat 3: fast-forward between stages, but stop on each refusal and on **Approve and sign**.
3. Never cut: the two refusals, Genuine turning red, or Chain intact.

## Backups (if a highlight fails during recording)
- **No email arrives:** run `python scripts/send_signed_email.py --agent Offer` and use that mail for beat 4. Or open the offer's verify link from the flow in the console.
- **Hiring flow stalls or a stage errors:** Crustdata is rate limited (Person Enrich is 15/min), so wait a minute and **Start hiring flow** again. The warm cache makes it fast.
- **Quant brief parses oddly (Gemini down):** the rule pass still reads role, seniority and schools. Or switch to the backend brief: `need a senior backend eng asap, payments exp, blr or remote india, ex startup pref`.
- **Need extra footage:** **Guided demo > Run demo** plays the six-agent story (sponsor left, permission refusal, false claim blocked, tampering). The false-claim test is also under **Agents > Sourced > Messages > Try a message > False claim > Sign and check**.

## After recording
- **Reinstate the Offer agent** (Agents > Offer) before the live finals, or its offers stay red.
- Trim with `Cmd+T` in QuickTime, export at 1080p, watch it once end to end, and upload by 15:15.
