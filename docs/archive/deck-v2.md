# Project Uzima — pitch deck (v2)

18 slides for a 3-minute pitch. Text and speaker notes as published; every number is sourced in `docs/numbers.md` and `docs/PRD.md`. Fill in the bracketed placeholders on the day.

## 1. Cover
- Healthcare AI Hackathon · AWS Builder Loft · Sept 26, 2026
- Ten phone calls. One patient. No time.
- Project Uzima is an AI agent swarm that finds an accepting ICU for heart attack, stroke and trauma patients by calling every capable hospital inside the survival window at once.
- [Team names] · [Contact]

> Speaker notes: Open on the three short lines, then go straight to Indianola. No stories from the pandemic: everything in this deck is 2025-26 data, checked at the source.

## 2. Indianola, Mississippi · Sunflower County
- Indianola, Mississippi · Sunflower County
- How far the right ICU is, from one rural hospital
- HEART ATTACK
- 22 mi
- Greenville: the only heart-attack receiving hospital in the region. The only heart-attack center reachable by road in time.
- STROKE
- 83 mi
- Jackson, by air. No thrombectomy center is reachable by ground inside the window.
- SEVERE TRAUMA
- 83 mi
- UMMC in Jackson, the only Level I trauma center in Mississippi. Air only.
- 28.9% of the county lives in poverty (17.8% statewide). The nearest large hospital, Greenwood, shut its ICU before laying off 86 staff in April 2026.
- Sources: Census ACS 2024; USAFacts; Mississippi Free Press, Apr 2026; UMMC; Delta Health; straight-line miles from Indianola

> Speaker notes: This is the setting for the whole demo. One small county hospital, three kinds of emergencies, three very different distances. The hospital that used to be the backstop no longer has an ICU.

## 3. Rural America, 2026
- Rural America, 2026
- Rural hospitals are closing, and the nearest ICU keeps getting farther
- 42%
- of rural residents can't reach a Level I or II trauma center within an hour by ground
- 417
- rural hospitals vulnerable to closure; 41.2% run at a loss
- 206
- rural hospitals closed or dropped inpatient care since 2010, 12 of them in Mississippi
- #2
- Mississippi's stroke death rate in the US: 1,925 deaths in 2024
- Sources: JAMA Network Open, Feb 2026; Chartis Rural Health State of the State 2026; Mississippi State Department of Health

> Speaker notes: Four numbers, all 2026 or 2024 data. The trauma figure is the national rural picture; the stroke figure is Mississippi. Chartis also counts 24 Mississippi rural hospitals, 42%, as vulnerable.

## 4. Every critical transfer
- Every critical transfer
- Transfers miss the clock, and time is the treatment
- 26%
- of stroke transfers leave the first hospital within the 90-minute goal
- −29%
- chance of getting the clot removed when that transfer takes 91 min to 3 h
- 10–14%
- of hospitals meet the 30-minute goal to send a heart-attack patient on
- 1.3M
- hospital-to-hospital ambulance transfers into US ERs every year
- Sources: Lancet Neurology, Jan 2026 (20,000+ patients); JACC Case Reports, 2025; American Journal of Emergency Medicine, 2026

> Speaker notes: Stroke: only a quarter of transfers leave in time, and a slow transfer cuts the chance of thrombectomy by 29%. Heart attack: only 10 to 14% of hospitals hit the 30-minute send-on target. We do not claim a count of deaths caused by "no bed".

## 5. The phone is the database
- The phone is the database
- Rural hospitals have no shared, live bed system. When the usual hub is full, staff call the next hospital, and the next, one at a time.
- TODAY
- 10 × N
- PROJECT UZIMA
- 1 × N
- N = one phone call, about 1–2 minutes. Ten calls in a row is 15–20 minutes. Ten at once is one call's time.

> Speaker notes: This is the whole insight. Point at the orange bar, then at the tiny blue stack. Same ten calls, one tenth of the time.

## 6. Introducing Project Uzima
- Introducing Project Uzima
- One request. Every capable ICU in the window, called at once.
- The rural doctor names what the patient needs. An agent swarm phones every hospital that can treat it and can be reached in time, asks two questions, and a physician accepts the best yes.

> Speaker notes: The one-sentence product. The target is a held bed with a transport plan in under two minutes; the demo shows the real time.

## 7. How a transfer runs
- How a transfer runs
- 01 · INTAKE
- Doctor starts it
- By call, text or click: heart attack, stroke or trauma, plus onset time and key scores.
- 02 · WINDOW
- Only who can help in time
- Hospitals with the right team, reachable by ground or air inside the survival window.
- 03 · SWARM
- All calls at once
- One sandboxed agent per hospital, all dialing in the same second.
- 04 · ASK
- Two questions
- Bed and team for this patient? How soon can you be ready?
- 05 · CONFIRM
- Doctors decide
- Hold the best, release the rest, text the summary, connect the two physicians.
- 06 · HANDOFF
- The record travels
- Encrypted handoff twin, transport booked, every call logged for EMTALA.

> Speaker notes: Walk left to right, top to bottom. Stress steps 2 and 5: distance is a hard rule, and a physician accepts every transfer.

## 8. The survival window
- The survival window
- Distance is a hard rule, not a ranking factor
- Case | Transport budget | Hard max | Who gets called from Indianola
- Heart attack | 75 min | 120 min | Greenville by ground (42 min); Jackson and Oxford by air; Memphis, Tupelo, Little Rock by air
- Stroke | 90 min | 240 min | Jackson by air (73 min); Memphis, Tupelo, Little Rock by air
- Severe trauma | 60 min | 90 min | UMMC Jackson by air (73 min); burn and pediatric cases go to the team that can treat them
- Ground if it fits the budget, air if it does not, and nobody beyond the hard max unless a physician overrides.
- Budgets from AHA door-in-door-out targets and the 60-minute trauma standard; times are estimates until AWS Location road routing; clinician sign-off pending

> Speaker notes: This is the difference from a list of nearest hospitals. The agent never calls a place the patient can't reach alive in time, and it recommends ground or air for each one.

## 9. The swarm, live: heart attack from Indianola
- The swarm, live: heart attack from Indianola
- A1
- Delta Health, Greenville
- Available · ready in 10 min · live call
- A2
- UMMC, Jackson
- Declined · no cardiac ICU bed
- A3
- Mississippi Baptist, Jackson
- Calling…
- A4
- Merit Health Central, Jackson
- No answer
- A5
- Baptist North Mississippi, Oxford
- Available · ready in 15 min
- A6
- Methodist University, Memphis
- Declined · on diversion
- A7
- NMMC, Tupelo
- Available · ready in 25 min
- A8
- Baptist Memorial, Memphis
- Declined · cath lab team in a case
- A9
- UAMS, Little Rock
- Call back in 5
- A10
- Baptist Health, Little Rock
- Declined · no staffed bed
- Illustration. Live: A1 is a real call to a teammate; A2–A10 run the same agent against simulated responders at real, verified ICUs.

> Speaker notes: Switch to the live dashboard here. A teammate's phone rings for A1. If they say yes, Greenville wins on time: 42 minutes by road, ready in 10. Be upfront that the other nine are simulated with the same agent code.

## 10. Two questions, then a human decision
- Two questions, then a human decision
- AGENT A1 · ON THE CALL
- "Hi, this is an AI transfer assistant calling for South Sunflower County Hospital. This call is recorded. We have a 62-year-old man having a heart attack, symptoms since 2:05 pm, ECG confirms a STEMI."
- Q1 · "Do you have a cardiac ICU bed and a cath lab team available right now?"
- Q2 · "When can you be ready to receive him?"
- Hold the best
- Ranked by earliest treatment: travel time by ground or air, ready time, handoff.
- Release the rest
- Other centers that said yes are told "no longer needed", so no bed sits idle.
- Doctor to doctor
- Case summary sent by text, then the two physicians are connected to accept.

> Speaker notes: Case 1 shown: cardiac ICU. For stroke it asks about a neuro ICU bed and a thrombectomy team; for trauma, a trauma bay and surgical team, or a burn or pediatric team when needed. Two questions keep the call under a minute. Hold and release shows we understand hospitals. The accepting physician always makes the final call.

## 11. After the yes
- After the yes
- The handoff twin arrives before the patient does
- What's inside
- The case: condition, onset, scores, ECG or imaging, blood thinners.
- The search: every hospital called, every answer, and why ground or air.
- Coverage: a real-time insurance check (X12 270/271) on the record.
- How it's built
- HL7 International Patient Summary bundle, readable by any EHR.
- SMART Health Link: encrypted, passcode given on the physician call, expires in 24 h.
- Insurance never gates care: checked only after acceptance.
- Standards: HL7 FHIR IPS v2.0.1; SMART Health Links (JWE A256GCM); EMTALA 42 CFR 489.24(d)(4); demo uses Stedi's free mock eligibility checks

> Speaker notes: It's called a twin because it mirrors the patient's transfer state, not because it simulates the patient. EMTALA forbids delaying care to ask about insurance, so the check runs only after a physician has accepted. The air-transport rationale in the record is what payers ask for later.

## 12. An agent swarm on AWS and OpenAI
- An agent swarm on AWS and OpenAI
- Orchestrator · FastAPI + OpenAI
- survival-window selection · bed memory · ranking · hold and release
- Amazon EKS sandbox template × N
- same image · header = hospital, phone, question, ground or air
- A1
- A2
- A3
- A4
- A5
- A6
- A7
- A8
- A9
- A10
- OpenAI synchronizer
- rate limiter · personas for simulated calls
- Twilio synchronizer
- Media Streams → OpenAI Realtime (A1) · SMS · Retell/Vapi backup
- Collector · four events per call
- DynamoDB · AWS Location + MapLibre · handoff twin

> Speaker notes: One agent template, cloned into isolated sandboxes; only the header changes. Every call reports the same four events (started, answered, answer recorded, ended), so the voice provider can be swapped without touching the dashboard. Going from 10 hospitals to 100 does not add time. App Runner is the fallback if EKS is not ready.

## 13. Ten calls in the time of one
- Ten calls in the time of one
- ONE AT A TIME
- 15–20 min
- 10 hospitals × one call each, plus hold music and repeating the story.
- PROJECT UZIMA SWARM
- <2 min
- Target: a held bed and a transport plan. Total time is the slowest single call, not the sum.
- One call takes about 1–2 minutes. Measured in today's live demo: [__ sec]

> Speaker notes: After the demo, update the right-hand number with the real measured time. Never overclaim.

## 14. The moat
- The moat
- Three things compound with every transfer
- Bed memory. Hospitals won't enter bed data; they do answer the phone. Every answer is saved.
- The swarm. Ten calls or a hundred take the time of one.
- The twin. A standard record that travels with every patient.
- Time | Hospital | Last answer
- 2:10 pm | Delta Health, Greenville | Available
- 2:10 pm | UMMC, Jackson | Full: no cardiac ICU bed
- 2:11 pm | Merit Health Central | No answer
- 2:25 pm | Next search | Skips UMMC, calls Greenville first
- The more transfers run, the more accurate the live bed map becomes.

> Speaker notes: This is what makes Project Uzima a company, not a feature: the bed network builds itself from calls that already happen, and the twin makes every receiving hospital a user.

## 15. Built for the gap nobody serves: the rural sender
- Built for the gap nobody serves: the rural sender
- Who | What they do | Gap for the rural sender
- Viz.ai | Stroke coordination inside one hub-and-spoke network | Stroke only, one network
- TeleTracking, ABOUT | Transfer-center software for receiving systems | Built for the receiver
- Pulsara | Secure messaging instead of phone calls | Does not find beds
- Juvare EMResource | Statewide bed-capacity dashboards | Nobody makes the calls
- Oregon, Washington, Indiana centers | Staffed state lines that place hard transfers | Nurses still work the phones: customers
- Aurelian, Hyper | AI voice agents for 911 non-emergency calls | Inbound, not hospital to hospital
- Project Uzima | Every ICU specialty, across networks and state lines, inside the survival window | Calls every capable center at once

> Speaker notes: Name the neighbours before a judge does. State coordination centers are not competitors: Oregon's and Washington's run on nurses and phones, and Indiana just put one out to bid. They are the first customers.

## 16. AI never decides who is sick
- AI never decides who is sick
- MINAS GERAIS, BRAZIL · JUNE 2026
- An AI bed system was blamed after it downgraded a 32-year-old's severity. She waited 5 days for an ICU 186 miles away and died hours after arriving.
- The state disputes the claim. The lesson stands: never let AI replace clinical judgment.
- No severity scoring. The agent only makes calls faster.
- Doctors accept every transfer. Physician to physician.
- Discloses itself. "AI assistant, call recorded" on every call.
- HIPAA ready. No patient data in the demo; BAAs in production.
- No pay per referral. Flat pricing, clinically neutral ranking.
- EMTALA log. Every call and decision recorded.
- Insurance never gates care. Checked only after acceptance.
- Sources: Gizmodo, June 15 2026; OECD AI Incidents Monitor; EMTALA 42 CFR 489.24

> Speaker notes: Get ahead of the "AI kills patients" question. The Brazil system judged severity; ours never does. Flat pricing avoids anti-kickback problems. This slide is for the Troutman Pepper judge.

## 17. Who pays, and why now
- Who pays, and why now
- BUYER
- Rural health networks and regional EMS
- Flat monthly subscription: [$__ per hospital per month]. No per-referral fees.
- USER
- The rural sending hospital
- One request replaces the phone tree; the twin makes every receiving ICU a user too.
- PROOF
- States now pay for this
- Indiana's 24/7 transfer center closed bids in June 2026; Oregon and Washington run their own.
- Why now: real-time voice AI and cloud agent sandboxes matured in 2025–26, while rural hospitals keep closing (Chartis 2026).
- Sources: Indiana Rural Health Transformation Program; OHSU (Oregon Medical Coordination Center); Disaster Med Public Health Prep (Washington); Chartis 2026

> Speaker notes: Flat pricing is not only simpler; paying per referral would raise anti-kickback questions. Fill in the price before the pitch.

## 18. Project Uzima
- Project Uzima
- Every capable ICU, called at once, inside the time the patient has.
- Why "Uzima"?
- Uzima (oo-ZEE-mah) is Swahili for life, being whole and well. That is our product: one call goes out, every hospital answers at once, and the patient gets to a bed in time.
- [Team names] · [Contact] · Thank you

> Speaker notes: Close on the product line, explain the name in one breath, and stop. Then take questions; the judge Q&A is in the PRD.
