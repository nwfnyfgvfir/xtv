from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

_CONFIGURED = False


def configure_logging(settings: Settings | None = None) -> None:
    """Configure root/app loggers from Settings (env LOG_LEVEL / DEBUG)."""
    global _CONFIGURED
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    if settings.debug:
        level_name = "DEBUG"
    else:
        level_name = (settings.log_level or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
        level_name = "INFO"

    root = logging.getLogger()
    # Reconfigure when called again (tests / reload)
    if root.handlers:
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        root.setLevel(level)

    # Keep third-party noise down unless we are debugging
    noisy_level = logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    for name in ("httpx", "httpcore", "watchdog", "apscheduler", "urllib3"):
        logging.getLogger(name).setLevel(noisy_level)

    logging.getLogger("app").setLevel(level)
    _CONFIGURED = True
    logging.getLogger(__name__).debug("Logging configured level=%s", level_name)
