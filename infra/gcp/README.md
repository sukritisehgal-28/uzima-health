# Uzima backend on Google Cloud

The dashboard runs on Vercel at `https://uzima-health.vercel.app/`. The Python backend runs on Cloud Run in `us-central1`, in a dedicated project, set up to cost close to nothing.

## Runtime

`runtime.py` supervises the existing five internal services and the public gateway in one container. Internal ports bind to loopback; only the public gateway listens on Cloud Run's assigned port. Startup waits for every internal health check. A failed child ends the container so Cloud Run can restart it.

Transfer, call and ticket state lives in memory, so the service runs at most one instance. It scales to zero when idle: the first visit after a quiet period starts it in a few seconds, and a restart clears earlier transfers and tickets. This is a demo configuration, not durable clinical storage.

## Cost settings

- Minimum 0 and maximum 1 instance, 1 vCPU, 1 GiB, startup CPU boost.
- CPU billed only while requests are handled (`--cpu-throttling`). Simulated hospital answers still arrive on time because the dashboard polls every second.
- Simulated by default: `TWILIO_ENABLED=0`, `USE_BEDROCK=0`, `USE_AWS=0`, so no provider is called.
- Artifact Registry keeps the two newest images; older ones expire after seven days.
- A monthly budget alert on the project emails at 50% and 100% of $5.

## Build and deploy

Build from a directory containing only tracked `services/`, `data/`, `requirements.txt` and `infra/gcp/`. Never upload `.env`, `.logs`, credential files or the local virtual environment.

```sh
gcloud builds submit <source-dir> --region us-central1 --config infra/gcp/cloudbuild.yaml \
  --substitutions _IMAGE=us-central1-docker.pkg.dev/<project>/uzima/backend:<tag>
gcloud run deploy uzima-backend --region us-central1 --image <image> \
  --service-account uzima-runtime@<project>.iam.gserviceaccount.com --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --cpu 1 --memory 1Gi --cpu-throttling --cpu-boost \
  --concurrency 80 --timeout 3600 \
  --set-env-vars TWILIO_ENABLED=0,USE_BEDROCK=0,USE_AWS=0,SIM_TIME_SCALE=1,VISITOR_CALLS=1,DOCTOR_CALLS=simulated,PUBLIC_HOST=<run-host>,HANDOFF_PUBLIC_URL=https://<run-host>,SHL_VIEWER_URL=https://<run-host>/view
```

The runtime service account has no roles. Public invocation is enabled because the gateway exposes only the dashboard API, signed phone callbacks and bearer ticket links.

## Optional live call

With `VISITOR_CALLS=1`, a visitor can enter their own US number so the first hospital call rings their phone; all other hospitals stay simulated, and `DOCTOR_CALLS=simulated` shows the two doctor calls on the dashboard instead of dialing. It switches on only when Twilio credentials are present. Store them in Secret Manager (mapped to `UZIMA_RUNTIME_JSON`), grant the runtime account access to that secret, and set `TWILIO_ENABLED=1`. A Twilio trial reaches only verified numbers. `VISITOR_CALLS_PER_DAY` and `VISITOR_CALLS_PER_NUMBER` cap the phone bill.

## Checks

- `make test` and the Node relay tests.
- Cloud Run `/dashboard/health` and `/dashboard/centers`.
- Simulated search → results → Connect → simulated doctor call → ticket.
- Public ticket and encrypted record manifest are reachable.
- The same routes work through the Vercel URL.
