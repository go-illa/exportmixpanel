import unittest
from unittest.mock import patch, MagicMock
import os
import pandas as pd
import json
import exportmix


class TestExportMix(unittest.TestCase):

    def setUp(self):
        if os.path.exists('mixpanel_export.xlsx'):
            os.remove('mixpanel_export.xlsx')

    def tearDown(self):
        if os.path.exists('mixpanel_export.xlsx'):
            os.remove('mixpanel_export.xlsx')

    @patch('exportmix.requests.get')
    def test_export_data_success(self, mock_get):
        # Create a dummy response mimicking Mixpanel API response
        dummy_data = '{"properties": {"time": 1609459200, "mp_api_timestamp_ms": 1609459200000}, "event": "test_event"}\n'
        dummy_response = MagicMock()
        dummy_response.status_code = 200
        dummy_response.text = dummy_data
        mock_get.return_value = dummy_response

        # Call export_data with dummy date range
        exportmix.export_data("2023-01-01", "2023-01-02")

        # Check that the export file is created
        self.assertTrue(os.path.exists('mixpanel_export.xlsx'))

        # Read the excel file and validate content
        df = pd.read_excel('mixpanel_export.xlsx')
        self.assertIn('event', df.columns)
        self.assertEqual(df.iloc[0]['event'], 'test_event')


if __name__ == '__main__':
    unittest.main() 