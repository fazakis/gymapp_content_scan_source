import unittest

from prompts import (
    ALL_PROMPTS,
    SAFE_PROMPTS,
    UNSAFE_PROMPTS,
    merge_second_opinion,
    unsafe_confidence,
)


def probabilities(safe_mass, unsafe_mass):
    return (
        [safe_mass / len(SAFE_PROMPTS)] * len(SAFE_PROMPTS)
        + [unsafe_mass / len(UNSAFE_PROMPTS)] * len(UNSAFE_PROMPTS)
    )


class PromptPolicyTests(unittest.TestCase):
    def test_prompt_order_matches_the_confidence_slice(self):
        self.assertEqual(ALL_PROMPTS[:len(SAFE_PROMPTS)], SAFE_PROMPTS)
        self.assertEqual(ALL_PROMPTS[len(SAFE_PROMPTS):], UNSAFE_PROMPTS)

    def test_confidence_uses_probability_mass(self):
        self.assertLess(unsafe_confidence(probabilities(0.95, 0.05)), 0.1)
        self.assertGreater(unsafe_confidence(probabilities(0.05, 0.95)), 0.9)

    def test_second_opinion_moves_both_directions(self):
        self.assertEqual(merge_second_opinion(0.70, 0.08, raise_cap=0.75), 0.08)
        self.assertEqual(merge_second_opinion(0.41, 0.91, raise_cap=0.75), 0.75)

    def test_second_opinion_cannot_raise_into_automatic_removal(self):
        self.assertLess(merge_second_opinion(0.41, 0.99, raise_cap=0.75), 0.90)


if __name__ == '__main__':
    unittest.main()
