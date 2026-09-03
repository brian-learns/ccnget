"""Pytest configuration for ccnget tests.

Isolates environment variables that may be set in the developer's
shell, so config resolution tests see a clean environment.
"""

import os
import pytest

# Env vars that ccnget reads from the environment
_CC_ENV_VARS = ("CDX_URL", "CC_CRAWL_BASE_URL")


@pytest.fixture(autouse=True)
def _clean_cc_env():
    """Ensure CC-NEWS env vars are not leaking between tests."""
    saved = {}
    for var in _CC_ENV_VARS:
        if var in os.environ:
            saved[var] = os.environ[var]
            del os.environ[var]

    yield

    # Restore if they were set before the test
    for var, val in saved.items():
        os.environ[var] = val
