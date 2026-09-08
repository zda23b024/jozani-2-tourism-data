import unittest

from database.create_tables import bounded_int_value, bounded_numeric_value
from normalizers.table_builder import build_all_tables


class SourceAwareDatabaseMappingTests(unittest.TestCase):
    def test_bounded_numeric_value_rejects_out_of_range_ratings(self):
        self.assertEqual(bounded_numeric_value("4.75", 0, 10), 4.75)
        self.assertIsNone(bounded_numeric_value("456", 0, 10))
        self.assertIsNone(bounded_numeric_value("-1", 0, 10))

    def test_bounded_int_value_rejects_impossible_review_counts(self):
        self.assertEqual(bounded_int_value("1200", 0, 1_000_000), 1200)
        self.assertIsNone(bounded_int_value("33992043", 0, 1_000_000))

    def test_tripadvisor_review_metadata_maps_to_source_aware_review_rows(self):
        place = {
            "source": "tripadvisor",
            "place_type_id": "hotel",
            "tripadvisor_id": "123",
            "name": "Sample Hotel",
            "property_url": "https://www.tripadvisor.com/Hotel_Review-g123-d123.html",
            "review_score": 4.5,
            "review_count": 99,
            "ranking_position": 3,
            "ranking_total": 50,
            "ranking_text": "#3 of 50 Hotels in Zanzibar",
            "ranking_category": "Hotels in Zanzibar",
        }
        review = {
            "source": "tripadvisor",
            "source_place_id": "123",
            "review_id": "r1",
            "reviewer_id": "u1",
            "reviewer_name": "A Reviewer",
            "reviewer_country": "Tanzania",
            "reviewer_profile_url": "https://www.tripadvisor.com/Profile/u1",
            "review_title": "Great stay",
            "review_text": "Loved the service.",
            "review_score": 5,
            "rating_scale": 5,
            "review_date": "2026-09-01",
            "stayed_date": "2026-08-01",
            "trip_type": "Family",
            "helpful_votes": 7,
            "language": "en",
            "additional_ratings": [{"category_name": "Service", "score": 5, "rating_scale": 5}],
            "response_id": "resp1",
            "response_text": "Thank you.",
            "response_date": "2026-09-02",
        }

        tables = build_all_tables([place], [review], [], include_availability=False)

        source_record = tables["place_source_records"][0]
        self.assertEqual(source_record["ranking_text"], "#3 of 50 Hotels in Zanzibar")
        self.assertEqual(source_record["review_score"], 4.5)

        review_row = tables["reviews"][0]
        self.assertEqual(review_row["place_source_id"], "tripadvisor:listing:123")
        self.assertEqual(review_row["review_text"], "Loved the service.")
        self.assertEqual(review_row["rating_scale"], 5)
        self.assertEqual(review_row["trip_type"], "Family")
        self.assertEqual(review_row["language_code"], "en")
        self.assertEqual(review_row["helpful_votes"], 7)

        self.assertEqual(tables["review_category_scores"][0]["rating_scale"], 5)
        self.assertEqual(tables["review_responses"][0]["source_response_id"], "resp1")

    def test_attraction_and_restaurant_details_are_split_by_place_type(self):
        attraction = {
            "source": "tripadvisor",
            "place_type_id": "museum",
            "tripadvisor_id": "a1",
            "name": "Sample Museum",
            "activity_type": "Museum",
            "price": "12.50",
            "currency": "USD",
            "duration_minutes": "90",
        }
        restaurant = {
            "source": "tripadvisor",
            "place_type_id": "restaurant",
            "tripadvisor_id": "r1",
            "name": "Sample Restaurant",
            "category_labels": "Cafe",
            "price_range": "$$",
        }

        tables = build_all_tables([], [], [attraction, restaurant], include_availability=False)

        self.assertEqual(len(tables["attractions"]), 1)
        self.assertEqual(tables["attractions"][0]["place_source_id"], "tripadvisor:attraction:listing:a1")
        self.assertEqual(tables["attractions"][0]["price_from"], 12.5)
        self.assertEqual(tables["attractions"][0]["duration_minutes"], 90)

        self.assertEqual(len(tables["restaurants"]), 1)
        self.assertEqual(tables["restaurants"][0]["place_source_id"], "tripadvisor:attraction:listing:r1")
        self.assertEqual(tables["restaurants"][0]["price_range"], "$$")


if __name__ == "__main__":
    unittest.main()
