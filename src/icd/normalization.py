from __future__ import annotations

import re
import unicodedata


_TRANSLATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "\u00A0": " ",
    }
)


def canonicalize(value: str | None) -> str:
    """Normalisation lexicale uniquement; aucune inférence clinique."""
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.translate(_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()
