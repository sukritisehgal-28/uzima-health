# AWS for the hackathon

Udit owns this setup. Use the event account in **us-west-2**.

## OpenAI text generation through Bedrock

`services/sync_openai` calls Bedrock Runtime `InvokeModel` using Boto3 and the
standard AWS credential chain. It does not call the direct OpenAI text API.
The default is `openai.gpt-oss-20b-1:0`; `openai.gpt-oss-120b-1:0` is also compatible.

1. Make the event credentials available through an AWS profile or the private
   `.env` fields `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
   `AWS_SESSION_TOKEN`. Temporary event credentials expire.
2. Confirm the account with `aws sts get-caller-identity` in the same environment.
3. Set `AWS_REGION=us-west-2`, `USE_BEDROCK=1` and
   `BEDROCK_MODEL_ID=openai.gpt-oss-20b-1:0` in `.env`, then restart `make dev`.
4. Run a short text request to verify actual model access:

   ```sh
   curl --fail-with-body http://localhost:8001/complete \
     -H 'Content-Type: application/json' \
     -d '{"messages":[{"role":"user","content":"Reply with exactly: Uzima ready"}]}'
   ```

The role needs `bedrock:InvokeModel` for the selected model. Model availability
and event-account permissions still require a live check. Health endpoints show
configuration, not proof of successful inference. `/personas` falls back to
templates on an AWS failure; `/complete` surfaces the failure. Offline tests
stub Bedrock and do not establish live access.

The gateway limits concurrent requests and runs the synchronous SDK off the
async event loop. The SDK retries transient failures. Bedrock's GPT OSS reasoning
prefix is removed before returning text or parsing persona JSON.
The live GPT OSS check returned malformed JSON with the native `response_format`
setting, so JSON requests use an explicit instruction followed by local JSON
validation. Persona responses also validate speakers and text; malformed or
truncated responses fall back to templates.
Persona generation rephrases an existing demo transcript and validates its
speaker sequence. The AI disclosure and questions are preserved verbatim.

### Verified on September 26, 2026

- Temporary Workshop credentials authenticate successfully in `us-west-2`.
- `openai.gpt-oss-20b-1:0` returned live text and valid conversations for
  available, declined and callback scenarios. Bedrock is enabled locally.
- The Workshop policy `ws-default-policy` explicitly denied
  `dynamodb:DescribeTable` and `geo:DescribeRouteCalculator` for the agreed
  resources. `USE_AWS=0` retains local storage and travel estimates; no resources
  were created. Enabling these services requires the workshop administrator to
  grant the required access.

Sources: [AWS OpenAI model requests](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-openai.html),
[GPT OSS 20B regions and capabilities](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-20b.html).

## Voice migration dependency

The Twilio `/media` bridge currently uses direct OpenAI Realtime WebSockets.
GPT OSS on Bedrock accepts and returns text, so changing its hostname cannot
make that bridge run through Bedrock. The voice teammate must provide speech
recognition and speech synthesis around Bedrock, or agree another supported AWS
voice integration with Udit. Keep AI disclosure and confirmed read-back.
Bedrock text integration alone does not complete the phone path.

## Storage and road times

`USE_AWS=1` separately enables these optional integrations:

- **DynamoDB:** table `project-uzima`, string partition key `pk`, string sort key
  `sk`, on-demand billing, TTL attribute `ttl`. The collector writes call events,
  results, transfer events and bed memory; reads currently remain in memory.
  `dynamodb-table.json` is valid CreateTable input. Configure TTL separately
  after the table exists.
- **Amazon Location:** route calculator `project-uzima-routes`, configured through
  `AWS_LOCATION_ROUTE_CALCULATOR`. Only ground travel times use road routes;
  air times stay estimated. Failed lookups use the existing estimates.

EKS and AgentCore remain outside the agreed hackathon scope. The app runs locally.
