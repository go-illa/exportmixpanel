import unittest
import sys
import os
from unittest.mock import patch

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

# Dummy trip object for testing
class DummyTrip:
    def __init__(self, trip_id, manual_distance, calculated_distance, route_quality, status=None):
        self.trip_id = trip_id
        self.manual_distance = manual_distance
        self.calculated_distance = calculated_distance
        self.route_quality = route_quality
        self.status = status

# Dummy implementations for functions used in app endpoints
def dummy_update_trip_db(trip_id):
    # Return a dummy trip for testing
    return DummyTrip(trip_id, 100.0, 105.0, "High")

def dummy_fetch_trip_from_api(trip_id):
    return {"data": {"attributes": {"dummy_attr": "value"}}}


def dummy_load_excel_data(excel_path):
    # Return a list with one dummy row
    return [{
        "tripId": 1,
        "UserName": "TestDriver",
        "carrier": "vodafone",
        "model": "TestModel",
        "RAM": "4GB",
        "time": "2020-01-01 00:00:00",
        "route_quality": "High"
    }]


class AppTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

        # Override global functions in the app module using the module object
        self.app_module = sys.modules['app']
        self.app_module.update_trip_db = dummy_update_trip_db
        self.app_module.fetch_trip_from_api = dummy_fetch_trip_from_api
        self.app_module.load_excel_data = dummy_load_excel_data

    def test_home(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        # Check for 'Dashboard' text in the analytics page
        self.assertIn(b'Dashboard', response.data)

    def test_trips_page(self):
        response = self.client.get('/trips')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Trips Table', response.data)
    
    def test_trip_insights(self):
        response = self.client.get('/trip_insights')
        self.assertEqual(response.status_code, 200)
        # Check for expected quality label, such as 'High'
        self.assertIn(b'High', response.data)

    def test_export_trips(self):
        # Test export trips endpoint with query parameter export_name
        response = self.client.get('/export_trips?export_name=test_export')
        self.assertEqual(response.status_code, 200)
        # Check that the response mimetype is for Excel xlsx
        expected_mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        self.assertEqual(response.mimetype, expected_mimetype)

    def test_save_filter(self):
        data = {
            'filter_name': 'test_filter',
            'trip_id': '123',
            'route_quality': 'High',
            'model': 'TestModel',
            'ram': '4GB',
            'carrier': 'Vodafone',
            'variance_min': '10',
            'variance_max': '20',
            'driver': 'TestDriver'
        }
        response = self.client.post('/save_filter', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # Check that a success message containing 'saved' appears
        self.assertIn(b'saved', response.data.lower())

    def test_trip_detail(self):
        response = self.client.get('/trip/1')
        self.assertEqual(response.status_code, 200)
        # Check that the rendered page contains 'Distance Verification:' and does not show 'N/A'
        self.assertIn(b'Distance Verification:', response.data)
        self.assertNotIn(b'Distance Verification: N/A', response.data)


if __name__ == '__main__':
    unittest.main() 