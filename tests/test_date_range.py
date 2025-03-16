import unittest
import datetime
from app import app

class DateRangeTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_date_range_persistence_with_params(self):
        # Provide date range parameters
        start_date = "2023-09-01"
        end_date = "2023-09-10"
        response = self.app.get("/", query_string={"start_date": start_date, "end_date": end_date})
        self.assertEqual(response.status_code, 200)
        # Check that the rendered template contains the provided dates
        response_text = response.get_data(as_text=True)
        self.assertIn(start_date, response_text)
        self.assertIn(end_date, response_text)
        
    def test_date_range_default(self):
        # Call without date range parameters, should use default last 10 days
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        today = datetime.date.today()
        ten_days_ago = today - datetime.timedelta(days=10)
        default_start = ten_days_ago.strftime("%Y-%m-%d")
        default_end = today.strftime("%Y-%m-%d")
        response_text = response.get_data(as_text=True)
        self.assertIn(default_start, response_text)
        self.assertIn(default_end, response_text)

if __name__ == '__main__':
    unittest.main() 