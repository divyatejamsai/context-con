# context-con: Verified Hiring Agent

Built at **ContextCon 03 (IIT Bombay x Crustdata x YC)**, Hiring theme.

An autonomous recruiting agent: give it a messy three-line hiring brief and it returns a ranked shortlist of real candidates from Crustdata's people graph. Every claim about every candidate is checked and labelled **Verified / Contradicted / Unverifiable**, with its source attached. Outreach is drafted, never sent.

> **New here (human or AI agent)? Read [CONTEXT.md](CONTEXT.md) first.** It holds every decision, the architecture, the API contract, the build plan and the progress log.

## Stack
- Agent backend: Python 3.11, FastAPI, SSE streaming
- Frontend: Next.js, Tailwind, shadcn/ui
- LLM: Gemini on Vertex AI (ADC auth)
- Data: Crustdata API + Crustdata MCP

## Setup
Copy `.env.example` to `.env` and fill it in. Full run steps get added once building starts at 10:30 IST.
