# AI Outbound Call Center — Service Offering, Pricing & Stack

> Internal go-to-market doc. Not client-facing as-is; the "Upwork Listing" section is
> the copy you paste. Everything else is your playbook.

## 0. Positioning (read this first — it keeps you legal and profitable)

Sell **warm, consent-based outbound voice automation**, not cold robo-dialing.
Cold, un-consented outbound to consumers violates TCPA (US) and similar laws and gets
your numbers blocked fast. The money is in calling a business's **own** contacts who
already have a relationship with them:

- Appointment reminders & confirmations (dental, clinics, salons, auto shops)
- Lead follow-up / speed-to-lead callbacks (real estate, insurance, home services)
- Order / delivery confirmations
- Payment reminders & renewals
- Customer reactivation ("we miss you") on opted-in lists
- Post-service surveys & review requests
- No-show rebooking

Your pitch: **"We call your leads/customers in under 60 seconds with a natural-sounding
AI agent — for a fraction of a human call center, fully private (data never leaves our
own hardware), and it never sleeps."**

Your three differentiators vs. cloud competitors (Air.ai, Bland, Vapi):
1. **Cost** — you own the GPUs, so per-minute cost is telephony + electricity only.
2. **Privacy** — on-prem inference; sellable to healthcare, legal, finance.
3. **Done-for-you** — you build, script, and run it; client just gets results.

---

## 1. Recommended tech stack (for your 5090s + 3090s)

Real-time voice has a hard latency budget: **< 800 ms** from "caller stops talking" to
"agent starts replying," or it feels robotic. Split the pipeline across GPUs:

| Stage | Component | Recommended | Runs on |
|-------|-----------|-------------|---------|
| Telephony | SIP / carrier | **Telnyx** or **Twilio** (start Twilio, move to Telnyx/SIP for margin) | — (cloud) |
| Orchestration | Real-time voice framework | **Pipecat** or **LiveKit Agents** | CPU |
| STT | Speech-to-text | **faster-whisper** (distil-large-v3), streaming | 1× 5090 |
| LLM | Dialog brain | **Qwen2.5-7B/14B-Instruct** or **Llama-3.1-8B**, served via **vLLM** | 1× 5090 (+ 3090s to scale concurrency) |
| TTS | Voice | **Kokoro** or **XTTS-v2** (streaming) for speed; **StyleTTS2** for quality | 1× 5090 / 3090 |
| App/DB | Campaigns, CRM sync, logs | Node.js (reuse this repo's stack) + Postgres | CPU |

**GPU allocation plan (your 3×5090 + 4×3090):**
- 5090 #1 → LLM (vLLM, batched — serves many concurrent calls)
- 5090 #2 → STT (faster-whisper, low-latency streaming)
- 5090 #3 → TTS (streaming) + burst capacity
- 4× 3090 → horizontal scale: additional vLLM replicas + Whisper workers as call volume grows

**Concurrency estimate:** a single well-tuned 5090 LLM replica handles ~15–30 concurrent
voice sessions (short turns, 8–14B model). Your fleet realistically supports **50–100+
simultaneous live calls** once tuned — that's a real call-center's worth of throughput.

Why local beats cloud APIs here: cloud voice-AI platforms charge **$0.07–0.15/min**.
Your marginal cost is roughly **telephony (~$0.01/min) + electricity (~$0.002/min)**.
That spread is your entire business.

---

## 2. Pricing & unit economics

Price on **outcomes and minutes**, not hours. Three-part model:

### A. Setup / build fee (one-time)
| Tier | What they get | Price |
|------|---------------|-------|
| Starter | 1 campaign, 1 script, 1 voice, basic CRM/CSV | **$500–$1,500** |
| Pro | Multi-script, calendar/CRM integration, custom voice, reporting | **$2,500–$6,000** |
| Enterprise | Custom integrations, compliance review, dedicated numbers | **$8,000+** |

### B. Per-minute or per-call usage
- Charge clients **$0.12–$0.25 / minute** of talk time, or **$0.35–$0.90 / completed call**.
- Your cost ≈ **$0.012 / min**. Gross margin **~90%** at the per-minute price.

### C. Monthly retainer (the real recurring revenue)
| Plan | Included minutes | Price/mo |
|------|------------------|----------|
| Basic | 1,000 min | **$300–$500** |
| Growth | 5,000 min | **$1,200–$2,000** |
| Scale | 20,000 min | **$4,000–$7,000** |

### Worked example
Client campaign: 5,000 appointment-reminder calls/mo, ~2 min avg = 10,000 min.
- Revenue: 10,000 × $0.18 = **$1,800/mo** (or a $2,000 Growth+ retainer)
- Telephony: 10,000 × $0.011 = ~$110
- Electricity: ~$40
- **Net ~$1,600/mo per client.** Ten such clients = ~$16k/mo net at near-zero marginal effort.

**Upwork-specific pricing:** land the first 2–3 clients with a low-risk **pilot**:
"$299 setup + first 200 calls free, then per-minute." Get the 5-star reviews, then raise
prices. Reviews are the entire game on Upwork early on.

---

## 3. Upwork listing (paste-ready)

**Title:**
> AI Voice Agent for Outbound Calls — Appointment Reminders, Lead Follow-Up & Confirmations

**Category:** Sales & Marketing → Telemarketing / Lead Generation (also list under AI Services)

**Overview:**
> I build and run **AI voice agents that call your leads and customers for you** — natural,
> human-sounding, and available 24/7. Perfect for appointment reminders, speed-to-lead
> callbacks, order confirmations, renewals, and customer reactivation.
>
> **Why work with me:**
> - ⚡ **Speed-to-lead in under 60 seconds** — new leads get called instantly, so you stop
>   losing them to competitors.
> - 💸 **A fraction of a human call center** — no per-agent salaries, no shifts, no missed calls.
> - 🔒 **Private & secure** — inference runs on my own dedicated hardware; your customer data
>   is never sold or sent to third-party AI APIs. Suitable for healthcare, finance, and legal.
> - 🗣️ **Sounds natural** — real-time speech, custom voice, handles interruptions and objections.
> - 📊 **Full transparency** — call recordings, transcripts, outcomes, and reporting.
>
> **I handle everything:** script writing, voice setup, phone numbers, CRM/calendar
> integration, and ongoing optimization. You just watch the results come in.
>
> **Compliance-first:** I only run consent-based / warm outbound (your existing contacts,
> opted-in lists) and respect DNC and TCPA rules — protecting your brand and your numbers.
>
> **Pilot offer for first-time clients:** $299 setup + first 200 calls on me. If it doesn't
> book more appointments than it costs, you don't continue. Zero risk.
>
> Message me with (1) what you'd want the AI to call about and (2) your rough monthly call
> volume, and I'll send back a tailored plan and quote within 24 hours.

**Skills tags:** AI Chatbot, Voice Assistant, Telemarketing, Lead Generation, Appointment
Setting, Twilio, Conversational AI, Automation, CRM, Cold Calling (warm/consent-based).

**Portfolio to create before going live:** a 60–90s demo recording of the AI handling a
mock appointment-reminder call (record both sides). This single sample closes most clients.

---

## 4. First-30-days execution checklist

1. **Legal guardrails:** write your consent/DNC policy; only accept opted-in lists.
2. **Build the pipeline** (see stack above) — MVP: Twilio + Pipecat + Whisper + vLLM + Kokoro.
3. **Record the demo call** for the portfolio.
4. **Publish Upwork listing** + a Fiverr gig mirroring it.
5. **Pick ONE niche** to target first (recommend: dental/medical appointment reminders or
   real-estate speed-to-lead — both have obvious ROI and opted-in contacts).
6. **Land 2 pilot clients**, over-deliver, collect 5-star reviews.
7. **Raise prices, add retainers, hire a VA** to handle client onboarding as you scale.

---

## 5. What we build next (engineering roadmap)

- [ ] Telephony account + a test number (Twilio trial)
- [ ] `voice/` service: Pipecat pipeline wiring STT ↔ LLM ↔ TTS
- [ ] vLLM deployment script for the LLM on a 5090
- [ ] faster-whisper streaming STT worker
- [ ] TTS streaming worker (Kokoro/XTTS)
- [ ] Campaign runner: load CSV of contacts → dial → log outcome to Postgres
- [ ] Simple dashboard: campaigns, call outcomes, recordings, transcripts
- [ ] Reuse this repo's Node/Sequelize base for the app/DB layer
