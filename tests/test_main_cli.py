import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, patch

import main as main_module


class MainCliTests(unittest.TestCase):
    def parse_cli(self, args: list[str]):
        with patch.object(sys, "argv", ["main.py", *args]):
            return main_module.parse_args()

    def test_flag_vocabulary_accepts_supported_commands(self):
        mode_flags = {
            "catalog": "--catalog",
            "reviews": "--reviews",
            "all": "--all",
        }
        for source in ("booking", "tripadvisor", "both"):
            for mode, flag in mode_flags.items():
                args = self.parse_cli([flag, "--source", source])
                self.assertEqual(args.source, source)
                self.assertEqual(main_module.selected_mode(args), mode)

    def test_positional_commands_are_not_main_cli_syntax(self):
        with self.assertRaises(SystemExit):
            self.parse_cli(["booking", "catalog"])

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
                    asyncio.run(main_module.main(mode, source="both"))
                    booking_scraper.assert_awaited_once_with(mode, "all")
                    tripadvisor_scraper.assert_awaited_once_with(mode, "all")


if __name__ == "__main__":
    unittest.main()
