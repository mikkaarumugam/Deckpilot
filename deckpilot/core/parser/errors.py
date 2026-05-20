"""
Shared exception types for the parser package.

ParseError is defined here (not in __init__.py) so both regex.py and llm.py
can import it without creating a circular dependency.
"""

from __future__ import annotations


class ParseError(ValueError):
    """Raised when a command can't be turned into a supported DJAction."""
