"""Every gate in this package is slow-marked and offline.

The mark is applied here rather than on each test so that adding a gate cannot forget it
and quietly grow the fast suite that gates Tuesday.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.slow)
