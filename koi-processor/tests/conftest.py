"""Shared pytest configuration for KOI-net tests."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live-url",
        default=None,
        help="KOI API base URL for live conformance tests (e.g. http://127.0.0.1:8351)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires a running KOI API instance (--live-url)")


@pytest.fixture
def live_url(request):
    url = request.config.getoption("--live-url")
    if url is None:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")
