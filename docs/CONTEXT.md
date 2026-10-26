# CONTEXT.md: everything decided so far, and why

Background for agents and teammates. `AGENTS.md` (rules, state, priorities) and `STATUS.md` (live board) come first. Where this file and the code disagree, the code and `AGENTS.md` win.

## The event

- Healthcare AI Hackathon, AWS Builder Loft, 525 Market St, San Francisco. Sat Sep 26, 2026, 10:00 to 17:00. Submission due 3:00 PM PT.
- Team: Udit (core, presents), Sakshi (voice), Sukriti (dashboard, submission). The original Marco Polo skeleton and data are Sukriti's work (see `docs/archive/`).
- Goal: win, and use it as a job signal. Judges should see real engineering: parallel agents, a real phone call, careful safety design, honest labels on what's simulated.

## The pitch in one breath

The beds exist. We get people to them in time. About 5 million people a year in low- and middle-income countries reach care and still die of something treatable ([Lancet Global Health Commission, 2018](https://www.eurekalert.org/news-releases/877728)). The gap isn't beds, it's coordination: one person, one phone, one call at a time. Uzima calls every capable hospital at once, confirms each answer by read-back, and connects doctor to doctor in one tap.

Name: Uzima (oo-ZEE-mah), Swahili for life, being whole and well. Always "Project Uzima".

## Pitch deck (6 slides)

Offline file: `docs/pitch/Project-Uzima-pitch.html` (open in a browser; arrow keys, F for fullscreen). Style: dark, gold accent, Geist + Instrument Serif italic, hopeful photos (Pexels/Unsplash, credited).

1. Title: "Project Uzima. The beds exist. We get people to them in time." Photo: nurse and child in a bright ward.
2. The gap: "5 million people a year reach care, and still die of something treatable."
3. What's missing: "Who can take this patient, right now?" Registries go stale. One phone, one call at a time. Records don't travel.
4. How it works: Speak, Race, Connect. Then "Live demo" (switch to the app).
5. Architecture: control plane, one agent per hospital, live hospital vs simulated hospitals, accepting hospital, one-tap Connect.
6. Close: tagline + photo of kids at a window. "Thank you."

Pitch rules the team agreed on: open with facts, not a single-patient story. Frame it as coordination, not poverty. Don't focus on one country or one case type. No "launch city" claims. Show hope, no distressing images.

## Product decisions and why

| Decision | Why |
| --- | --- |
| Hospitals only get a phone call. No app, page, SMS, link or QR. | The whole point is zero effort for hospitals. An earlier responder web page was removed for this reason. |
| Every answer is read back and must be confirmed before it counts (`report_capacity` with `confirmed`). | Stops the model from inventing or mishearing a yes. |
| Plain-code decider, no LLM in the ranking. | Explainable and testable. "Humans decide, AI coordinates." |
| The clinician confirms every transfer by pressing Connect. | Clinical responsibility stays with a human. |
| AI disclosure in the first line of every call. | Required by OpenAI policy; FCC treats AI voices as artificial under the TCPA. |
| One agent per hospital, all in parallel. | The core demo moment: many calls at once instead of one by one. |
| 3 live phones + simulated hospitals, labeled. | Twilio trial allows 5 concurrent calls; honesty about what's simulated builds trust with judges. |
| Connect by updating the winning live call (Say summary, then Dial clinician). | Keeps the hospital on the same call; no second dial to someone on hold. |
| Encrypted handoff record (IPS as a SMART Health Link) kept, but not required. | Real standard, good for questions; the handoff works by voice alone. |
| Twilio (not Telnyx). | Telnyx trial allows 2 calls and only one verified number; Twilio trial allows 5 calls and 5 verified numbers. |
| No LiveKit, no Signadot, no Kubernetes today. | Not needed for the demo; each adds setup risk. |
| AgentCore sandboxes and chaos button cut for today. | Not enough time. Agents run as parallel async tasks; say so if asked. |

## Twilio trial (current account)

- 5 concurrent calls; outbound only to verified numbers (max 5, verified by SMS code, the signup number counts as one); 10 min per call; 75 min of voice in total; calls only within the US; a trial message plays before our TwiML, and it may ask the callee to press a key.
- Don't upgrade today: paid accounts without an approved business profile drop to 2 concurrent calls.
- Sources: [Twilio trial limits](https://support.twilio.com/hc/en-us/articles/360036052753-Twilio-Free-Trial-Limitations), [Try out Voice](https://www.twilio.com/docs/usage/trials/try-out-voice), [Verified caller IDs](https://support.twilio.com/hc/en-us/articles/223180048-How-to-Add-and-Remove-a-Verified-Phone-Number-or-Caller-ID-with-Twilio).

## AWS (event account)

- Workshop Studio account, role `WSParticipantRole`, temporary keys that expire (re-copy from the event page). Region us-west-2.
- Used only for optional DynamoDB (`project-uzima`) and Amazon Location route calculator (`project-uzima-routes`). The app works without AWS.
- Keys go in `.env` or the shell, never in commits or chat.

## What the hospital hears (target call, about 60 seconds)

> Agent: Hello, this is an AI assistant from Project Uzima, calling for a referring doctor. I have an emergency referral. [one-breath case]. [capability question] How many minutes until you could be ready?
> Hospital: Yes, give us 10 minutes.
> Agent: So that's yes, ready in 10 minutes. Is that right?
> Hospital: Yes.
> Agent: Thank you. Please hold one moment while I confirm with the doctor.

On a no: ask the reason in one question, thank them, hang up. If they win: the agent reads the summary and passcode, then the clinician is dialed in.

## Dashboard design direction

Mockups: `docs/ui-mockups/` (1 intake, 2 race, 3 connect, 4 track). They're the target look; the current dashboard is Sukriti's working version, don't rebuild it this late.

- Dark map with glass tiles, Apple-minimal, one gold accent. No radar sweeps, neon or sci-fi.
- Tokens: bg `#0A0B0D`, ink `#F5F3EE`, muted `#A3A6AD`, gold `#F0C06A`, yes `#5BD18B`, no `#EE7B6B`, calling `#F2B35B`, LIVE tag `#8FB8FF`, SIM tag `#B9A6F0`. Glass: `rgba(20,22,26,.56)`, blur 22px, 1px white 9% border, radius 16px. Fonts: Geist, Geist Mono, Instrument Serif italic.
- Row states: queued, calling (amber pulse), yes · ready in N min (green), no · reason (coral, dimmed), no answer (grey outline), best (gold ring), standby (green outline).
- Must show: case pill, hospitals in the zone with LIVE/SIM tags, "calling one by one" estimate next to the Uzima clock, live transcript of a live call, recommendation with reasons, Connect doctors.

## Demo run (about 3 min)

Heart attack case, default window (10 hospitals), 3 real phones ring (Sakshi, Sukriti, a judge), answers read back, ranking, Connect, clock comparison, then slides 5 and 6.

## Judge questions to prepare

- "Isn't this just a wrapper?" The orchestration: N parallel voice agents, read-back confirmation, plain-code decider, human-confirmed handoff, phone-only for hospitals.
- "What if the AI mishears?" Answers only count after read-back and confirmation; unclear answers are asked once more, then recorded as unclear.
- "Is it isolated?" Today every agent is its own async task in one process; the Kubernetes Job launcher exists (`LAUNCH_MODE=k8s`) and AgentCore is the production plan. Be honest.
- "Privacy?" Hospitals hear only the need until they accept; the record is encrypted with a passcode and 24 h expiry; fictional patients only.
- "What's simulated?" Other hospitals' answers, labeled on screen. Everything else is real.
