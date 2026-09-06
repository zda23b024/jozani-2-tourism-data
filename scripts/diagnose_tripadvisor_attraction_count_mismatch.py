import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.configuration import OUTPUT_DIR


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "attraction_pagination"


def page_number(path: Path) -> int:
    match = re.search(r"page_(\d+)\.json$", path.name)
    return int(match.group(1)) if match else 0


def card_key(section: dict[str, Any]) -> tuple[str | None, str | None]:
    return (
        str(section.get("extracted_location_id") or "").strip() or None,
        str(section.get("attraction_url") or "").strip() or None,
    )


def normalized_card_key(card: dict[str, Any]) -> tuple[str | None, str | None]:
    return (
        str(
            card.get("tripadvisor_id")
            or card.get("source_place_id")
            or card.get("location_id")
            or ""
        ).strip()
        or None,
        str(card.get("property_url") or card.get("source_url") or card.get("url") or "").strip()
        or None,
    )


def main() -> None:
    paths = sorted(DEBUG_DIR.glob("page_*.json"), key=page_number)
    if not paths:
        raise SystemExit(f"No attraction pagination debug files found in {DEBUG_DIR}")

    api_total = None
    raw_cards = 0
    accepted = 0
    duplicate_location = 0
    duplicate_url = 0
    missing_identity = 0
    seen_locations: set[str] = set()
    seen_urls: set[str] = set()
    location_counter: Counter[str] = Counter()
    url_counter: Counter[str] = Counter()
    duplicate_pages: dict[str, list[int]] = defaultdict(list)
    page_rows = []

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        page = int(data.get("page_number") or page_number(path))
        if api_total is None:
            api_total = data.get("api_reported_total_results")
        normalized_cards = data.get("normalized_cards")
        use_normalized_cards = isinstance(normalized_cards, list)
        sections = []
        if not use_normalized_cards:
            sections = [
                section
                for section in data.get("sections", [])
                if section.get("has_singleFlexCardContent")
                and section.get("cardLink_webRoute_page") == "Attraction_Review"
            ]
        page_raw = len(sections)
        if use_normalized_cards:
            page_raw = int(data.get("attraction_card_sections") or len(normalized_cards))
        page_new = 0
        page_dup_location = 0
        page_dup_url = 0
        page_missing = 0

        card_items = normalized_cards if use_normalized_cards else sections
        for item in card_items:
            location_id, url = (
                normalized_card_key(item)
                if use_normalized_cards
                else card_key(item)
            )
            if not location_id or not url:
                missing_identity += 1
                page_missing += 1
                continue
            location_counter[location_id] += 1
            url_counter[url] += 1
            duplicate_pages[location_id].append(page)
            if url in seen_urls:
                duplicate_url += 1
                page_dup_url += 1
                continue
            if location_id in seen_locations:
                duplicate_location += 1
                page_dup_location += 1
                continue
            seen_urls.add(url)
            seen_locations.add(location_id)
            accepted += 1
            page_new += 1

        raw_cards += page_raw
        page_rows.append(
            {
                "page": page,
                "raw": page_raw,
                "new": page_new,
                "dup_location": page_dup_location,
                "dup_url": page_dup_url,
                "missing": page_missing,
            }
        )

    duplicate_locations = {
        location_id: count
        for location_id, count in location_counter.items()
        if count > 1
    }
    duplicate_urls = {url: count for url, count in url_counter.items() if count > 1}

    summary = {
        "debug_pages": len(paths),
        "api_reported_total": api_total,
        "raw_attraction_cards": raw_cards,
        "unique_after_scraper_dedupe": accepted,
        "gap_api_total_minus_unique": (int(api_total) - accepted) if api_total is not None else None,
        "dropped_before_normalized_cards": raw_cards
        - accepted
        - duplicate_location
        - duplicate_url
        - missing_identity,
        "dropped_duplicate_location": duplicate_location,
        "dropped_duplicate_url": duplicate_url,
        "dropped_missing_identity": missing_identity,
        "duplicate_location_ids": len(duplicate_locations),
        "duplicate_urls": len(duplicate_urls),
        "top_duplicate_location_ids": [
            {
                "location_id": location_id,
                "appearances": count,
                "pages": duplicate_pages[location_id][:20],
            }
            for location_id, count in location_counter.most_common(20)
            if count > 1
        ],
        "pages_with_drops": [
            row
            for row in page_rows
            if row["dup_location"] or row["dup_url"] or row["missing"]
        ][:30],
    }

    out_path = DEBUG_DIR / "count_mismatch_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Tripadvisor attraction count mismatch diagnostic")
    print(f"Debug pages                 : {summary['debug_pages']}")
    print(f"API reported total          : {summary['api_reported_total']}")
    print(f"Raw attraction cards        : {summary['raw_attraction_cards']}")
    print(f"Unique after scraper dedupe : {summary['unique_after_scraper_dedupe']}")
    print(f"Gap                         : {summary['gap_api_total_minus_unique']}")
    print(f"Dropped before normalized   : {summary['dropped_before_normalized_cards']}")
    print(f"Dropped duplicate URL       : {summary['dropped_duplicate_url']}")
    print(f"Dropped duplicate location  : {summary['dropped_duplicate_location']}")
    print(f"Dropped missing identity    : {summary['dropped_missing_identity']}")
    print(f"Duplicate location IDs      : {summary['duplicate_location_ids']}")
    print(f"Duplicate URLs              : {summary['duplicate_urls']}")
    print(f"Debug file                  : {out_path}")


if __name__ == "__main__":
    main()
