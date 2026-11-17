from pathlib import Path

SOURCE_NAME_VERSION = "source-filename-v1"


def source_name(filename: str) -> str:
    """Pass the original filename stem to metadata providers without rewriting it."""
    return Path(filename).stem
