# Alibaba Function Compute telemetry scaffold

This directory is a minimal, deployable reference receiver for **redacted metadata only**. It verifies `HMAC-SHA256(timestamp + "." + raw_body)`, rejects requests more than five minutes old, rejects unknown/content-bearing fields, and writes accepted scalar events to Function Compute logs. It has no database, dashboard, replay database, or policy-distribution feature, and the edge loop does not send events to it yet.

This source tree is not evidence of an Alibaba deployment. Before making that claim, deploy it in your Alibaba Cloud account, invoke it from a controlled demo client, retain the Function Compute resource/region view and invocation logs, and capture judge-safe screenshots. Rotate the demo secret afterward.

## Validate locally

```bash
cd cloud/alibaba-telemetry
python -m unittest -v test_index.py
```

## Deploy with Serverless Devs

Install and authenticate the current Serverless Devs CLI using Alibaba's official instructions, then provide a region and a randomly generated secret of at least 32 characters:

```bash
export ALIBABA_CLOUD_REGION=us-west-1
export TELEMETRY_HMAC_SECRET="$(openssl rand -hex 32)"
s deploy --use-local --template s.yaml
```

The HTTP trigger is intentionally `anonymous` at the platform layer because the handler performs end-to-end HMAC verification over the exact request body. For production, store the HMAC key in Alibaba Cloud KMS/Secrets Manager rather than shell history or plain deployment state, add WAF/rate limits, and use a replay store keyed by `event_id`.

Every request must include:

- `X-ConglomerAIte-Timestamp`: current Unix seconds;
- `X-ConglomerAIte-Signature`: `sha256=<lowercase HMAC hex>`;
- a JSON body containing only the allowlisted schema fields in `index.py`.

Hash node/task identifiers with a deployment-specific keyed hash before sending them; a plain hash of a predictable identifier can still be reversible by guessing. Never send task, prompt, draft, critique, result, API-key, hostname, username, IP, or model-output content.

`s.yaml` targets the `fc3` component and Python 3.10. Validate the component/runtime/region against current Alibaba Cloud documentation at deployment time; availability and schema can change. Record the exact deployed template and CLI version with the submission evidence.
