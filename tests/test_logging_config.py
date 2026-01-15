import logging

from backend.core.logging_config import AccessPathExcludeFilter


def _make_access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %s',
        args=("127.0.0.1", "POST", path, "1.1", 204),
        exc_info=None,
    )


def test_access_log_excludes_configured_paths() -> None:
    access_filter = AccessPathExcludeFilter(["/logs/frontend", "/logs/backend"])

    filtered = access_filter.filter(_make_access_record("/logs/frontend"))
    allowed = access_filter.filter(_make_access_record("/items"))

    assert filtered is False
    assert allowed is True
