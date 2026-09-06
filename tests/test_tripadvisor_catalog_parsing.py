import unittest

from scraper.tripadvisor.scrape_places import normalize_place_card
from scraper.tripadvisor.scrape_reviews import extract_review_page_payload, valid_review_total
from scraper.tripadvisor.scrape_stays import normalize_card, valid_tripadvisor_location_id


class TripadvisorCatalogParsingTests(unittest.TestCase):
    def test_valid_tripadvisor_location_id_requires_digits(self):
        self.assertEqual(valid_tripadvisor_location_id("11925961"), "11925961")
        self.assertIsNone(valid_tripadvisor_location_id("Kuza Cave"))
        self.assertIsNone(valid_tripadvisor_location_id(""))

    def test_hotel_normalizer_rejects_missing_numeric_location_id(self):
        self.assertIsNone(
            normalize_card(
                {
                    "name": "Sample Hotel",
                    "url": "https://www.tripadvisor.com/Hotel_Review-g123-Sample.html",
                }
            )
        )

    def test_hotel_normalizer_accepts_id_from_url(self):
        hotel = normalize_card(
            {
                "name": "Sample Hotel",
                "url": "https://www.tripadvisor.com/Hotel_Review-g482884-d585857-Reviews-Sample.html",
            }
        )
        self.assertIsNotNone(hotel)
        self.assertEqual(hotel["tripadvisor_id"], "585857")

    def test_attraction_normalizer_rejects_missing_numeric_location_id(self):
        self.assertIsNone(
            normalize_place_card(
                {
                    "name": "Sample Attraction",
                    "url": "https://www.tripadvisor.com/Attraction_Review-g123-Sample.html",
                },
                "attractions",
            )
        )

    def test_restaurant_normalizer_accepts_id_from_graphql_card(self):
        restaurant = normalize_place_card(
            {
                "name": "Sample Restaurant",
                "url": "https://www.tripadvisor.com/Restaurant_Review-g482884-d27943321-Reviews-Sample.html",
                "location_id": "27943321",
            },
            "restaurants",
        )
        self.assertIsNotNone(restaurant)
        self.assertEqual(restaurant["restaurant_id"], "27943321")

    def test_attraction_route_json_does_not_become_rating_or_review_count(self):
        attraction = normalize_place_card(
            {
                "name": "Sample Tour",
                "url": "https://www.tripadvisor.com/Attraction_Review-g482884-d20324135-Reviews-Sample_Tour.html",
                "location_id": "20324135",
                "text": '{"detailId": 20324135, "page": "Attraction_Review"}',
            },
            "attractions",
        )

        self.assertIsNotNone(attraction)
        self.assertIsNone(attraction["review_score"])
        self.assertIsNone(attraction["review_count"])

    def test_review_total_missing_stays_unknown(self):
        total_count, reviews = extract_review_page_payload(
            [
                {
                    "data": {
                        "ReviewsProxy_getReviewListPageForLocation": [
                            {"reviews": [{"id": "1"}, {"id": "2"}]}
                        ]
                    }
                }
            ]
        )
        self.assertIsNone(total_count)
        self.assertEqual([review["id"] for review in reviews], ["1", "2"])

    def test_review_total_rejects_internal_unknown_sentinel(self):
        self.assertIsNone(valid_review_total(-1))
        self.assertIsNone(valid_review_total(None))
        self.assertEqual(valid_review_total(0), 0)
        self.assertEqual(valid_review_total(1021), 1021)


if __name__ == "__main__":
    unittest.main()
