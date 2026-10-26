# AGENTS.md: handoff for coding agents

Read this first. It's the current state of Project Uzima as of 12:30 PM PT, Sat Sep 26, 2026.
**Hard deadline: submission at 3:00 PM PT. Code freeze at 2:15 PM.** Anything not working by then gets cut, not fixed.

## Final integration update (14:40 PT)

Udit explicitly authorized urgent integration fixes after the freeze. `docs/INTEGRATION_PLAN.md` and the current README describe the release; older details below are historical.

- Default voice is `VOICE_PROVIDER=bedrock_gather`: Twilio speech recognition/synthesis, OpenAI GPT OSS interpretation through AWS Bedrock, scripted read-back and strict confirmation. Direct Realtime is a legacy opt-in only.
- `TWILIO_ENABLED=0` is an explicit simulation switch even when credentials exist. Set it to 1 for an authorized phone rehearsal. Use one worker for the voice service.
- The public gateway on port 8005 exposes only TwiML, signed voice callbacks and handoff links. A temporary HTTPS tunnel can serve both voice and records. Never expose the internal `/call` or `/bridge` endpoints.
- Every result carries `source` (`live` or `simulated`) and optional `error`. Accept/status responses add bridge mode/status; successful connection requests are not proof of two-way audio.
- The supplied Twilio account was checked as Full; old trial-account assumptions below do not describe the current account.
- Main now has 18 receiving centers and a white dashboard. The record passcode was removed by the team; possession of the ticket/record link grants access until expiry.
- `make preflight` checks real Bedrock inference and HTTPS without dialing. `make smoke` refuses to dial unless invoked with `--live`.

## What we're building

Project Uzima: "The beds exist. We get people to them in time."
A clinician says what the patient needs and how fast. Uzima calls every capable hospital inside that time window at the same time, one AI agent per hospital. Each agent says it's an AI, asks, reads the answer back, and only counts it once the hospital confirms. Plain rules rank the confirmed yeses. One tap ("Connect doctors") puts the referring clinician on the winning hospital's call, after the agent reads the summary to them.

**Core rule: hospitals never open anything.** No app, page, link, SMS or QR code for hospitals. Only a normal phone call. Don't add any hospital-facing UI or messages.

Overview, setup and architecture: `README.md`. The story (why, why now, what we built): `docs/STORY.md`. Background, decisions and why, Twilio and AWS details, design direction: `docs/CONTEXT.md`. Release plan: `docs/INTEGRATION_PLAN.md`.

## Team

- Udit: core and integration (orchestrator, collector, agents, infra, data). Presents.
- Sakshi: voice (Twilio gateway, Realtime bridge, Connect).
- Sukriti: dashboard, demo video, submission.

## State of the code (GitHub main = `sukritisehgal-28/marco-polo`, may be renamed `project-uzima`)

Done and tested (`make test`, 15 tests pass, all offline):

- `services/orchestrator/app/main.py`: selection inside the window, bed memory, fan-out, ranking, accept flow.
  - `live_phones()` reads `DEMO_HOSPITAL_PHONES` (comma list). The nearest N hospitals get real calls; the rest are simulated.
  - `window_for()` + `Case.window_min`: clinician's "care within N minutes" (10 to 120). Untouched = case default. Narrow windows leave few hospitals in the rural demo data (heart attack: 50 min gives 1, default gives 10). Demo uses the default.
  - Accept: marks held/released (no SMS), builds the handoff twin, then calls `POST /bridge` on the Twilio gateway with a spoken summary that includes the record passcode.
- `services/agent/`: one agent per hospital. `runner.py` uses the live call when `header.live` and Twilio keys exist, else `call_sim.py` (weighted-random answers, same four events).
- `services/collector/`: `POST /events`, `POST /results`, `POST /transfer-events`, `WS /stream`, bed memory. In-memory or DynamoDB when `USE_AWS=1`.
- `services/handoff/`: IPS FHIR bundle encrypted as a SMART Health Link (JWE A256GCM, passcode, 24 h expiry), Stedi mock insurance check. Kept as a record; nobody has to open it.
- `services/sync_twilio/app/main.py`: Twilio gateway.
  - `POST /call`: places the call; TwiML `<Connect><Stream url="wss://PUBLIC_HOST/media">` with `transfer_id` and `agent_id` parameters. Stores the call in `live_calls[(transfer_id, agent_id)]` including `call_sid`.
  - `WS /media`: **written but never tested on a real call.** Bridges Twilio Media Streams (G.711 μ-law) to the OpenAI Realtime GA API (`wss://api.openai.com/v1/realtime?model=gpt-realtime`, `session.type=realtime`, `audio/pcmu`, server VAD). Tool `report_capacity {bed, ready_in_min, reason, confirmed}`. Emits `call_started`, `call_answered`, `answer_recorded`, `call_ended` + `AgentResult` to the collector. Barge-in sends Twilio `clear` + `response.cancel`. Hangs up on a no; on a yes it stays on the line (hold) for Connect.
  - `POST /bridge`: if the winner has a live `call_sid`, updates that call with TwiML `<Say>summary</Say><Dial>clinician</Dial>`. Otherwise calls the clinician and dials `DEMO_ACCEPTING_DOCTOR_PHONE`.
  - `POST /release`: logs only (no SMS, by design).
- `apps/dashboard/`: React + Vite + Tailwind + MapLibre (CARTO dark tiles). Case buttons, "Care within" slider, Find a bed, live map pins, two clocks, recommendation, "Connect doctors", twin panel. `npx tsc -b` and `vite build` pass.
- `data/hospitals.json`: sending hospital South Sunflower County Hospital (Indianola, MS) and 15 verified receiving centers. **Never dial the `phone_reference` numbers.**

Not built, deliberately cut for today: AgentCore sandboxes (agents run as parallel asyncio tasks; the K8s Job launcher exists but no cluster), and the chaos "kill a sandbox" button. Don't start them unless everything above works by 1:30.

## Run it

```
make install     # venv + dashboard packages
make test        # 15 tests
make dev         # orchestrator 8000, sync_openai 8001, sync_twilio 8002, collector 8003, handoff 8004, dashboard 5173
make smoke       # with make dev running: start, wait, accept, print twin link
```
`GET localhost:8000/health` shows which integrations are live. Logs are in `.logs/`.

## Environment (`.env`, never commit it)

- Twilio **trial**: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`. Limits: 5 concurrent calls, only verified numbers (max 5, SMS verification), 10 min per call, 75 min total, US numbers only, and a trial message plays before our TwiML. Budget the 75 minutes: rehearse with simulated calls.
- `PUBLIC_HOST`: ngrok host for port 8002, no `https://` (`ngrok http 8002`). The Twilio gateway must run as a **single uvicorn worker** because `live_calls` is in memory.
- OpenAI text generation must use **AWS Bedrock**, per Udit: `USE_BEDROCK=1`, `BEDROCK_MODEL_ID=openai.gpt-oss-20b-1:0`, `AWS_REGION=us-west-2`, and the standard AWS credential chain (temporary keys/session token, profile or role). `USE_BEDROCK=0` keeps text templates. No OpenAI API key is needed for the text gateway. `USE_AWS` separately controls DynamoDB and Location.
- The existing Twilio voice bridge still uses direct `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL` (`gpt-realtime`), `OPENAI_REALTIME_VOICE` and `OPENAI_TRANSCRIBE_MODEL`. **This is a pending voice migration, not a Bedrock integration.** The voice teammate owns adapting speech input/output around a Bedrock model. Do not enable or claim this legacy path as satisfying the Bedrock requirement.
- `DEMO_HOSPITAL_PHONES="+1...,+1...,+1..."` (Sakshi, Sukriti, a judge), `DEMO_SENDING_DOCTOR_PHONE` (Udit, the clinician), `DEMO_ACCEPTING_DOCTOR_PHONE` (fallback only).
- `LIVE_CALL_TIMEOUT_S=240`, `LIVE_CALL_MAX_S=240`, `SIM_TIME_SCALE=1` on stage (`0` in tests), `SIM_A1_ANSWER=available` forces simulated live agents to say yes.
- AWS storage and routing (optional): Workshop Studio event account, temporary keys (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, they expire). Region **us-west-2**. Set `USE_AWS=1`, `AWS_REGION=us-west-2`, `DYNAMODB_TABLE=project-uzima`, and `AWS_LOCATION_ROUTE_CALCULATOR=project-uzima-routes` after access is verified. `make install` includes the AWS SDK and CRT. `infra/aws/dynamodb-table.json` is valid CreateTable input; configure TTL separately. The current workshop policy denies the storage and route checks, so leave `USE_AWS=0` and use built-in estimates. Bedrock uses its separate `USE_BEDROCK` flag.

## Priorities for the next 2.5 hours, in order

1. **One real live call end to end (by 1:00).** `make dev`, ngrok on 8002, keys in `.env`, one phone in `DEMO_HOSPITAL_PHONES`. Press Find a bed. The phone rings, the agent speaks, the answer is read back, and the events and result appear on the map. Debug `WS /media` against real Realtime events: check the server event names in `.logs/sync_twilio.log`. The most likely issues are session.update shape, audio format, and the agent talking over the pickup.
2. **Three live phones + Connect (by 1:45).** Three numbers in `DEMO_HOSPITAL_PHONES`; confirm 3 concurrent calls work on the trial. Press Connect doctors: the winning hospital hears the summary, then the clinician's phone rings and joins. If updating the live call fails, the fallback path must still work.
3. **Freeze at 2:15.** After that only: README screenshots, a short "How to run" check, and the demo video of a clean run.
4. Optional if 1 and 2 are solid: AWS road times (`USE_AWS=1`), dashboard polish to match the deck (dark, gold `#F0C06A` accent, Geist).

## How we coordinate (humans and LLMs, via GitHub)

Every coding agent and every person follows this loop on every change:

1. `git pull --rebase origin main` before touching anything.
2. Read `AGENTS.md` (rules, rarely changes) and `STATUS.md` (live board).
3. Claim a task: set its row in `STATUS.md` to `doing`, your name + tool, and the time. If someone else has it `doing`, pick another task or add a note, don't take it over.
4. Stay in your lane's directories (Team above). Touching another lane's files or `services/shared/schemas.py` means adding a line under "Messages" in `STATUS.md` first.
5. Make the change, run `make test`.
6. Update only your own rows in `STATUS.md` (status, one-line result, next step), and commit the code and the status change together in one small commit.
7. `git pull --rebase` then `git push`. If a rebase conflicts on `STATUS.md`, keep both sides' rows.

Edit `AGENTS.md` itself only when a rule or contract changes, and say so in "Messages".

## Rules for agents

- Keep `make test` green. Add a test for anything you change in selection, ranking, accept or the bridge's pure functions.
- Don't change the shapes in `services/shared/schemas.py` or the endpoint contracts without telling the team.
- No hospital-facing UI, SMS or links. Live calls only to verified teammate or judge phones.
- The agent must disclose it's an AI in its first line and read every answer back before reporting it.
- Commits are authored by the human running you. Don't add AI co-author or "generated by" lines to commits or PRs.
- Don't commit `.env`, keys or tokens.
