"""Compatibility shim — review/commit live in ``gai.review`` / ``gai.commit``."""

from __future__ import annotations

from gai.commit.cmd import commit_cmd, _confirm_and_commit, _do_commit  # noqa: F401
from gai.review.cmd import review_cmd  # noqa: F401
from gai.review.helpers import (  # noqa: F401
    _SUGGEST_SPLIT_HELP,
    _maybe_suggest_optional_splitflow,
    _offer_splitflow_instead,
    _print_diff_too_large,
)
