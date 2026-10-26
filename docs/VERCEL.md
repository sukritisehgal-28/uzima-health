# Vercel demo hosting

The React dashboard and API relay run at `https://project-uzima.vercel.app/`. The Python backend runs on Google Cloud Run at `https://uzima-backend-704882703182.us-central1.run.app`. AWS Bedrock provides the AI model and Twilio handles phone calls. The host laptop and temporary tunnel are no longer needed for the cloud deployment. See `infra/gcp/README.md` for backend operation.

## Configuration

The dashboard opens without an access code. The gateway only forwards the required read/search/accept routes. Internal dialing, results and storage endpoints stay inaccessible.

From `apps/dashboard`, link the desired Vercel project and deploy a preview with:

```sh
vercel deploy --yes --target preview \
  --build-env VITE_ORCHESTRATOR_URL=/api \
  --build-env VITE_COLLECTOR_WS= \
  --env UZIMA_BACKEND_URL=https://uzima-backend-704882703182.us-central1.run.app
```

Only the backend origin is stored on Vercel. AWS and Twilio credentials are held in Google Secret Manager. Hosted updates use the existing one-second status poll instead of a WebSocket server.

The Cloud Run hostname is also used for Twilio callbacks and ticket/record links. The backend currently keeps transfers and tickets in memory, so a backend restart or deployment clears them.

Vercel’s deployment protection may additionally require the project owner to sign in. Share the preview according to the project’s access settings.

## Verification

- `make test`
- `node --test apps/dashboard/tests/relay.test.mjs`
- Build with the two `VITE_` settings above.
- Verify the cloud backend’s `/dashboard/health` responds without an access code.
- Deployment readiness is reported by the Vercel CLI. A live phone rehearsal requires the configured demo participants to be ready.

The submitted domain is the production URL. Use `--prod` instead of `--target preview` when updating that submitted site.
