# Photon SMS approval (SPEC section 10)

Human-in-the-loop for an optimized schedule. When a proposed schedule
with `shifted_job_count > 0` is submitted for approval, the backend texts
the operator; a `YES`/`NO` reply drives the schedule state machine.

## Modes

| `PHOTON_MODE` | Send | Inbound | Network |
|---|---|---|---|
| `mock` (default) | returns `mock-sms-<schedule_id>`, logs `sms_sent` | accepts `{"message_id","from_number","text"}` at `POST /api/webhooks/photon` | none |
| `live` | Photon Beta `POST /v1/projects/{id}/messages` | `message.received` delivery, Standard-Webhooks signature check | Photon API + inbound webhook |

Live needs `PHOTON_API_KEY` (`pho_sk_`), `PHOTON_PROJECT_ID` (`pho_prj_`),
`OPERATOR_PHONE`, `PHOTON_WEBHOOK_SECRET` (returned by destination
registration) and `PHOTON_PLATFORM` (`imessage` or `sms`). With the key
or project id missing, live is *unconfigured*: webhook returns
`501 photon_unconfigured`, `send_approval_sms` logs `error` and returns
the mock id without networking — the SPEC 10 fallback.

## Channel note: iMessage shared line, not carrier SMS

The project's plan has no purchased SMS number (`platforms/sms/numbers`
needs paid capacity + 10DLC). We use a **shared iMessage line** instead —
identical reply flow, same text contract. Constraint: a shared line
**cannot send first**. The operator must send any message to the assigned
line once; that inbound `message.received` creates the space the send
path uses. If a real SMS number is purchased later, set
`PHOTON_PLATFORM=sms` — the code paths are identical.

## Sequence

```
POST /api/schedules/{id}/request-approval
  -> schedules.request_approval (proposed -> pending_approval,
     expires any older pending row with superseded_by_new_request)
  -> send_approval_sms:
       mock: logs sms_sent with mock-sms- id
       live: POST /users (create-or-get operator, platform handle)
             GET  /spaces (find direct space, agent = other participant)
             POST /messages (text content, Idempotency-Key =
             gridpulse-approval-<schedule_id>; 10 s timeout, one retry)
       -> logs sms_sent with the masked phone and text
          "GridPulse: {n} jobs shifted, {kwh:.1f} kWh moved into
          {start}-{end} UTC. Reply YES or NO"
  -> background task: after PHOTON_TIMEOUT_SECONDS (default 300) a
     still-pending row is expired with reason timeout

Reply (mock): POST /api/webhooks/photon
  {"message_id": "sim-...", "from_number": "+1555...", "text": "YES"}

Reply (live): Photon posts a message.received event; we verify
  webhook-id/webhook-timestamp/webhook-signature (HMAC-SHA256 of
  "<id>.<ts>.<rawBody>" under the destination secret, 401 on failure),
  map data.object.id / sentBy.handle / content.text, and require
  from_number == OPERATOR_PHONE. Non-message events are acked as
  ignored/not_pending.

State machine (both modes, in _handle_reply):
  duplicate message_id            -> ignored / duplicate
  no pending_approval schedule    -> ignored / not_pending
  strip().upper() == "YES"        -> approve_and_apply(actor=photon, via=sms)
  "NO"                            -> reject(actor=photon, reason=sms_no)
  other text, first               -> clarification_sent ("Reply YES or NO")
  other text, again               -> sms_reply only, stays pending
```

Inbound text is untrusted: only exact `YES`/`NO` after `strip().upper()`
acts; it is never sent to an LLM, shell, SQL, or file path. Phone numbers
are masked (last 2 chars) in every log.

## Run it (mock)

```bash
cd backend && uvicorn main:app --port 8000
SID=$(curl -s -X POST localhost:8000/api/optimize \
      -H 'Content-Type: application/json' -d '{"alpha":0.5}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["schedule_id"])')
curl -s -X POST localhost:8000/api/schedules/$SID/request-approval
python3 ../scripts/simulate_reply.py YES
```

`simulate_reply.py` reads `OPERATOR_PHONE` from `.env`, posts to
`GRIDPULSE_API_URL` (default `http://127.0.0.1:8000`), masks the number.

## Exposing the webhook for live

The public path is `POST /api/webhooks/photon`.

- **cloudflared** (used; no account needed):
  `cloudflared tunnel --url http://localhost:8000` prints an ephemeral
  `https://*.trycloudflare.com` URL. Ephemeral — re-register the
  destination after each restart (or use a named tunnel for a stable URL).
- **ngrok**: `ngrok http 8000` -> `https://<id>.ngrok-free.app/api/webhooks/photon`
  (this machine's ngrok account required a paid plan for URLs).
- **Vultr**: uvicorn on `0.0.0.0:8000` behind an HTTPS reverse proxy;
  Photon requires an HTTPS URL without credentials/fragment.

Register (documented): `POST /v1/projects/{id}/webhooks/destinations`
with `{apiVersion: "2026-07-01", url, enabledEvents: ["message.received"]}`;
the response `signingSecret` goes to `PHOTON_WEBHOOK_SECRET` in `.env`.

## Live field mapping (verified against a real delivery, 2026-10-18)

Documented schema: `GET .../webhooks/event-types/message.received/schema`.
Real object captured in `docs/photon_payload_example.json`.

- `message_id` <- `data.object.id` (`pho_msg_...`)
- `from_number` <- `data.object.sentBy.handle`
- `text` <- `data.object.content.text` (only when `content.type == "text"`)

## Verified live — 2026-10-18

- Shared iMessage line assigned via `POST .../platforms/imessage/assignments`
  (agent number `+1 628-…-22`, handle = `OPERATOR_PHONE`).
- Webhook destination `pho_whd_01m565yzwaecs874dg9dwj9nv9` -> trycloudflare
  URL; signature verified end-to-end.
- Operator's first text `hi` reached the webhook (`sms_reply`,
  `pho_msg_0b0m…`, ignored/not_pending — no pending schedule).
- `request-approval` sent the real approval text (`pho_msg_1bzg…`).
- Operator reply `YES ` applied `sch-20261018T002310Z-a050`:
  `sms_reply -> approved via=sms -> superseded -> applied`.

## Still not covered

- Carrier-SMS platform (`PHOTON_PLATFORM=sms`): code path exists, no SMS
  number on the project, so only `imessage` was exercised live.
- Timeout during live: the background expiry task is transport-agnostic
  and tested (PH-5) in mock mode.
- Signature failure path: unit-covered behavior, not exercised against a
  real bad-signature delivery.
