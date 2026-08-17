# Its own image, built from the same repo but deployed on its own boxes.
# Nothing here shares a runtime with the API: no Django, no database driver,
# no storage client. That is what keeps a compromise of this container from
# reaching user data.
FROM python:3.12-slim

# The unprivileged user is created FIRST, and the model cache is written as
# that user. The obvious ordering -- download as root, then `chown -R` -- both
# duplicates several GB into a new layer (which exhausted the CI runner's disk)
# and is unnecessary. Doing it in this order means no large chown ever happens.
RUN useradd --system --uid 10001 --create-home --home-dir /home/scanner scanner

WORKDIR /app
COPY requirements.txt requirements-second-opinion.txt ./

# The default image contains only the primary part-level detector. CLIP is a
# several-GB optional tuning lever, so merely leaving it disabled at runtime is
# not enough: installing and baking it by default exhausted the CI runner while
# exporting an image that would never use it.
ARG CONTENT_SCAN_INCLUDE_SECOND_OPINION=0
RUN set -eu; \
    pip install --no-cache-dir -r requirements.txt; \
    case "$CONTENT_SCAN_INCLUDE_SECOND_OPINION" in \
      0) ;; \
      1) pip install --no-cache-dir -r requirements-second-opinion.txt ;; \
      *) echo 'CONTENT_SCAN_INCLUDE_SECOND_OPINION must be 0 or 1' >&2; exit 2 ;; \
    esac

# Weights live under the scanner's own home so the runtime user can actually
# read them. Downloading them as root would leave them unreadable after
# USER scanner, and the service would silently re-download on first request --
# turning the first uncertain image into a timeout.
ENV HF_HOME=/home/scanner/.cache/huggingface

ARG CONTENT_SCAN_MODEL=nudenet
ARG CONTENT_SCAN_CLIP_MODEL=openai/clip-vit-base-patch32
ENV CONTENT_SCAN_MODEL=${CONTENT_SCAN_MODEL}
ENV CONTENT_SCAN_CLIP_MODEL=${CONTENT_SCAN_CLIP_MODEL}

# Every included model is baked in at BUILD time, as the runtime user. A
# container that fetches a model when the first user posts a photo turns a
# deploy into an outage that only appears under traffic.
USER scanner
RUN set -eu; \
    python -c "from nudenet import NudeDetector; NudeDetector()"; \
    if [ "$CONTENT_SCAN_INCLUDE_SECOND_OPINION" = 1 ]; then \
      python -c "from transformers import CLIPModel, CLIPProcessor; CLIPModel.from_pretrained('${CONTENT_SCAN_CLIP_MODEL}'); CLIPProcessor.from_pretrained('${CONTENT_SCAN_CLIP_MODEL}')"; \
    fi

# LICENSE ships in the image: AGPL requires it to travel with the work.
COPY --chown=scanner:scanner LICENSE labels.py prompts.py app.py ./

EXPOSE 8099
# The ONNX detector is resident PER PROCESS. An explicitly CLIP-enabled image
# also keeps a torch ViT resident and roughly doubles memory. Size workers for
# the image you built; past that, add a box because the app side accepts a
# comma-separated list of instances.
ENV CONTENT_SCAN_WORKERS=1
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8099 --workers ${CONTENT_SCAN_WORKERS}"]
