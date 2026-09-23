"""CLI help i18n helpers.

Help strings are resolved at import/decoration time from sys.argv,
so `gai commit -h --cn` shows Chinese option help for that invocation.
"""

from __future__ import annotations

import sys


def help_cn() -> bool:
    return "--cn" in sys.argv


def H(en: str, cn: str) -> str:
    """Pick English or Simplified Chinese help text for the current argv."""
    return cn if help_cn() else en
