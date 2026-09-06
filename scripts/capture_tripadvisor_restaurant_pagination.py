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
    TRIPADVISOR_FIND_RESTAURANTS_URL,
    TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_BROWSER_PROFILE_DIR,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context


GRAPHQL_URL = "https://www.tripadvisor.com/data/graphql/ids"
DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "restaurant_pagination_capture"


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


def operation_from_body(body: Any) -> dict[str, Any] | None:
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                query_id = item.get("extensions", {}).get("preRegisteredQueryId")
                if query_id == TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID:
                    return item
    if isinstance(body, dict):
        query_id = body.get("extensions", {}).get("preRegisteredQueryId")
        if query_id == TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID:
            return body
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
        "offset",
        "page",
        "token",
        "cursor",
        "next",
        "pagination",
        "route",
        "params",
        "geo",
        "hasNext",
        "start",
        "end",
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


def count_restaurant_markers(value: Any) -> int:
    if isinstance(value, dict):
        marker_count = 0
        if "/Restaurant_Review-" in json.dumps(value, ensure_ascii=False):
            marker_count += 1
        for child in value.values():
            marker_count += count_restaurant_markers(child)
        return marker_count
    if isinstance(value, list):
        return sum(count_restaurant_markers(child) for child in value)
    return 0


async def candidates(page) -> list[dict[str, Any]]:
    try:
        return await page.evaluate(
            """
            () => [...document.querySelectorAll('a, button')]
                .map((node, index) => ({
                    index,
                    text: (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim(),
                    aria: node.getAttribute('aria-label') || '',
                    href: node.href || ''
                }))
                .filter((item) => /next|page|more|oa30|o30|offset/i.test(`${item.text} ${item.aria} ${item.href}`))
                .slice(0, 80)
            """
        )
    except Exception as error:
        print(f"Could not inspect clickable candidates during navigation: {error}")
        return []


def preferred_candidate(candidate: dict[str, Any]) -> bool:
    text = str(candidate.get("text") or "").lower()
    aria = str(candidate.get("aria") or "").lower()
    href = str(candidate.get("href") or "").lower()
    label = f"{text} {aria} {href}"
    if "next photo" in label or "read more" in label or "show more" in label:
        return False
    return "next page" in label or "oa30" in label or "offset=30" in label


async def click_candidate(page, candidate: dict[str, Any]) -> bool:
    try:
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
    except Exception as error:
        print(f"Could not click candidate during navigation: {error}")
        return False


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
        observed_ids = []
        if isinstance(body, list):
            observed_ids = [
                item.get("extensions", {}).get("preRegisteredQueryId")
                for item in body
                if isinstance(item, dict)
            ]
        elif isinstance(body, dict):
            observed_ids = [body.get("extensions", {}).get("preRegisteredQueryId")]
        observed_graphql.append(
            {
                "url": response.url,
                "method": request.method,
                "status": response.status,
                "preRegisteredQueryIds": observed_ids,
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
        capture = {
            "index": len(captures) + 1,
            "url": response.url,
            "method": request.method,
            "status": response.status,
            "preRegisteredQueryId": operation.get("extensions", {}).get("preRegisteredQueryId"),
            "variables": sanitize(operation.get("variables") or {}),
            "route": sanitize((operation.get("variables") or {}).get("route")),
            "routeParameters": sanitize(
                ((operation.get("variables") or {}).get("route") or {}).get("params")
            ),
            "pagination_related_values": find_pagination_values(
                operation.get("variables") or {}
            ),
            "restaurant_marker_count": count_restaurant_markers(payload),
        }
        captures.append(capture)
        (DEBUG_DIR / f"request_{capture['index']}.json").write_text(
            json.dumps(capture, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            "Captured restaurant query "
            f"{capture['index']}: status={capture['status']} "
            f"markers={capture['restaurant_marker_count']}",
            flush=True,
        )

    page.on("response", lambda response: asyncio.create_task(record_response(response)))

    try:
        await page.goto(TRIPADVISOR_FIND_RESTAURANTS_URL, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        attempted.append("Opened Zanzibar FindRestaurants page and waited for initial restaurant request.")
        print("Opened Zanzibar restaurants page.", flush=True)
        await page.wait_for_timeout(12_000)

        for scroll_round in range(1, 7):
            if len(captures) >= 2:
                break
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as error:
                attempted.append(f"Scroll round {scroll_round} interrupted by navigation: {error}")
                await page.wait_for_timeout(3_000)
                continue
            attempted.append(f"Scrolled to page bottom, round {scroll_round}.")
            await page.wait_for_timeout(4_000)

        clickable = await candidates(page)
        (DEBUG_DIR / "clickable_candidates.json").write_text(
            json.dumps(clickable, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ordered = [
            *[candidate for candidate in clickable if preferred_candidate(candidate)],
            *[candidate for candidate in clickable if not preferred_candidate(candidate)],
        ]
        for candidate in ordered:
            if len(captures) >= 2:
                break
            attempted.append(
                "Clicked candidate: "
                f"text={candidate.get('text')!r} aria={candidate.get('aria')!r} href={candidate.get('href')!r}"
            )
            if await click_candidate(page, candidate):
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8_000)
                except Exception:
                    pass
                await page.wait_for_timeout(4_000)

        try:
            title = await page.title()
        except Exception as error:
            title = f"<unavailable: {error}>"
        try:
            body_text = await page.locator("body").inner_text(timeout=5_000)
        except Exception as error:
            body_text = f"<unavailable: {error}>"
        page_snapshot = {
            "url": page.url,
            "title": title,
            "body_text_start": body_text[:2000],
            "observed_graphql": observed_graphql,
        }
        (DEBUG_DIR / "page_snapshot.json").write_text(
            json.dumps(page_snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            await page.screenshot(path=str(DEBUG_DIR / "page_snapshot.png"), full_page=True)
        except Exception as error:
            attempted.append(f"Screenshot failed: {error}")

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
            print("TRIPADVISOR RESTAURANT PAGINATION CAPTURED")
            print("=" * 60)
            print(f"Query ID        : {first['preRegisteredQueryId']}")
            print(f"First batch     : {first['restaurant_marker_count']} restaurant markers")
            print()
            print("Changed pagination fields:")
            relevant = [
                change
                for change in changes
                if any(
                    marker in change["path"].lower()
                    for marker in ["token", "cursor", "page", "offset", "start", "end", "next", "route", "params"]
                )
            ]
            for change in relevant:
                print(f"{change['path']} : {change['first']} -> {change['second']}")
            mechanism = ", ".join(change["path"] for change in relevant)
            print()
            print(f"Pagination mechanism: {mechanism or 'changed fields captured; inspect comparison.json'}")
            print("=" * 60)
        else:
            (DEBUG_DIR / "no_second_request.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print("No second restaurant GraphQL request captured.")
            print("Interactions attempted:")
            for item in attempted:
                print(f"- {item}")
            print(f"Captured requests: {len(captures)}")
            print(f"Debug directory: {DEBUG_DIR}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
