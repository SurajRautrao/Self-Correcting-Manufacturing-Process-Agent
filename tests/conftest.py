"""Shared pytest fixtures: raw example data that tests can copy and corrupt."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from scmpa.io import DEFAULT_CATALOGUE_PATH, EXAMPLE_COMPONENTS_DIR, REFERENCE_PLANS_DIR, load_catalogue, read_json
from scmpa.schemas import Catalogue


@pytest.fixture(scope="session")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture
def catalogue_data() -> dict[str, Any]:
    return copy.deepcopy(read_json(DEFAULT_CATALOGUE_PATH))


@pytest.fixture
def bracket_data() -> dict[str, Any]:
    """Fresh, mutable copy of the demo bracket component."""
    return copy.deepcopy(read_json(EXAMPLE_COMPONENTS_DIR / "demo_bracket_001.json"))


@pytest.fixture
def plate_data() -> dict[str, Any]:
    return copy.deepcopy(read_json(EXAMPLE_COMPONENTS_DIR / "demo_plate_002.json"))


@pytest.fixture
def bracket_plan_data() -> dict[str, Any]:
    return copy.deepcopy(read_json(REFERENCE_PLANS_DIR / "demo_bracket_001_ref.json"))
