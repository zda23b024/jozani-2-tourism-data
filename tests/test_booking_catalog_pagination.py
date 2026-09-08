import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scraper.booking import scrape_stays


class BookingCatalogPaginationTests(unittest.TestCase):
    def test_short_page_continues_when_api_total_is_larger(self):
        page_batches = [
            [
                {"hotel_id": f"hotel-{page * 25 + index}", "name": "Hotel"}
                for index in range(25)
            ]
            for page in range(15)
        ]
        page_batches.append(
            [
                {"hotel_id": f"hotel-{375 + index}", "name": "Hotel"}
                for index in range(24)
            ]
        )
        page_batches.append(
            [
                {"hotel_id": f"hotel-{399 + index}", "name": "Hotel"}
                for index in range(25)
            ]
        )
        page_batches.append([])

        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        context = SimpleNamespace(pages=[page])
        captured_request = SimpleNamespace(url="https://booking.test/graphql")
        payloads = [object() for _ in page_batches]

        async def fake_fetch(*args, **kwargs):
            return payloads.pop(0)

        with patch.object(
            scrape_stays,
            "wait_for_initial_request",
            new=AsyncMock(return_value=captured_request),
        ), patch.object(
            scrape_stays,
            "parse_request_body",
            return_value={"variables": {"input": {}}},
        ), patch.object(
            scrape_stays,
            "build_fetch_headers",
            new=AsyncMock(return_value={}),
        ), patch.object(
            scrape_stays,
            "fetch_graphql_page",
            new=AsyncMock(side_effect=fake_fetch),
        ) as fetch_page, patch.object(
            scrape_stays,
            "extract_total_results",
            return_value=1424,
        ), patch.object(
            scrape_stays,
            "extract_results",
            side_effect=page_batches,
        ), patch.object(
            scrape_stays,
            "enrich_hotels_with_detail_pages",
            new=AsyncMock(side_effect=lambda _context, hotels: hotels),
        ):
            hotels = asyncio.run(
                scrape_stays.scrape_hotels_in_context(context, catalog_mode=True)
            )

        offsets = [
            call.kwargs["body"]["variables"]["input"]["pagination"]["offset"]
            for call in fetch_page.await_args_list
        ]
        self.assertIn(375, offsets)
        self.assertIn(400, offsets)
        self.assertEqual(offsets[-1], 425)
        self.assertEqual(len(hotels), 424)


if __name__ == "__main__":
    unittest.main()
