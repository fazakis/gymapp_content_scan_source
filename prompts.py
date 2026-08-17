"""Optional fitness-specific prompts for ambiguous detector scores.

## Why this exists

The primary detector uses part-level labels that distinguish
*covered* from *exposed* — the difference between a shirtless deadlift and
pornography, which is most of this app's content. We deliberately kept that
AGPL-3.0 detector under Option A and publish this service's corresponding
source.

CLIP is retained as an optional second opinion because it scores an image
against **arbitrary text**. It can ask a narrower, fitness-specific question
when a part-level `explicit` score sits in the ambiguous band. It does not
replace the primary label mapping and is off by default.

## How it is used

NOT on every upload. The part-level detector is the first pass; this runs only
on an ambiguous `explicit` score — a few percent of images. It can lower that
score when a fitness-specific prompt explains the image, but it cannot create
a removal the primary detector did not already suspect.

## Tuning

These are prompts, not code. Edit them against real examples and re-check; there
is nothing to retrain and nothing to redeploy but this file.

Two rules when editing:

1. **Keep the safe list specific.** "A person exercising" is too broad to
   discriminate. "A woman in a sports bra lifting weights in a gym" is a
   description CLIP can actually match against.
2. **Keep the two lists balanced in specificity.** Zero-shot scoring is
   comparative — a vague unsafe prompt against precise safe prompts will lose
   every time, and vice versa. That asymmetry, not the model, is how these
   go wrong.
"""
from __future__ import annotations

# Descriptions of content that is NORMAL here. Deliberately concrete, and
# deliberately covering the cases a general-purpose model gets wrong: gym
# clothing exposes skin, and that is the whole point of the garment.
SAFE_PROMPTS: tuple[str, ...] = (
    'a shirtless man lifting weights in a gym',
    'a muscular man flexing to show his physique',
    'a woman in a sports bra exercising in a gym',
    'a woman in athletic leggings working out',
    'a bodybuilder posing on stage in competition trunks',
    'a person in running shorts and a vest running outdoors',
    'a person in compression shorts doing squats',
    'a fitness progress photo of a person in underwear showing their body',
    'a person in swimwear at a swimming pool',
    'a close-up of a person flexing an arm muscle',
    'a person stretching on a yoga mat',
    'a photograph of gym equipment',
    'an ordinary photograph of a clothed person',
)

# Descriptions of content that does NOT belong here. Kept narrow: this list
# decides removals, and a broad prompt here is a false positive machine.
UNSAFE_PROMPTS: tuple[str, ...] = (
    'explicit sexual activity between people',
    'full frontal nudity with exposed genitals',
    'a close-up photograph of exposed genitals',
    'pornographic content',
)

ALL_PROMPTS: tuple[str, ...] = SAFE_PROMPTS + UNSAFE_PROMPTS


def unsafe_confidence(probabilities) -> float:
    """Total probability mass sitting on the unsafe prompts.

    Summed rather than "is the top match unsafe": an image that matches four
    explicit descriptions at 0.2 each is more concerning than one matching a
    single safe description at 0.3, and an argmax would call the first one safe.

    `probabilities` must be aligned with ALL_PROMPTS.
    """
    values = list(probabilities or [])
    if len(values) != len(ALL_PROMPTS):
        # Misaligned input is a bug, not a clean image. The caller turns None
        # into "could not scan", which is the honest answer.
        return -1.0
    unsafe = values[len(SAFE_PROMPTS):]
    total = sum(float(v) for v in values) or 1.0
    return max(0.0, min(1.0, sum(float(v) for v in unsafe) / total))
