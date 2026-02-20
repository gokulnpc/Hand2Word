"""Pytest configuration and shared fixtures"""
import pytest
import os


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Setup test environment variables"""
    os.environ["REDIS_HOST"] = "localhost"
    os.environ["REDIS_PORT"] = "6379"
    os.environ["LOG_LEVEL"] = "DEBUG"
    os.environ["MONGODB_URL"] = ""  
    yield


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires Redis)"
    )

