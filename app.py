"""The classifier service.

Runs on its own box, reachable only over the private network. It holds no
credentials, touches no database, and stores nothing: bytes in, scores out.
That is deliberate -- it is the component most likely to be replaced, and the
one whose compromise should cost the least.

Run:
    CONTENT_SCAN_TOKEN=... uvicorn app:app --host <tailnet-ip> --port 8099
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from labels import categories_from_detections
from prompts import ALL_PROMPTS, merge_second_opinion, unsafe_confidence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('content_scan_service')

TOKEN = os.environ.get('CONTENT_SCAN_TOKEN', '')
MAX_BYTES = int(os.environ.get('CONTENT_SCAN_MAX_BYTES', str(12 * 1024 * 1024)))
if MAX_BYTES < 1:
    raise RuntimeError('CONTENT_SCAN_MAX_BYTES must be a positive integer')

app = FastAPI(title='content scan', docs_url=None, redoc_url=None)

_detector = None
_clip = None

# The band the first pass cannot call. Only these images cost a second model.
# OFF by default: with the part-level taxonomy back, the second stage is a
# tuning lever rather than a necessity, and it doubles resident memory.
SECOND_OPINION = os.environ.get('CONTENT_SCAN_SECOND_OPINION', '') == '1'
SECOND_OPINION_LOW = float(os.environ.get('CONTENT_SCAN_SECOND_OPINION_LOW', '0.30'))
SECOND_OPINION_HIGH = float(os.environ.get('CONTENT_SCAN_SECOND_OPINION_HIGH', '0.97'))
SECOND_OPINION_RAISE_CAP = float(
    os.environ.get('CONTENT_SCAN_SECOND_OPINION_RAISE_CAP', '0.75')
)
CLIP_MODEL = os.environ.get('CONTENT_SCAN_CLIP_MODEL', 'openai/clip-vit-base-patch32')

if not 0 <= SECOND_OPINION_RAISE_CAP < 0.90:
    raise RuntimeError(
        'CONTENT_SCAN_SECOND_OPINION_RAISE_CAP must be between 0 and 0.90'
    )


MODEL_ID = os.environ.get('CONTENT_SCAN_MODEL', 'nudenet')

# AGPL section 13 obliges us to offer the source of THIS service to anyone
# interacting with it over a network. Served from the service itself so the
# offer travels with the running code rather than living in a README nobody
# reaching the API can see.
SOURCE_URL = os.environ.get(
    'CONTENT_SCAN_SOURCE_URL',
    'https://github.com/fazakis/gymapp_content_scan',
)


def detector():
    """Loaded once, on first use.

    Resident rather than per-request: loading costs seconds and inference costs
    milliseconds, so a per-request load would make the model load the entire
    cost of the service.

    AGPL-3.0, deliberately: the part-level taxonomy is worth more than any
    permissively-licensed single-score alternative, and the cost of keeping it
    is publishing this directory. See LICENSE and README.md.
    """
    global _detector
    if _detector is None:
        from nudenet import NudeDetector

        _detector = NudeDetector()
        logger.info('detector loaded: part-level (AGPL-3.0)')
    return _detector


def clip():
    """CLIP, loaded lazily and only if the second stage is ever reached.

    MIT licensed, code and weights, and it runs here -- it is a downloadable
    model, not an API call, so no image leaves this box.
    """
    global _clip
    if _clip is None:
        from transformers import CLIPModel, CLIPProcessor

        model = CLIPModel.from_pretrained(CLIP_MODEL)
        model.eval()
        _clip = (model, CLIPProcessor.from_pretrained(CLIP_MODEL))
        logger.info('clip loaded: %s', CLIP_MODEL)
    return _clip


def second_opinion(image) -> float | None:
    """Score the image against our own prompts. None if it could not be done.

    The primary taxonomy remains the detector's exposed/covered body-part
    labels. These prompts are an optional fitness-specific tiebreaker for an
    ambiguous explicit score. See prompts.py.
    """
    try:
        import torch

        model, processor = clip()
        inputs = processor(text=list(ALL_PROMPTS), images=image, return_tensors='pt', padding=True)
        with torch.no_grad():
            probs = model(**inputs).logits_per_image.softmax(dim=1)[0].tolist()
    except Exception as exc:
        # Never fatal: the first pass already produced a usable score, and a
        # broken tiebreaker must not turn a working scan into a failed one.
        logger.warning('second opinion failed: %s', exc)
        return None
    score = unsafe_confidence(probs)
    return None if score < 0 else score


@app.get('/source')
def source():
    """Where to get this service's source.

    Required by AGPL section 13: anyone interacting with this over a network is
    entitled to the corresponding source. Unauthenticated on purpose -- an offer
    only visible to people holding our token is not an offer.
    """
    return {'source': SOURCE_URL, 'license': 'AGPL-3.0-or-later'}


@app.get('/health')
def health():
    """Liveness only. Deliberately does NOT load the model: a health check that
    pulls 600 MB into memory turns a monitoring poll into an outage."""
    return {'ok': True}


@app.get('/ready')
def ready():
    """Load every configured model before accepting traffic.

    In particular, setting CONTENT_SCAN_SECOND_OPINION on the default image is
    a deployment error. Readiness exposes the missing optional dependencies or
    weights instead of claiming success and silently degrading every request.
    """
    try:
        detector()
        if SECOND_OPINION:
            clip()
    except Exception as exc:
        return JSONResponse({'ok': False, 'detail': str(exc)}, status_code=503)
    return {'ok': True}


@app.post('/classify')
async def classify(request: Request, authorization: str = Header(default='')):
    if TOKEN:
        if not secrets.compare_digest(authorization, f'Bearer {TOKEN}'):
            raise HTTPException(status_code=401, detail='bad token')
    else:
        # Refuses to run open. The tailnet is the first line, but a service that
        # would happily answer anyone who reaches it is one firewall mistake
        # away from being a public nudity-detection API on our bill.
        raise HTTPException(status_code=503, detail='CONTENT_SCAN_TOKEN is not set')

    chunks = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_BYTES:
            raise HTTPException(status_code=413, detail='too large')
        chunks.append(chunk)
    body = b''.join(chunks)
    if not body:
        raise HTTPException(status_code=400, detail='empty body')

    import io
    import tempfile

    from PIL import Image

    # Decoded in memory and never written to disk: nothing about a user's photo
    # outlives the request, which is what makes this box safe to run elsewhere.
    try:
        image = Image.open(io.BytesIO(body))
        image.load()
        image = image.convert('RGB')
    except Exception as exc:
        # A file we cannot decode is a bad request, not a scanner failure --
        # distinguishing them matters because the caller turns a scanner
        # failure into "uncertain" and a bad request into an upload error.
        logger.warning('undecodable image: %s', exc)
        raise HTTPException(status_code=400, detail='could not decode image') from exc

    # The detector reads from a path. Written to a temp file removed on exit --
    # nothing about a user's photo outlives the request, which is what makes
    # this box safe to run somewhere else.
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg') as handle:
            image.save(handle, format='JPEG')
            handle.flush()
            predictions = detector().detect(handle.name)
    except Exception as exc:
        # 502, not 200-with-empty-scores: the caller must be able to tell
        # "nothing found" from "nothing looked", because those become
        # different verdicts.
        logger.warning('detection failed: %s', exc)
        raise HTTPException(status_code=502, detail='detector failed') from exc

    categories = categories_from_detections(predictions)

    # Second stage, on the middle band only. A confident call from the first
    # pass is left alone -- paying for a tiebreaker on an obvious image would
    # cost 10x the compute to change nothing.
    first = categories.get('explicit', 0.0)
    if SECOND_OPINION and SECOND_OPINION_LOW <= first < SECOND_OPINION_HIGH:
        refined = second_opinion(image)
        if refined is not None:
            categories['explicit'] = merge_second_opinion(
                first,
                refined,
                raise_cap=SECOND_OPINION_RAISE_CAP,
            )
            logger.info('second opinion: %.2f -> %.2f', first, categories['explicit'])
    # Never log the image, its bytes, or a path that outlives the request. The
    # count is enough to tell a working service from a silent one.
    logger.info('classified: %d predictions, %d actionable', len(predictions or []), len(categories))
    return {'categories': categories}
