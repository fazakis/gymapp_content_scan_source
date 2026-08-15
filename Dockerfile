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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Weights live under the scanner's own home so the runtime user can actually
# read them. Downloading them as root would leave them unreadable after
# USER scanner, and the service would silently re-download on first request --
# turning the first uncertain image into a timeout.
ENV HF_HOME=/home/scanner/.cache/huggingface

ARG CONTENT_SCAN_MODEL=nudenet
ARG CONTENT_SCAN_CLIP_MODEL=openai/clip-vit-base-patch32
ENV CONTENT_SCAN_MODEL=${CONTENT_SCAN_MODEL}
ENV CONTENT_SCAN_CLIP_MODEL=${CONTENT_SCAN_CLIP_MODEL}

# Both models baked in at BUILD time, as the runtime user. A container that
# fetches a model when the first user posts a photo turns a deploy into an
# outage that only appears under traffic.
USER scanner
RUN python -c "from nudenet import NudeDetector; NudeDetector()" \
 && python -c "from transformers import CLIPModel, CLIPProcessor; CLIPModel.from_pretrained('${CONTENT_SCAN_CLIP_MODEL}'); CLIPProcessor.from_pretrained('${CONTENT_SCAN_CLIP_MODEL}')"

# LICENSE ships in the image: AGPL requires it to travel with the work.
COPY --chown=scanner:scanner LICENSE labels.py prompts.py app.py ./

EXPOSE 8099
# Both models are resident PER PROCESS and these are torch ViTs, not quantised
# ONNX graphs -- budget ~1.2-1.5 GB per worker. On an 8 GB box that is 2-3
# workers, not 4. Past that, add a box: the app side takes a comma-separated
# list of instances.
ENV CONTENT_SCAN_WORKERS=1
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8099 --workers ${CONTENT_SCAN_WORKERS}"]
