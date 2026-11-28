"""Validate byte counts shared by captured and observed storage evidence."""
import math


def byte_count(value, minimum=0):
    """Return an exact, browser-safe count, or None for unusable metadata."""
    if isinstance(value, str):
        value = value.strip()
        if not value or len(value) > 16 or not value.isascii() or not value.isdecimal():
            return None
        value = int(value)
    if type(value) is float:
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    return value if type(value) is int and minimum <= value <= 2**53 - 1 else None
