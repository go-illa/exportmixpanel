import unittest
import os
import shutil
import pandas as pd
import consolidatemixpanel


class TestConsolidateMixpanel(unittest.TestCase):
    def setUp(self):
        # Clean up any previous test files
        if os.path.exists('mixpanel_export.xlsx'):
            os.remove('mixpanel_export.xlsx')
        if os.path.exists('data/data.xlsx'):
            os.remove('data/data.xlsx')
        if os.path.exists('data/backup'):
            shutil.rmtree('data/backup')
        if not os.path.exists('data'):
            os.makedirs('data')

    def tearDown(self):
        if os.path.exists('mixpanel_export.xlsx'):
            os.remove('mixpanel_export.xlsx')
        if os.path.exists('data/data.xlsx'):
            os.remove('data/data.xlsx')
        if os.path.exists('data/backup'):
            shutil.rmtree('data/backup')

    def test_consolidate_with_event(self):
        # Create a sample Excel file mimicking the export with an 'event' column
        df = pd.DataFrame({
            'event': ['click', 'view', 'click'],
            'value': [10, 20, 30]
        })
        df.to_excel('mixpanel_export.xlsx', index=False)

        # Run the consolidation which groups by event by counting occurrences
        consolidatemixpanel.consolidate_data()

        # Check that the consolidated file is created
        self.assertTrue(os.path.exists('data/data.xlsx'))

        # Read the consolidated file
        df_out = pd.read_excel('data/data.xlsx')

        # For event column, grouping should result in two rows
        self.assertEqual(len(df_out), 2)
        self.assertIn('count', df_out.columns)
        
        # Verify that the count for event 'click' is 2 and 'view' is 1
        count_click = df_out.loc[df_out['event'] == 'click', 'count'].iloc[0]
        count_view = df_out.loc[df_out['event'] == 'view', 'count'].iloc[0]
        self.assertEqual(count_click, 2)
        self.assertEqual(count_view, 1)


if __name__ == '__main__':
    unittest.main() 