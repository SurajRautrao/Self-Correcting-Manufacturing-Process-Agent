"""Shared schema building blocks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

#: Version of the JSON data contracts defined in this package.
SCHEMA_VERSION = "1.0"

#: Stable identifier: letters, digits, underscore, hyphen. No free text.
Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and validates on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def find_duplicates(values: Iterable[str]) -> list[str]:
    """Return the sorted list of values that occur more than once."""
    return sorted(v for v, n in Counter(values).items() if n > 1)
