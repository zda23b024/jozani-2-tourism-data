"""Booking.com parsing helpers.

Keep platform-specific extraction helpers here as the Booking scraper is
gradually moved out of the legacy top-level scraper files.
"""

from typing import Any


def parse_booking_record(raw_record: dict[str, Any]) -> dict[str, Any]:
    """Return a Booking.com record unchanged until deeper parser migration."""
    return raw_record

