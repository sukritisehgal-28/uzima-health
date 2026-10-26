# Uzima backend on Google Cloud

The dashboard stays at `https://project-uzima.vercel.app/`. The Python backend runs in the dedicated `uzima-hackathon-20260926` project, in Cloud Run `us-central1`, administered through `hello@oriva.health`.

## Runtime

`runtime.py` supervises the existing five internal services and the public gateway in one container. Internal ports bind to loopback; only the public gateway listens on Cloud Run's assigned port. Startup waits for every internal health check. A failed child ends the container so Cloud Run can restart it.

The demo uses one instance, always-allocated CPU, and a maximum of one instance because transfer, call and ticket state currently lives in memory. Cloud Run can still replace an instance; restarts or deployments lose that state. This is a hackathon configuration, not durable clinical storage. Keeping an instance running incurs hosting charges.

AWS Bedrock remains the AI provider. Twilio remains the phone provider. Provider credentials and configured demo numbers are in the `uzima-runtime` Secret Manager secret, with secret access granted to the dedicated runtime service account. Temporary AWS workshop credentials must be renewed when they expire. Cloud Run environment settings override values from the secret.

## Build and deploy

Build a source directory containing only tracked `services/`, `data/`, `requirements.txt` and `infra/gcp/`. Do not upload `.env`, `.logs`, credential files or the local virtual environment.

Build the container with `cloudbuild.yaml`, setting `_IMAGE` to an Artifact Registry image in this project's `uzima` repository. Use the dedicated `uzima-builder` service account. Deploy `uzima-backend` with:

- Image from Artifact Registry.
- Runtime service account `uzima-runtime@uzima-hackathon-20260926.iam.gserviceaccount.com`.
- Secret environment mapping `UZIMA_RUNTIME_JSON=uzima-runtime:1` (update the pinned version when renewing credentials).
- One vCPU, 1 GiB RAM, min/max instances 1, CPU throttling disabled, concurrency 80 and timeout 3600 seconds.
- Public invocation enabled: the gateway exposes only the dashboard API, signed phone callbacks and bearer ticket links.
- `PUBLIC_HOST` set to the Cloud Run hostname; `HANDOFF_PUBLIC_URL` set to its HTTPS origin and `SHL_VIEWER_URL` to its `/view` route.

Initially deploy with `TWILIO_ENABLED=0` to verify a complete simulated transfer without dialing. After verification, set `TWILIO_ENABLED=1` for the user-authorized live demo. No real phone rehearsal is part of the deployment check.

Set Vercel's `UZIMA_BACKEND_URL` to the Cloud Run origin and publish production with the existing dashboard build settings. The submitted Vercel domain remains unchanged.

## Checks

- `make test` and the Node relay tests.
- Cloud Run `/dashboard/health` and `/dashboard/centers`.
- Simulated search → results → accept → ticket while Twilio is disabled.
- Public ticket and encrypted record manifest are reachable.
- The same dashboard health and transfer routes work through the submitted Vercel URL.
