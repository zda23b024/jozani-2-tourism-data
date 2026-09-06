import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.configuration import (
    OUTPUT_DIR,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_ATTRACTIONS_URL,
    TRIPADVISOR_BROWSER_PROFILE_DIR,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context


GRAPHQL_URL = "https://www.tripadvisor.com/data/graphql/ids"
DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "attraction_pagination_capture"


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            lower = str(key).lower()
            if lower in {
                "authorization",
                "cookie",
                "csrf",
                "datadome",
                "sessionid",
                "pageviewuid",
                "pageviewid",
            }:
                result[key] = "<redacted>"
            else:
                result[key] = sanitize(child)
        return result
    if isinstance(value, list):
        return [sanitize(child) for child in value]
    return value


def operation_from_body(body: Any) -> dict[str, Any] | None:
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                query_id = item.get("extensions", {}).get("preRegisteredQueryId")
                if query_id == TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID:
                    return item
    if isinstance(body, dict):
        query_id = body.get("extensions", {}).get("preRegisteredQueryId")
        if query_id == TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID:
            return body
    return None


def request_json(request) -> Any:
    try:
        body = request.post_data_json
        if callable(body):
            body = body()
        return body
    except Exception:
        post_data = request.post_data or ""
        try:
            return json.loads(post_data)
        except Exception:
            return None


def variables_signature(operation: dict[str, Any]) -> str:
    return json.dumps(
        sanitize(operation.get("variables") or {}),
        sort_keys=True,
        ensure_ascii=False,
    )


def dotted_changes(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            changes.extend(
                dotted_changes(
                    left.get(key),
                    right.get(key),
                    f"{path}.{key}" if path else str(key),
                )
            )
        return changes
    if isinstance(left, list) and isinstance(right, list):
        max_len = max(len(left), len(right))
        for index in range(max_len):
            changes.extend(
                dotted_changes(
                    left[index] if index < len(left) else None,
                    right[index] if index < len(right) else None,
                    f"{path}[{index}]",
                )
            )
        return changes
    if left != right:
        changes.append({"path": path or "$", "first": left, "second": right})
    return changes


def find_pagination_values(value: Any, path: str = "") -> list[dict[str, Any]]:
    names = [
        "updateToken",
        "token",
        "cursor",
        "next",
        "pagination",
        "pageInfo",
        "page",
        "offset",
        "loadMore",
        "continuation",
        "continuationToken",
        "nextPage",
        "nextToken",
        "start",
        "end",
        "hasNext",
        "webRoute",
        "routeParameters",
    ]
    lowered = [name.lower() for name in names]
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if any(marker in str(key).lower() for marker in lowered):
                found.append({"path": child_path, "value": sanitize(child)})
            found.extend(find_pagination_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_pagination_values(child, f"{path}[{index}]"))
    return found


def attraction_card_count(payload: Any) -> tuple[int | None, int]:
    try:
        result = payload[0]["data"]["Result"][0]
        total = result.get("totalResults")
        sections = result.get("sections") or []
    except (KeyError, TypeError, IndexError):
        return None, 0
    cards = [
        section
        for section in sections
        if isinstance(section, dict)
        and section.get("singleFlexCardContent")
        and (
            section.get("singleFlexCardContent", {})
            .get("cardLink", {})
            .get("webRoute", {})
            .get("page")
            == "Attraction_Review"
        )
    ]
    return total, len(cards)


async def clickable_candidates(page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => [...document.querySelectorAll('a, button')]
            .map((node, index) => ({
                index,
                text: (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim(),
                aria: node.getAttribute('aria-label') || '',
                href: node.href || ''
            }))
            .filter((item) => /next|show more|more|load/i.test(`${item.text} ${item.aria} ${item.href}`))
            .slice(0, 50)
        """
    )


async def next_page_candidates(page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => [...document.querySelectorAll('a, button')]
            .map((node, index) => ({
                index,
                text: (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim(),
                aria: node.getAttribute('aria-label') || '',
                href: node.href || ''
            }))
            .filter((item) => /next page/i.test(`${item.text} ${item.aria}`) || /oa30/i.test(item.href))
            .slice(0, 20)
        """
    )


def is_next_page_candidate(candidate: dict[str, Any]) -> bool:
    text = str(candidate.get("text") or "").strip().lower()
    aria = str(candidate.get("aria") or "").strip().lower()
    href = str(candidate.get("href") or "").strip().lower()
    label = f"{text} {aria} {href}"
    if "next photo" in label or "read more" in label or "show more" in label:
        return False
    return "next page" in label or "oa30" in href


async def click_candidate(page, candidate: dict[str, Any]) -> bool:
    return await page.evaluate(
        """
        ({index}) => {
            const nodes = [...document.querySelectorAll('a, button')];
            const node = nodes[index];
            if (!node) return false;
            node.scrollIntoView({block: 'center'});
            node.click();
            return true;
        }
        """,
        candidate,
    )


async def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    captures: list[dict[str, Any]] = []
    signatures: set[str] = set()
    attempted: list[str] = []
    observed_graphql: list[dict[str, Any]] = []

    context = await launch_context(TRIPADVISOR_BROWSER_PROFILE_DIR, "Tripadvisor")
    page = context.pages[0] if context.pages else await context.new_page()

    async def record_response(response) -> None:
        if response.url.split("?")[0] != GRAPHQL_URL:
            return
        request = response.request
        if request.method.upper() != "POST":
            return
        body = request_json(request)
        observed_operations = []
        if isinstance(body, list):
            observed_operations = [
                item.get("extensions", {}).get("preRegisteredQueryId")
                for item in body
                if isinstance(item, dict)
            ]
        elif isinstance(body, dict):
            observed_operations = [body.get("extensions", {}).get("preRegisteredQueryId")]
        observed_graphql.append(
            {
                "url": response.url,
                "method": request.method,
                "status": response.status,
                "preRegisteredQueryIds": observed_operations,
                "body_shape": "list" if isinstance(body, list) else type(body).__name__,
            }
        )
        (DEBUG_DIR / "observed_graphql_ids.json").write_text(
            json.dumps(observed_graphql, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        operation = operation_from_body(body)
        if not operation:
            return
        signature = variables_signature(operation)
        if signature in signatures:
            return
        signatures.add(signature)
        try:
            payload = await response.json()
        except Exception:
            payload = None
        total, card_count = attraction_card_count(payload)
        capture = {
            "index": len(captures) + 1,
            "url": response.url,
            "method": request.method,
            "status": response.status,
            "preRegisteredQueryId": operation.get("extensions", {}).get("preRegisteredQueryId"),
            "variables": sanitize(operation.get("variables") or {}),
            "routeParameters": sanitize(
                operation.get("variables", {})
                .get("request", {})
                .get("routeParameters")
            ),
            "updateToken": sanitize(
                operation.get("variables", {}).get("request", {}).get("updateToken")
            ),
            "pagination_related_values": find_pagination_values(
                operation.get("variables") or {}
            ),
            "api_total": total,
            "attraction_cards": card_count,
        }
        captures.append(capture)
        (DEBUG_DIR / f"request_{capture['index']}.json").write_text(
            json.dumps(capture, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            "Captured AttractionsFusion request "
            f"{capture['index']}: status={capture['status']} "
            f"cards={capture['attraction_cards']} total={capture['api_total']}",
            flush=True,
        )

    page.on("response", lambda response: asyncio.create_task(record_response(response)))

    try:
        await page.goto(TRIPADVISOR_ATTRACTIONS_URL, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        attempted.append("Opened Zanzibar attractions page and waited for initial AttractionsFusion request.")
        print("Opened Zanzibar attractions page.", flush=True)
        await page.wait_for_timeout(12_000)

        for scroll_round in range(1, 7):
            if len(captures) >= 2:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            attempted.append(f"Scrolled to page bottom, round {scroll_round}.")
            await page.wait_for_timeout(4_000)

        candidates = await clickable_candidates(page)
        next_candidates = await next_page_candidates(page)
        (DEBUG_DIR / "clickable_candidates.json").write_text(
            json.dumps(candidates, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (DEBUG_DIR / "next_page_candidates.json").write_text(
            json.dumps(next_candidates, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ordered_candidates = [
            *next_candidates,
            *[candidate for candidate in candidates if is_next_page_candidate(candidate)],
            *[candidate for candidate in candidates if not is_next_page_candidate(candidate)],
        ]
        for candidate in ordered_candidates:
            if len(captures) >= 2:
                break
            attempted.append(
                "Clicked candidate: "
                f"text={candidate.get('text')!r} aria={candidate.get('aria')!r} href={candidate.get('href')!r}"
            )
            clicked = await click_candidate(page, candidate)
            if clicked:
                await page.wait_for_timeout(8_000)

        page_snapshot = {
            "url": page.url,
            "title": await page.title(),
            "body_text_start": (
                await page.locator("body").inner_text(timeout=5_000)
            )[:2000],
            "observed_graphql": observed_graphql,
        }
        (DEBUG_DIR / "page_snapshot.json").write_text(
            json.dumps(page_snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        await page.screenshot(path=str(DEBUG_DIR / "page_snapshot.png"), full_page=True)

        summary = {
            "attempted": attempted,
            "captures": captures,
            "observed_graphql": observed_graphql,
            "page_snapshot": page_snapshot,
        }
        if len(captures) >= 2:
            first = deepcopy(captures[0])
            second = deepcopy(captures[1])
            changes = dotted_changes(first["variables"], second["variables"])
            summary["changed_variable_fields"] = changes
            (DEBUG_DIR / "comparison.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print("=" * 60)
            print("TRIPADVISOR ATTRACTION PAGINATION CAPTURED")
            print("=" * 60)
            print(f"Query ID        : {first['preRegisteredQueryId']}")
            print(f"First batch     : {first['attraction_cards']} attractions")
            print(f"API total       : {first['api_total']}")
            print()
            print("Changed pagination fields:")
            for change in changes:
                path = change["path"]
                if any(
                    marker in path.lower()
                    for marker in ["token", "cursor", "page", "offset", "start", "end", "next", "routeparameters"]
                ):
                    print(f"{path} : {change['first']} -> {change['second']}")
            mechanism = ", ".join(
                change["path"]
                for change in changes
                if any(
                    marker in change["path"].lower()
                    for marker in ["token", "cursor", "page", "offset", "start", "end", "next", "routeparameters"]
                )
            )
            print()
            print(f"Pagination mechanism: {mechanism or 'changed fields captured; inspect comparison.json'}")
            print("=" * 60)
        else:
            (DEBUG_DIR / "no_second_request.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print("No second AttractionsFusion request captured.")
            print("Interactions attempted:")
            for item in attempted:
                print(f"- {item}")
            print(f"Captured requests: {len(captures)}")
            print(f"Debug directory: {DEBUG_DIR}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
