# STATUS.md: live board

Pull before reading. Update only your own rows. Times are PT. Statuses: todo, doing, blocked, done, cut.

## Tasks

| # | Task | Lane | Owner | Status | Updated | Result / next step |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | One real live call end to end: phone rings, read-back, events on the map | Voice | Voice teammate | todo | 13:21 | Udit clarified his friend owns calling. Confirmation fix 0e94809 is available; teammate to report real-call outcome |
| 2 | Three live phones at once on the Twilio trial | Voice | Voice teammate | todo | 13:21 | Voice teammate to verify after one-phone test; coordinate with Udit for integrated run |
| 3 | Connect doctors on the live call (summary, then clinician dialed in) | Voice | Voice teammate | todo | 13:21 | Offline summary/dial and rejected-update fallback tests pass; voice teammate owns live verification |
| 4 | Full run with 3 live + 7 simulated, ranking and accept | Core | Udit | todo | 12:30 | `make dev`, default window, heart attack |
| 5 | AWS road times (USE_AWS=1, us-west-2) | Core | Udit | blocked | 13:50 | Credentials work; workshop policy explicitly denies DynamoDB DescribeTable and Location DescribeRouteCalculator. USE_AWS=0 retains local storage and estimates; administrator access required |
| 6 | Dashboard polish to match the deck | Screen | Sukriti | done | 13:35 | White version of the deck's style (Geist, gold accent, light map) for hospital screens; "Ticket created" panel; LIVE tag only when Twilio is live; call-backs counted apart from pending |
| 7 | Demo video of a clean run (about 2 min) | Screen | Sukriti | todo | 12:30 | Record by 2:15 |
| 8 | README screenshots and submission text | Screen | Sukriti | todo | 12:30 | Submit by 2:45 |
| 9 | AgentCore sandboxes | Core | - | cut | 12:30 | Only if 1 to 4 are done by 1:30 |
| 10 | Chaos "kill a sandbox" button | Core | - | cut | 12:30 | Only if 1 to 4 are done by 1:30 |
| 11 | Patient handoff: encrypted record + transfer ticket (web + Apple Wallet) | Screen | Sukriti | done | 13:35 | Ticket at /tickets/{id} (its QR opens the record), viewer at /view, EMTALA handoff content with fictional demo data. Wallet needs the APPLE_* certificate; phones need an https tunnel to 8004 and HANDOFF_PUBLIC_URL |
| 12 | OpenAI text generation through AWS Bedrock | Core / Voice integration | Udit | done | 13:53 | Live GPT OSS 20B text and three persona scenarios verified in us-west-2; enabled locally. 58 tests pass after merging teammate updates. Voice adaptation remains separate |
| 13 | High-risk childbirth case: verified birthing hospitals with a NICU | Screen | Sukriti | done | 13:57 | Dropdown option, call question, fictional demo patient, verified hospitals with sources; window 60/120 is a demo default |
| 14 | Resolve Sakshi voice PR #4 against current main | Core / Voice integration | Udit | done | 14:09 | Merged current main into voice branch; retained both test suites. All 62 tests pass; live-call verification remains pending |

| 15 | Final integration: Bedrock voice, honest failures, Connect, timing, public handoff and release plan | Core / Voice / Screen | Udit | done | 14:46 | 76 tests/build pass; full live hospital confirmation and three-party conference verified via Twilio; public ticket/record decrypt verified |

| 16 | One-second greeting and dashboard handoff completion | Core / Voice / Screen | Udit | done | 15:09 | 79 tests/build pass; initial pickup pause is one second; signed callbacks update calling/connected/ended states; user confirmed two-way audio |

| 17 | Patient information delivery status for the demo | Screen / Handoff | Udit | done | 15:12 | Dashboard shows recipient and Patient information sent after call end, clearly labeled simulated delivery; existing record accessible through ticket; 79 tests/build pass |

| 18 | Vercel dashboard deployment with protected live backend | Screen / Core | Udit | done | 15:27 | Vercel preview ready; access-code protected relay; 81 Python and 3 relay tests pass; live backend remains on laptop/tunnel |

| 19 | Remove demo access code | Screen / Core | Udit | done | 15:30 | Removed login and API code checks; updated preview ready; 81 backend and 3 relay tests/build pass |

| 20 | Fix hosted transfer API routing | Screen / Core | Udit | done | 15:49 | Explicit relay rewrite deployed; submitted-site health/centers and nested transfer/accept routes reach GCP; 3 relay tests pass |

| 21 | Move backend to Google Cloud | Core / Infrastructure | Udit | done | 15:49 | Cloud Run backend live; submitted Vercel domain connected; simulated transfer/ticket/decryption and real Bedrock inference pass; 82 Python tests pass; cloud phone audio rehearsal pending |

## Checkpoints

- 1:00 one live call works
- 1:45 three live phones + Connect
- 2:15 code freeze
- 2:45 submitted

## Messages

Newest at the bottom. One line each: time, who, message.

- 12:30 Udit: Board created. Claim a row before you start.
- 13:35 Sukriti: Pushed the patient handoff (now Sukriti's lane, see docs/PLAN.md) and the white dashboard. Other-lane touches: one line in orchestrator accept() passes `ticket` into the twin; optional handoff fields on `Case` in schemas.py (additive, existing callers unchanged). 23 offline tests pass.
- 13:35 Sukriti: The ticket's QR code is scanned by the receiving team on arrival. Hospitals still only get a phone call to answer, and the ticket is optional. This bends the "no QR for hospitals" rule, so say if you want it hidden in the demo. Dashboard, ticket and record are white on purpose (hospital screens); the deck stays dark.
- 13:35 Sukriti to Voice lane: please have the agent ask the accepting doctor's name on the winning call so the record and ticket show it; today it's a placeholder.
- 13:35 Sukriti to Udit: fixed your two dashboard notes. A1 is no longer tagged LIVE and the screen no longer says doctors were connected when Twilio is in mock mode; call-backs no longer count as pending.

- 12:53 Udit: Voice lane: adding offline regressions in tests/test_bridge.py for mandatory read-back confirmation and Connect fallback; no shared schema or endpoint changes.

- 12:59 Udit: Browser rehearsal completed in mock mode: all 10 hospitals emitted all four events; Connect created the encrypted handoff and one mock bridge with a passcode summary. Dashboard build and 31 offline tests pass. No real calls placed.
- 12:59 Udit to Screen lane: Existing mock UI labels A1 live and says doctors connected/record sent; callback_requested stays counted as pending after collector has all 10 results. Observed in transfer 9b271415fe; dashboard left unchanged.
- 13:21 Udit: Ownership corrected per Udit: his friend handles calling; Udit owns core integration, presenting and AWS. Voice rows are pending teammate verification, not blocked by Udit lacking voice credentials. AWS stays disabled until access and resources are verified.
- 13:22 Udit: AWS CLI 2.37.4 verified. STS checks for default, clinsight and clinsight-new all return NoCredentials, including a fresh interactive login shell. Installed boto3 locally; no AWS resources created or integration enabled. Need hackathon credentials saved in .env or an authenticated profile.
- 13:26 Udit: Udit requires OpenAI through AWS Bedrock. Updating the text gateway in services/sync_openai, shared config, dependency/env setup and AWS docs; no endpoint shape changes. Voice teammate must adapt the existing direct Realtime bridge separately; do not claim it runs through Bedrock.
- 13:30 Udit: Updating AGENTS.md and the README integration row to reflect Udit's Bedrock requirement. Text generation uses the AWS credential chain; direct Realtime voice remains a documented migration dependency owned by the voice teammate.
- 13:34 Udit: Text gateway now invokes OpenAI GPT OSS through Bedrock with AWS authentication, bounded concurrency and retries, JSON support and template fallback. No direct OpenAI text requests remain. 49 offline tests pass; STS still reports Unable to locate credentials, so USE_BEDROCK and USE_AWS remain disabled and no live AWS result is claimed. Setup and a live verification request are in infra/aws/README.md.
- 13:40 Udit: Udit saved the temporary event credentials locally; STS now verifies the Workshop participant role in us-west-2. Checking actual Bedrock inference and the agreed DynamoDB/Location resources. Credentials remain private and gitignored.
- 13:50 Udit: Bedrock returned "Uzima ready" from the running HTTP service. Live tests exposed malformed native JSON-format output and invented transcript details; changed requests to validated plain JSON and rephrasing existing demo lines, preserving the AI disclosure/questions. Available, declined and callback examples now pass; 57 offline tests pass. USE_BEDROCK=1 locally. Workshop policy denies the storage/route checks, so USE_AWS remains 0 and no resources were created.
- 13:50 Udit: Integrated 10-hospital simulation d4dfee52fb returned all 10 results with eight transcripts (two no-answers). This randomized run had no acceptance, so no new handoff was exercised. Twilio remained mock and no phones were dialed. Task 4 still needs the voice teammate's three real calls.
- 13:52 Udit: Rebasing onto the latest main. Resolving the overlap between Sakshi's URL-based TwiML fix and our earlier rejected-update fallback; preserving both behaviors and both test sets.
- 13:53 Udit: Preserved the main-branch TwiML URL change and both regression suites (confirmation/fallback fix now 3d12f29). Updating AWS setup instructions in AGENTS.md/infra README because main removed the invalid DynamoDB metadata; retaining the team's boto3 CRT dependency.
- 13:53 Udit: All 58 tests pass with the merged code and installed AWS CRT dependency. Final local configuration: Bedrock text live, Twilio mock, DynamoDB in memory and Location estimated.
- 13:57 Sukriti: Added the high-risk childbirth case. Other-lane touches: `Specialty.childbirth` in schemas.py (additive), its capability question in orchestrator QUESTION, decline reasons in agent/responder.py, one SPECIALTY_NEED line in sync_twilio, and a `childbirth` capability plus 3 new birthing hospitals (Baptist Women's Memphis, Merit Woman's Flowood, Bolivar Medical Cleveland) in data/hospitals.json, each with a source.
- 13:57 Sukriti: Dashboard now uses a case dropdown, floating case and clock cards on the map (like the mockups, in white), bigger green pins, and no pulsing on the other pins.
- 13:58 Sukriti: Removed the record passcode (team decision): the ticket's QR code opens the encrypted record, which still expires after 24 h. The spoken summary no longer reads a passcode; it says the transfer ticket travels with the patient (one line in orchestrator accept). tests/test_e2e.py updated to match.

- 14:08 Udit: Udit requested resolving Sakshi PR #4. Merging current main into the voice branch; the only conflict is tests/test_bridge.py. Keeping both test suites, Bedrock setup, childbirth case and the updated handoff contract. No live calls are part of this verification.
- 14:09 Udit: PR #4 conflict resolved by combining the test imports and retaining all greeting/startup-apology, explicit-confirmation and Connect fallback tests. The production merge preserves the current Bedrock, childbirth and passcode-free handoff changes. All 62 offline tests pass; no real calls placed.
- 14:38 Sukriti: Renamed the GitHub repo to sukritisehgal-28/project-uzima (old URLs redirect). Update your remote: git remote set-url origin git@github.com:sukritisehgal-28/project-uzima.git. Added docs/SUBMISSION.md (Udit's submission text with the passcode removed, the transfer ticket, Bedrock and the three live phones).

- 14:28 Udit: User explicitly requested integration fixes after freeze. Touching runner/orchestrator, Twilio bridge, dashboard, tests and demo docs; additive bridge response fields only. Integrating PR #4 locally. Bedrock remains the OpenAI provider; investigating a Twilio speech path that does not require direct Realtime access. No live calls placed.

- 14:40 Udit: Added default Twilio speech + Bedrock interpretation path, preserving Sakshi's legacy Realtime path. Added AgentResult source/error and additive bridge mode/status fields; dashboard labels simulated recommendations and requested connections accurately. Updated AGENTS.md contracts and README. 75 tests and the dashboard build pass; live Bedrock speech interpretation and public HTTPS checks pass. User explicitly authorized one hospital call and a Connect rehearsal; in progress.

- 14:46 Udit: Authorized live rehearsal 10b01b57f2: hospital answered, read-back confirmed available in 10 minutes, source=live result collected. Connect updated the winning call and Twilio reports completed hospital/clinician legs (112/40 seconds). Both-way audio still requires the user's feedback. Public ticket and manifest returned 200; record decrypted to 16 entries. Adding dashboard recovery by transfer URL and polling to recover missed events. Syncing only current implementation/test facts in the new submission draft after pulling teammate changes.

- 14:49 Udit: User confirmed the hospital-to-sending-doctor connection worked but requires a separate accepting-doctor call. Added signed doctor-ready callback: dial accepting doctor, play summary, then dial sending doctor into a conference and include the original hospital desk if still present. New regression verifies all three destinations, ordering and duplicate callback handling. Corrected handoff live rehearsal pending.

- 14:52 Udit: Corrected doctor handoff test dialed the separate accepting doctor first, then the sending doctor after the summary callback; Twilio reports both calls completed (36/13 seconds). Waiting for user confirmation of summary and two-way audio. Sakshi PR #4 merged after preserving the latest submission draft. Updated current architecture/test facts in docs/SUBMISSION.md; repository is still private, so judges need access or an owner-approved visibility change.

- 14:56 Udit: Full fresh rehearsal ac1ac837cb completed the hospital availability/ready-time/read-back sequence (confirmed yes, 10 minutes), then called the separate accepting doctor, read the summary, and dialed the sending doctor. Twilio reports all three roles in-progress in one conference, three participants and all unmuted. Dashboard restored the same transfer. 76 tests and build pass. Final code is going to main; remaining human tasks are recording, judge access to the private repo and submission.

- 15:01 Udit: User requests one-second initial greeting delay and dashboard update after doctors finish. Touching Twilio callbacks, collector shared event type, orchestrator bridge status, dashboard and tests. Both-way phone audio confirmed by Udit.

- 15:09 Udit: Added signed conference/call callbacks and internal handoff status polling (no shared event schema change). Dashboard marks connected only when both doctors join and reports call end/failure. Initial hospital TwiML pauses one second on both voice providers, with no repeated pause on later turns. 79 offline tests and build pass. User confirmed two-way audio; Twilio reports no active calls. Restarted updated services, retained the completed demo and ticket, and verified the dashboard shows Doctor call ended. No new live calls placed.

- 15:11 Udit: User requests Patient information sent and explicitly permits mocking delivery. Touching dashboard UI only, using completed bridge status and the existing accepted record. Hospital-system delivery will remain clearly labeled simulated; no email, SMS or external patient-data transmission.

- 15:12 Udit: Verified completed demo shows Patient information sent, Demo · simulated delivery, actual receiving hospital, and record contents; refresh preserves it. Pending/failed connections keep the record ready instead. Fixed restored timer values drifting negative during dashboard updates. UI-only delivery mock; no external transmission added.

- 15:22 Udit: User requested Vercel after AWS hosting permissions were denied. Touching dashboard, public gateway and deployment tests/docs. Public dashboard API requires a separate demo access code; no provider credentials enter the frontend. Vercel login pending.

- 15:27 Udit: Vercel preview ready at https://project-uzima-my1s60pe9-uditanshu-tomars-projects.vercel.app . Hosted dashboard requires the private demo access code and uses status polling; backend relay tests reject unauthenticated/private routes. Provider credentials remain local. Public gateway health and preserved completed transfer verified through the tunnel. No calls placed. CLI initially defaulted the first deployment to production; replaced it with an explicit preview. Deployment instructions in docs/VERCEL.md.

- 15:29 Udit: User explicitly requests removing the access code altogether. Removing dashboard login, relay authentication requirement and local gateway code check; retaining the existing route allowlist and signed Twilio callbacks.

- 15:30 Udit: Removed the demo access code from UI, both relays and private local settings at the user’s explicit request. Unauthenticated tunnel health/current-demo requests return 200; callback signatures and private route restrictions remain. New preview: https://project-uzima-ixm7ocyn7-uditanshu-tomars-projects.vercel.app . No phone calls placed.

- 15:36 Udit: User asks whether backend is connected and offers GCP hosting with hello@oriva.health. Live production check found nested API routing failure before the relay; local transfer exists. Fixing Vercel routing and tests. GCP credentials require reauthentication.

- 15:39 Udit: Creating separate uzima-hackathon-20260926 project for the user-authorized GCP backend migration. Container packages only services, data and dependencies; provider credentials go through Secret Manager. Existing Oriva/Veronica projects remain unchanged.

- 15:49 Udit: Deployed the backend in isolated GCP project uzima-hackathon-20260926 with Secret Manager credentials and one Cloud Run instance. Submitted https://project-uzima.vercel.app now relays to GCP; laptop/tunnel no longer required. Cloud simulation produced 10 results and a ticket whose record decrypted to 16 entries; actual Bedrock inference from GCP passed. Enabled live Twilio after simulation; no real calls placed during migration. 82 Python tests, 3 relay tests and production build pass. State remains in memory and AWS temporary credentials require renewal.
