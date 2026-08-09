"""Pytest configuration for ccnget tests.

Resets environment variables that may have been set by load_dotenv()
when main() is invoked during earlier tests.
"""

import os
import pytest

# Env vars that load_dotenv() may set from the project .env file
_CC_ENV_VARS = ("CDX_LOOKUP_URL", "CC_CRAWL_BASE_URL")


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
