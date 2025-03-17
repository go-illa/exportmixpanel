import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import app  # Import the app module rather than the Flask instance


class TestLackOfAccuracy(unittest.TestCase):
    def sample_response(self):
        return {
            "data": {
                "attributes": {
                    "manualDistance": "100",
                    "calculatedDistance": "120",
                    "pickupTime": "2025-03-17T23:00:00.000Z",
                    "tagsCount": [{"tag_name": "lack_of_accuracy", "count": "1"}]
                }
            }
        }

    def test_lack_of_accuracy_extraction(self):
        original_fetch = app.fetch_trip_from_api

        def fake_fetch_trip_from_api(trip_id, token=app.API_TOKEN):
            return self.sample_response()

        app.fetch_trip_from_api = fake_fetch_trip_from_api
        trip = app.update_trip_db(123, force_update=True)
        self.assertTrue(trip.lack_of_accuracy)
        app.fetch_trip_from_api = original_fetch


if __name__ == '__main__':
    unittest.main() 