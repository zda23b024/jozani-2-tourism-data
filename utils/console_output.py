from __future__ import annotations

from typing import Any


LINE = "=" * 60
SUBLINE = "-" * 60


def print_category_header(platform: str, category: str) -> None:
    print()
    print(LINE)
    print(f"{platform.upper()} - {category.upper()}")
    print(LINE)
    print(f"Collecting {category.lower()}...")
    print()


def print_catalog_page(
    page_number: int,
    received: int,
    new: int,
    total_unique: int,
    offset: int | None = None,
    suffix: str = "",
) -> None:
    if offset is None:
        print(
            f"Page {page_number:>3} | received {received:>2} | "
            f"new {new:>2} | total unique {total_unique}{suffix}"
        )
        return
    print(
        f"Page {page_number:>3} | offset {offset:>5} | "
        f"received {received:>2} | new {new:>2} | "
        f"total unique {total_unique}{suffix}"
    )


def print_catalog_complete(category: str, count: int) -> None:
    print(f"OK {category.title()} collected: {count}")


def print_review_header(category: str) -> None:
    print()
    print(SUBLINE)
    print(f"COLLECTING {category.upper()} REVIEWS")
    print(SUBLINE)
    print()


def print_review_progress(
    index: int,
    total: int,
    name: Any,
    collected: int | None,
    reported: int | None = None,
    failed: bool = False,
) -> None:
    label = str(name or "Unknown").strip() or "Unknown"
    print(f"[{index}/{total}] {label}")
    if failed:
        print("         Reviews: FAILED")
        print()
        return
    if reported is None or not isinstance(reported, int) or reported < 0:
        print(f"         Reviews: {collected or 0}/? UNKNOWN")
        return
    status = "OK" if (collected or 0) == reported else "WARN"
    print(f"         Reviews: {collected or 0}/{reported} {status}")
    print()


def print_category_summary(
    platform: str,
    category: str,
    collected: int,
    reviews_collected: int | None = None,
) -> None:
    print()
    print(LINE)
    print(f"OK {platform.upper()} {category.upper()} COMPLETE")
    print(f"{category.title()} collected: {collected}")
    if reviews_collected is not None:
        print(f"Reviews collected: {reviews_collected}")
    print(LINE)


def print_platform_summary(
    platform: str,
    hotels: int = 0,
    attractions: int = 0,
    restaurants: int | None = None,
    reviews: int = 0,
) -> None:
    print()
    print(LINE)
    print(f"OK {platform.upper()} COMPLETE")
    print(LINE)
    print(f"Hotels      : {hotels}")
    print(f"Attractions : {attractions}")
    if restaurants is not None:
        print(f"Restaurants : {restaurants}")
    print(f"Reviews     : {reviews}")
    print(LINE)


def print_overall_summary(
    tripadvisor: dict[str, int],
    booking: dict[str, int],
) -> None:
    print()
    print(LINE)
    print("OK ALL COLLECTION COMPLETE")
    print(LINE)
    print()
    print("TRIPADVISOR")
    print(f"Hotels      : {tripadvisor.get('hotels', 0)}")
    print(f"Attractions : {tripadvisor.get('attractions', 0)}")
    print(f"Restaurants : {tripadvisor.get('restaurants', 0)}")
    print(f"Reviews     : {tripadvisor.get('reviews', 0)}")
    print()
    print("BOOKING.COM")
    print(f"Hotels      : {booking.get('hotels', 0)}")
    print(f"Attractions : {booking.get('attractions', 0)}")
    print(f"Reviews     : {booking.get('reviews', 0)}")
    print()
    print(SUBLINE)
    print("TOTAL")
    places = (
        tripadvisor.get("hotels", 0)
        + tripadvisor.get("attractions", 0)
        + tripadvisor.get("restaurants", 0)
        + booking.get("hotels", 0)
        + booking.get("attractions", 0)
    )
    reviews = tripadvisor.get("reviews", 0) + booking.get("reviews", 0)
    print(f"Places      : {places}")
    print(f"Reviews     : {reviews}")
    print(LINE)
