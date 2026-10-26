# Uzima final integration and release plan

Updated September 26, 2026. Team submission deadline: 3:00 PM PT; target submission: 2:45 PM PT.

## Release objective

Show one complete emergency-transfer workflow using fictional patient data: select capable hospitals, call in parallel, confirm availability and ready time, rank the answers, connect doctors, and open the encrypted transfer record from a phone. One reliable real hospital roleplay call is the minimum live demonstration. Additional hospitals can be visibly simulated.

## Integrated flow

1. The clinician chooses a case and care window in the dashboard.
2. The orchestrator selects capable hospitals and starts one local asynchronous agent for each.
3. Configured teammate numbers receive real Twilio calls when live calling is enabled. Other agents produce explicitly simulated results.
4. Twilio recognizes speech and reads scripted prompts. OpenAI GPT OSS on AWS Bedrock interprets availability and ready time. Clear literal replies remain usable during a model outage.
5. The agent reads the complete answer back. Only an unqualified confirmation records availability or decline. Corrections restart collection. Silence or unresolved ambiguity becomes no answer.
6. The collector receives the transcript, source and result, then updates the dashboard. Ranking uses estimated travel time, ready time and the fixed demo handoff allowance.
7. Connect creates the handoff record and calls the separate accepting doctor. After that doctor hears the summary, a signed callback dials Udit into a conference; the hospital desk joins too if its original call remains open. A failed phone request is shown as an error; the UI never asserts that both participants can hear one another.
8. The transfer ticket opens over HTTPS. Its QR opens the encrypted record, with the decryption key held in the link fragment. No passcode is required. The record expires after 24 hours.

## Work already integrated

| Area | Change | Evidence |
| --- | --- | --- |
| Sakshi voice branch | Conflict resolution and pickup/startup-error handling preserved | Existing regression tests |
| AWS-compatible speech | Twilio speech + Bedrock interpretation replaces the blocked direct Realtime dependency by default | Signed callback tests and actual Bedrock interpretation checks |
| Result honesty | Live failures remain failures; every result states live or simulated | Failure regression and dashboard labels |
| Confirmation | Availability, ready time, read-back, strict confirmation, corrections, retries | Full voice state-machine tests |
| Connect | HTTP errors surfaced; successful duplicate requests return the same result; fallback summary reaches receiving doctor first | Failure/retry/concurrency and bridge tests |
| Timeouts | Search waits long enough for live results | Timeout regression |
| Smoke rehearsal | Removed obsolete passcode lookup; live calls require an explicit flag | Running-service smoke check |
| Public access | Restricted HTTPS gateway serves voice callbacks and phone record links | External HTTPS checks; private dial endpoint returns 404 |
| Submission accuracy | README describes actual local/AWS components and current limits | Updated documentation |

## Final gates and owners

### Gate 1 — software verification: Udit

- Run `make test` and dashboard production build.
- Start the services and public tunnel; run `make preflight`.
- Run a simulation with `TWILIO_ENABLED=0`, `SIM_A1_ANSWER=available`.
- Confirm all results arrive, Connect creates a ticket, and the ticket and encrypted record load through the public URL.
- Keep `USE_AWS=0`; workshop permissions currently deny DynamoDB and AWS Location. Keep Bedrock enabled independently.

### Gate 2 — one real phone conversation: Sakshi + Udit

- Confirm the intended teammate and Udit are ready to answer. Use only the configured demo numbers.
- Enable `TWILIO_ENABLED=1`, leave `VOICE_PROVIDER=bedrock_gather`, restart services and refresh the dashboard.
- Start one transfer. The hospital roleplayer answers: “Yes”, then “ten minutes”, then “yes” after the read-back.
- Pass only if the introduction is audible, the required capability is asked, the ready time is collected, and the result appears after confirmation.
- Test a correction: change ten to twenty minutes, then explicitly confirm the new read-back. The old time must never be accepted.
- Test a decline separately if time allows. No second or third live number until the first call succeeds.

### Gate 3 — Connect and ticket: Sakshi + Udit + Sukriti

- Keep the confirmed hospital call open. Select that confirmed live result for the live demonstration.
- Press Connect once. The separate accepting doctor's phone rings and that doctor hears the referral summary. Only then does Udit's phone ring. Both doctors speak and hear each other; the hospital desk joins if its call is still open.
- Verify the phone actually joined; “connection requested” in the app alone is insufficient evidence.
- Open the new ticket on a second phone and scan its QR. Confirm the correct fictional patient, selected hospital, transcript and ready time.
- If the original desk call ends, the separate accepting-doctor handoff still works. The legacy two-party fallback is used only when a separate accepting-doctor number is not configured.

### Gate 4 — packaging and submission: Sukriti, pitch by Udit

- Record a clean roughly two-minute run with audible AI speech, confirmed dashboard result, Connect and ticket.
- Keep a backup recording open locally before presenting.
- Include the repository link, setup steps, screenshot, short problem/solution statement, actual architecture and known limits.
- Clearly identify which calls are real, which results are simulated, and which AWS service is actually exercised.
- Udit explains why simultaneous confirmed capacity checks reduce coordination delay; describe time savings as a demo comparison, not measured clinical outcomes.
- Submit using the organizer's actual portal/checklist and retain submission confirmation. The public event page is not a detailed submission rubric.

## Time budget

Work on remaining gates immediately and in parallel as humans: Sakshi on phone verification, Udit on integration/pitch, Sukriti on recording/submission. Stop adding features. Aim to finish the live rehearsal by 2:40 PM, submit by 2:45 PM, and use the remaining 15 minutes only for submission or demo blockers.

If a phone gate fails, retain a clearly labeled simulation and record the working parts. Do not describe the live call as verified. A second phone, Wallet pass, cloud cluster, custom domain, live insurance and real routing are out of scope until the first complete flow and submission are done.

## Operational checklist

- One running `make dev` process and one running tunnel. Do not restart during recording; memory-backed tickets and transfers reset.
- All model inference uses AWS Bedrock by default. Direct OpenAI Realtime is a legacy opt-in path and does not satisfy the AWS requirement.
- `PUBLIC_HOST` is the bare tunnel hostname. `HANDOFF_PUBLIC_URL` is its HTTPS URL; `SHL_VIEWER_URL` ends in `/view`. Recreating the tunnel requires updating these and restarting.
- `LIVE_CALL_MAX_S=240`, `LIVE_CALL_TIMEOUT_S=300`; the orchestrator permits a further completion margin.
- No secrets in Git, screenshots, README or the submission. Keep `.env` local.
- The local health endpoint reports configured integration modes. `make preflight` performs actual Bedrock and public HTTPS checks. Real audio always needs people to verify it.

## After the hackathon

Persist calls/tickets/results, add end-to-end call status callbacks and reconciliation, run security and clinical reviews, validate hospital data and routing, and harden deployment/recovery. These are follow-up engineering tasks, not claims about the current prototype.

## References

- Twilio speech collection: https://www.twilio.com/docs/voice/twiml/gather
- Twilio signed webhook validation: https://www.twilio.com/docs/usage/security
- Temporary HTTPS tunnels: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

## Verification recorded at 2:50 PM PT

- 76 automated tests pass; dashboard production build passes.
- Live Bedrock interpretation correctly extracted yes, ten minutes and no from three spoken-answer examples in under a second each.
- Authorized hospital call produced a confirmed live availability result with ready time 10 minutes, visible on the dashboard.
- First bridge connected the sending doctor to the hospital desk, confirmed by Udit. Udit clarified that the accepting doctor must be called separately; this is now implemented and a corrected live handoff is being checked.
- Public HTTPS ticket and manifest both returned 200, and the encrypted record decrypted successfully. Restarting the services invalidates prior in-memory tickets; create a new ticket for the final recording.

## Final handoff correction

The original hospital desk and the accepting doctor are separate roles and separate numbers. Connect now explicitly dials the accepting doctor before the sending doctor. The hospital desk can leave the conference without ending the doctors' conversation. Udit reported the isolated corrected summary/handoff ran; a fresh full-sequence rehearsal was then started at 2:54 PM, including the hospital confirmation from the beginning.

Submission priority now: finish that rehearsal, save a recording, provide judge access to the currently private repository, and submit before 3:00 PM. No additional feature work is required for the demo scope.

## Final full-sequence evidence — 2:56 PM PT

Fresh transfer `ac1ac837cb` ran from the beginning. The hospital confirmed availability and a 10-minute ready time. Connect then dialed the separate accepting doctor, played the summary, and dialed the sending doctor. Twilio reported the hospital desk, accepting doctor and sending doctor all in progress, with three unmuted participants in the same conference. The dashboard and a new HTTPS transfer ticket represent that fresh run. Provider state confirms all three joined; human listening remains the authority on audio quality.

**Software release gates passed:** 76 automated tests, production dashboard build, actual Bedrock inference, live confirmation/collector/dashboard flow, separate accepting-doctor handoff, public ticket/record checks. **Remaining human release tasks:** save the demo video, give judges repository access (it is private), complete and confirm the submission. Keep the running services and tunnel open during the demo.
