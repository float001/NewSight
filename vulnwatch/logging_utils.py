from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LogConfig:
    level: str = "INFO"  # DEBUG/INFO/WARNING/ERROR


def setup_logging(level: str = "INFO") -> None:
    lvl = (level or os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    if lvl not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        lvl = "INFO"
    logging.basicConfig(
        level=getattr(logging, lvl, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

