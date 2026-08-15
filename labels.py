"""Turning a detector's part labels into the three categories we act on.

This file IS the false-positive strategy. Everything else in the service is
plumbing around it.

## Licensing — read before changing the detector

The detector is **AGPL-3.0**. That is a deliberate, decided choice, not an
oversight: the part-level taxonomy below is worth more than the alternatives,
and the cost of keeping it is publishing THIS DIRECTORY under AGPL. See
`LICENSE` and the licensing section of `README.md`.

The rest of the repository is NOT AGPL and must not become so. That boundary
holds because this service is a separate process reached over HTTP — it shares
no code, no imports and no runtime with the Django application. **Do not import
anything from this directory into the backend, and do not import backend code
here.** Doing so is what would drag the copyleft across the line.

A part-level detector (NudeNet-style) is chosen over a single-score NSFW
classifier for one reason: it distinguishes *which* part and whether it is
covered. A blended "is this NSFW" number cannot tell a shirtless deadlift from
pornography, and that distinction is most of the content in a fitness app.

The rule below is not "how explicit is this image". It is "would a reasonable
person say this does not belong in a gym app" -- which is a much narrower
question, and answering the narrow one is why this works.
"""
from __future__ import annotations

# The reason this file is worth an AGPL obligation: the labels distinguish
# COVERED from EXPOSED. That distinction is the difference between a shirtless
# deadlift and pornography, and it is most of the content in this app. A
# permissively-licensed single-score classifier cannot make it, which is why
# the alternative required a human review queue to catch what it could not.
#
# Detector label -> (our category, how much we trust it to mean "actionable").
#
# The weight is a deliberate confidence calibration, not a fudge. A detection
# we are certain about maps at 1.0 and can reach the block threshold on its own.
# One we are less sure carries a different meaning in THIS app is scaled so a
# confident detection lands in the middle band and a human looks, rather than
# a user being blocked by a rule we were not confident enough to write.
ACTIONABLE_LABELS: dict[str, tuple[str, float]] = {
    'FEMALE_GENITALIA_EXPOSED': ('explicit_nudity', 1.0),
    'MALE_GENITALIA_EXPOSED': ('explicit_nudity', 1.0),
    'ANUS_EXPOSED': ('explicit_nudity', 1.0),
    'FEMALE_BREAST_EXPOSED': ('explicit', 1.0),
    # Posing trunks exist, and physique athletes photograph themselves in them.
    # Scaled so a confident detection asks a human instead of removing a
    # bodybuilder's competition photo automatically.
    'BUTTOCKS_EXPOSED': ('explicit', 0.7),
}

# Labels a general-purpose model reports enthusiastically and that mean nothing
# here. Listed EXPLICITLY rather than left to fall through the default, so that
# a future model adding a label cannot silently start blocking gym photos --
# anything unrecognised is ignored, and this list documents why the common ones
# are, so nobody "fixes" it later by wiring them up.
FITNESS_NORMAL_LABELS = frozenset({
    'MALE_BREAST_EXPOSED',      # a shirtless man. Half the lifting videos here.
    'FEMALE_BREAST_COVERED',    # a sports bra.
    'BELLY_EXPOSED',            # a crop top, or a progress photo.
    'BELLY_COVERED',
    'ARMPITS_EXPOSED',          # every overhead press ever filmed.
    'ARMPITS_COVERED',
    'FEET_EXPOSED',             # barefoot deadlifts, yoga.
    'FEET_COVERED',
    'BUTTOCKS_COVERED',         # leggings.
    # The dangerous one: a "covered genitalia" detector fires on leggings and
    # compression shorts. Wiring this up would flag a large share of the
    # women's content in the app, and it describes clothing, not nudity.
    'FEMALE_GENITALIA_COVERED',
    'FACE_FEMALE',
    'FACE_MALE',
})


def categories_from_detections(detections) -> dict[str, float]:
    """[{class, score}, ...] -> {our category: confidence}.

    Takes the HIGHEST score per category rather than summing: three detections
    of the same thing is one fact about the image, and summing would push an
    image over a threshold by being busy rather than by being explicit.
    """
    scores: dict[str, float] = {}
    for detection in detections or []:
        label = str((detection or {}).get('class') or (detection or {}).get('label') or '')
        mapped = ACTIONABLE_LABELS.get(label.upper())
        if not mapped:
            # Unrecognised and fitness-normal labels both land here. Silence is
            # correct: a label we have not reasoned about must not be able to
            # block anyone.
            continue
        category, weight = mapped
        try:
            score = float((detection or {}).get('score', 0.0))
        except (TypeError, ValueError):
            continue
        if score <= 0:
            continue
        scores[category] = max(scores.get(category, 0.0), min(1.0, score * weight))
    return scores
