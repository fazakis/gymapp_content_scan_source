# content scan service

A classifier on its own box. Bytes in, category scores out. No database, no
credentials, no storage access, nothing persisted.

It lives in this repo but deploys separately. The reason to keep it here is the
contract: `content_scan/test_service_contract.py` asserts that every category
this service emits is one the Django policy acts on. Split across two repos,
renaming a category on one side would leave the other scoring nothing — and a
scanner that finds nothing looks exactly like a clean feed.

## ⚠️ Licensing — this directory is AGPL-3.0, the rest of the repo is not

**This directory is published under AGPL-3.0** (see `LICENSE`). The rest of
`gymapp_backend` is proprietary and must stay that way.

### Why

The detector reports **which body part** and whether it is **covered**. That
distinction is the difference between a shirtless deadlift and pornography, and
it is most of the content in this app. Every permissively-licensed alternative
is a single-score classifier that cannot make it — and without it, fitness
photos have to be sent to a human review queue instead of being dismissed by
category.

We judged the taxonomy worth more than the alternative, and the price of keeping
it is publishing this directory. That was a deliberate decision.

### How the boundary holds

This service is a **separate process** reached over HTTP. It shares no code, no
imports and no runtime with the Django application, which is the standard basis
for the backend not being a derivative work — the same reasoning that lets
closed software call an AGPL database over a socket.

**Two rules keep it true:**

1. **Never import anything from this directory into the backend**, and never
   import backend code here. `content_scan/test_service_contract.py` reads
   `labels.py` off the filesystem for assertions only, and that is the closest
   the two ever come.
2. **Keep the source published.** AGPL §13 obliges us to offer the corresponding
   source to anyone interacting with this over a network. `GET /source` serves
   that offer, unauthenticated — an offer only visible to holders of our token
   is not an offer. The canonical public mirror is
   <https://github.com/fazakis/gymapp_content_scan>.

**This is not legal advice.** The arrangement was chosen on that basis; if you
intend to rely on it, have a lawyer confirm it.

## The optional second stage

`prompts.py` and the CLIP path remain **off in the default image** so a local or
test install stays small. Production enables them: real-world calibration found
that a part detector can miss an unmistakable sexual scene when bodies are
occluded, angled, or partly clothed. CLIP supplies that missing scene-level
second opinion while the policy still caps how far it may raise a score.

The default install and Docker image do not contain CLIP or torch. For a local
environment, install `requirements-second-opinion.txt` in addition to the base
requirements. For an image, build with
`--build-arg CONTENT_SCAN_INCLUDE_SECOND_OPINION=1`, then set
`CONTENT_SCAN_SECOND_OPINION=1` at runtime. Readiness deliberately fails if the
runtime flag is enabled on an image that was not built with the optional model.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

First use downloads the model. Do that at deploy time, not on first request —
the Dockerfile bakes every included model in at build time for this reason.

## Run

```bash
CONTENT_SCAN_TOKEN=$(openssl rand -hex 32) \
  uvicorn app:app --host 100.x.y.z --port 8099
```

**Bind to the tailnet address, never `0.0.0.0`.** The token is a second line,
not the first: the service refuses to start answering without one, but a public
listener plus a leaked token is a public nudity-detection API on your bill.

Set the same token as `CONTENT_SCAN_TOKEN` on the Django side, with
`CONTENT_SCAN_PROVIDER=http` and `CONTENT_SCAN_URL=http://100.x.y.z:8099/classify`.

## systemd

```ini
[Unit]
Description=content scan
After=network-online.target

[Service]
Environment=CONTENT_SCAN_TOKEN=...
ExecStart=/opt/content-scan/.venv/bin/uvicorn app:app --host 100.x.y.z --port 8099
WorkingDirectory=/opt/content-scan
Restart=always
# The model is resident; this keeps a leak from taking the box down.
MemoryMax=2G
# It reads no files it is not handed and writes only to its own temp dir.
ProtectSystem=strict
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

## Sizing

The detector is ONNX and resident **per process**: budget **~600 MB per worker**,
so the 8 GB box runs 3–4 comfortably. Enabling the optional CLIP stage roughly
doubles that — 2 workers then, not 4.

**Dedicated** cores matter more than the count — sustained inference is exactly
the workload shared-vCPU plans throttle.

## Endpoints

- `GET /health` — liveness. Deliberately does **not** load the model; a health
  check that pulls 600 MB into memory turns a monitoring poll into an outage.
- `GET /ready` — loads the model, so readiness means "can actually answer".
- `POST /classify` — raw image bytes, `Authorization: Bearer <token>`.
  Returns `{"categories": {"explicit_nudity": 0.93}}`. An empty object means
  nothing actionable was found.

A detector failure is **502, not 200 with empty scores** — the caller has to be
able to tell "nothing found" from "nothing looked", because those become
different verdicts.

## What it deliberately does not do

- **No decisions.** It never says block or allow, only what it saw. Trust
  weighting, thresholds and takedowns all stay in Django where the user data
  already is.
- **No logging of images**, bytes, or paths that outlive a request.
- **No storage access.** It is handed the one image it must look at. Giving it
  a URL instead would mean storage credentials on the box, turning a stateless
  service into one whose compromise is a data breach.

## Before trusting it in production

Calibrate the thresholds on **real uploads from this app**, not on the model's
defaults — the whole premise is that our content sits where general-purpose
models are weakest. A few hundred labelled images is enough to see the shape.
That means a person looking at users' photos: keep it to one person, keep it
off shared storage, and do not retain them afterwards.
