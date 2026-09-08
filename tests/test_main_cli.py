import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main as main_module


class MainCliTests(unittest.TestCase):
    def test_help_vocabulary_accepts_all_nine_commands(self):
        for source in ("booking", "tripadvisor", "all"):
            for mode in ("catalog", "reviews", "all"):
                args = main_module.parse_args([source, mode])
                self.assertEqual(args.source, source)
                self.assertEqual(args.mode, mode)

    def test_legacy_flags_are_not_normal_commands(self):
        with self.assertRaises(SystemExit):
            main_module.parse_args(["--source", "booking"])

    def test_source_dispatch_isolated_for_each_provider(self):
        for mode in ("catalog", "reviews", "all"):
            with self.subTest(source="booking", mode=mode):
                with patch.object(
                    main_module,
                    "scrape_booking_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as booking_scraper, patch.object(
                    main_module,
                    "scrape_tripadvisor_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as tripadvisor_scraper:
                    asyncio.run(main_module.main(mode, source="booking"))
                    booking_scraper.assert_awaited_once_with(mode, "all")
                    tripadvisor_scraper.assert_not_awaited()

            with self.subTest(source="tripadvisor", mode=mode):
                with patch.object(
                    main_module,
                    "scrape_booking_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as booking_scraper, patch.object(
                    main_module,
                    "scrape_tripadvisor_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as tripadvisor_scraper:
                    asyncio.run(main_module.main(mode, source="tripadvisor"))
                    booking_scraper.assert_not_awaited()
                    tripadvisor_scraper.assert_awaited_once_with(mode, "all")

    def test_all_dispatches_both_sources_for_each_mode(self):
        for mode in ("catalog", "reviews", "all"):
            with self.subTest(mode=mode):
                with patch.object(
                    main_module,
                    "scrape_booking_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as booking_scraper, patch.object(
                    main_module,
                    "scrape_tripadvisor_data",
                    new=AsyncMock(return_value=([], [], [])),
                ) as tripadvisor_scraper:
                    asyncio.run(main_module.main(mode, source="all"))
                    booking_scraper.assert_awaited_once_with(mode, "all")
                    tripadvisor_scraper.assert_awaited_once_with(mode, "all")


if __name__ == "__main__":
    unittest.main()
