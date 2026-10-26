# Team plan: three equal lanes, one merge

Three people, three lanes of roughly equal weight: about 6 hours of build work each, plus a third of the pitch. Each lane owns its own directories and talks to the others only through frozen contracts, so the branches merge without conflicts. Every lane can demo its own slice by 12:00 using fixtures or stubs, and the three join at the checkpoints.

## Lanes

| | Engine: voice and agents | Backbone: orchestration and cloud | Face: experience and handoff |
| --- | --- | --- | --- |
| Owns (nobody else edits) | `services/agent/`, `services/sync_twilio/`, `services/sync_openai/` | `services/orchestrator/`, `services/collector/`, `infra/`, `data/` | `apps/dashboard/`, `services/handoff/`, `docs/deck.md` |
| Builds | Live A1 call: Twilio Media Streams to OpenAI Realtime, with Retell/Vapi as the backup · Q1/Q2 script, answer extraction, transcript · the four call events · simulated hospitals with two OpenAI personas · SMS, physician-to-physician bridge, release calls | Survival-window selection · ranking, hold and release, the accept flow · collector + DynamoDB (bed memory, EMTALA log) · AWS Location road times replacing the estimates · EKS deploy with one pod per hospital; App Runner fallback | Dashboard: MapLibre map, call cards, two clocks, recommendation, Accept · handoff twin: IPS bundle, SMART Health Link, Stedi mock insurance check · twin panel with QR and passcode |
| Build time | ~6 h (the live bridge is the riskiest single piece) | ~6 h | ~6 h |
| Done when | A teammate's phone rings, both questions are answered, the four events land; A2–An resolve realistically | One button launches the swarm on AWS, ranks with real road times, holds and releases correctly | Judges watch the map fill in, click Accept, and see the twin link and QR appear |
| Pitch share (~1 min each) | The live call: plays the hospital on the phone, answers voice and AI questions | Architecture and moat; answers "why Kubernetes" and "isn't this just concurrency" | Opening story and numbers, the twin, business and close; records the backup video |

## Contracts (frozen at 10:30; changes only by a PR all three approve)

| Contract | Producer → consumer | Where |
| --- | --- | --- |
| `AgentHeader`, `CallEvent`, `AgentResult`, `HandoffTwin`, `InsuranceCheck` | shared | `services/shared/schemas.py` |
| `POST /events`, `POST /results`, `WS /stream`, `GET /memory`, `GET /log/{hospital_id}` | Engine → Backbone → Face | `services/collector` |
| `POST /transfers {Case}` → agent headers; accept and release | Face → Backbone | `services/orchestrator` |
| `POST /call {AgentHeader}`, `POST /sms {to,text}`, `POST /bridge {a,b}` | Backbone → Engine | `services/sync_twilio` |
| `POST /twins {TwinRequest}` → `{shlink, passcode}`; `POST /manifests/{id}` | Backbone → Face (called by the orchestrator when a physician accepts) | `services/handoff` |
| `data/hospitals.json` (centers, windows, demo cases) | Backbone → all | `data/` |
| `data/fixtures/events_sample.json` (replayable events and results) | Backbone → Face | `data/fixtures/` |

## Working without each other

- Face builds the dashboard against `data/fixtures/events_sample.json` replayed into a local collector (`python3 scripts/replay_fixture.py`), and tests the twin locally with no network; no live call is needed to see the map move.
- Engine tests against a local collector (`uvicorn services.collector.app.main:app --port 8003`) and the fallback runner; the live call needs only Twilio and OpenAI keys and ngrok.
- Backbone tests selection and ranking with `scripts/run_local_swarm.py` (no network) and stubs `POST /twins` and `POST /call` until the other lanes land.

## Branches and merging

- Branches: `engine`, `backbone`, `face`. Small commits, PR into `main`, one reviewer from another lane. `main` stays runnable at all times.
- Touch only your lane's directories. A change to `services/shared/schemas.py` or any contract endpoint is a contract change: PR, all three approve, everyone rebases.
- Rebase on `main` at every checkpoint. If a conflict appears, the owner of that file resolves it.

## Checkpoints

| Time | What must be true on `main` |
| --- | --- |
| 10:30 | Contracts frozen; everyone has keys; the fixture replays on the dashboard |
| 12:00 | Engine: one real call end to end with events on the dashboard (not clean → switch to Retell/Vapi). Face: map, cards and clocks live from the fixture; twin builds locally |
| 13:00 | Backbone: DynamoDB writes, bed memory, AWS Location road times |
| 14:30 | Full swarm: A1 live + simulated agents, ranking, hold and release; Accept triggers the twin, and the SHL link and QR appear |
| 15:30 | Code freeze; only fixes. Face records the backup video and fills the measured time into the deck |
| 16:15–17:00 | Three rehearsals under 3 minutes: Face opens and closes, Engine answers the live call as the hospital, Backbone drives the dashboard and takes the architecture questions |

## Tonight (Friday)

| Lane | Tasks |
| --- | --- |
| Engine | Twilio account and one number; verify all three phones (trial accounts only call verified numbers); OpenAI key with Realtime access; a Retell or Vapi agent on an OpenAI model; ngrok; clone Twilio's Media Streams + OpenAI Realtime sample and get one test call |
| Backbone | AWS account: DynamoDB table, Location route calculator and map, EKS or App Runner; run `run_local_swarm.py` for both cases |
| Face | `npm install` in `apps/dashboard`; map tiles rendering with Indianola centered; fixture replay working; Stedi test key and one mock 271; `HANDOFF_ENCRYPTION_KEY`; review `docs/deck.md` and draft your pitch lines |
| All | Register for the AWS Builder Loft (separate from Luma); physical photo ID; plan the route to 525 Market St |
