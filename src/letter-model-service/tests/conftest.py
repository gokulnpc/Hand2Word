"""
Pytest configuration and shared fixtures for letter-model-sevice tests.
"""

import os
import sys
import pytest

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Ensure tracing is disabled during tests
@pytest.fixture(scope="session", autouse=True)
def disable_tracing():
    """Disable tracing for all tests to avoid connection errors."""
    os.environ["ENABLE_TRACING"] = "false"
    yield
    # Cleanup is not needed as the environment variable will be reset after tests
