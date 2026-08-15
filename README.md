# content-scan

An image classification service. Bytes in, category scores out.

No database, no credentials, no storage access, nothing persisted. It answers
*"what is in this image"* and nothing else — every decision about what to do
with the answer is made by the caller.

## Licence

**AGPL-3.0** (see `LICENSE`). It depends on an AGPL-3.0 nudity detector, so the
service inherits that licence.

This repository is published to satisfy AGPL §13: anyone interacting with a
running instance over a network is entitled to its corresponding source. It is a
mirror of one directory of a private repository; the rest of that repository is
separate, proprietary work that shares no code, no imports and no runtime with
this service and communicates with it only over HTTP.

## The interesting part

`labels.py`.

General-purpose nudity detection is badly behaved on fitness content. Shirtless
lifting, sports bras, physique photos and compression shorts all read as
"nudity" to a naive classifier — and a *covered*-genitalia detector fires on
leggings.

A single "is this NSFW" score cannot separate a shirtless deadlift from
pornography. A **part-level** detector can, because it reports which part and
whether it is covered. `labels.py` maps those labels to three categories and
deliberately ignores the ones that are normal in a gym, with a test for each.

If you have the same problem, that file is the useful bit.

## Running it

```bash
pip install -r requirements.txt
CONTENT_SCAN_TOKEN=$(openssl rand -hex 32) uvicorn app:app --host 127.0.0.1 --port 8099
```

Or with Docker — the image bakes the model in at build time, so no weights are
fetched on first request:

```bash
docker build -t content-scan .
docker run -d -e CONTENT_SCAN_TOKEN=... -p 127.0.0.1:8099:8099 content-scan
```

**Bind it to an address only your own services can reach.** The service refuses
to answer without a bearer token, but a token is a second line of defence, not
the first.

## Endpoints

| | |
|---|---|
| `POST /classify` | raw image bytes, `Authorization: Bearer <token>`. Returns `{"categories": {...}}`; an empty object means nothing actionable was found. |
| `GET /health` | liveness. Deliberately does **not** load the model — a health check that pulls hundreds of MB into memory turns a monitoring poll into an outage. |
| `GET /ready` | loads the model, so readiness means it can actually answer. |
| `GET /source` | the AGPL §13 source offer. Unauthenticated by design. |

A detector failure is **502, not 200 with empty scores** — a caller must be able
to tell "nothing found" from "nothing looked", because those are different
answers.

## Configuration

| variable | |
|---|---|
| `CONTENT_SCAN_TOKEN` | required; the service refuses to answer without it |
| `CONTENT_SCAN_WORKERS` | uvicorn workers. The model is resident **per process** — size to available RAM |
| `CONTENT_SCAN_MAX_BYTES` | request body limit |
| `CONTENT_SCAN_SOURCE_URL` | what `/source` reports |

## Issues

Bug reports about this service are welcome. It is one component and cannot see
anything else, so that is the only thing it can help with.
