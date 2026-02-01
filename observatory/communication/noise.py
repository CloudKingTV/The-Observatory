"""
Communication noise system.

Messages between agents are subject to noise/misinterpretation
based on distance between regions. This makes proximity matter.
"""

from __future__ import annotations

import random
import string


def apply_noise(content: str, noise_factor: float) -> str:
    """
    Apply noise to a message.

    noise_factor: 0.0 = perfect transmission, 1.0 = complete garbling

    Noise is applied character-by-character:
    - Each character has a (noise_factor) probability of being corrupted
    - Corrupted characters are replaced with random characters
    """
    if noise_factor <= 0.0:
        return content

    if noise_factor >= 1.0:
        return "".join(random.choice(string.printable[:62]) for _ in content)

    result = []
    for char in content:
        if random.random() < noise_factor:
            # Replace with random character
            result.append(random.choice(string.printable[:62]))
        else:
            result.append(char)
    return "".join(result)


def estimate_readability(noise_factor: float) -> str:
    """Human-readable description of noise level."""
    if noise_factor <= 0.0:
        return "crystal clear"
    elif noise_factor <= 0.1:
        return "minor static"
    elif noise_factor <= 0.3:
        return "noticeable interference"
    elif noise_factor <= 0.5:
        return "heavy distortion"
    elif noise_factor <= 0.8:
        return "barely legible"
    else:
        return "complete garbling"
