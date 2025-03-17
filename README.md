# Mixpanel Export & Analytics Tool

A comprehensive tool to export event data from Mixpanel, consolidate and enhance it with mobile device specifications, and provide an interactive web dashboard for analyzing trip data.

## Features

- Export event data from the Mixpanel API for a specified date range.
- Consolidate exported data to filter unique trip records (keeping only the most recent entry per trip).
- Merge trip data with mobile device specifications for enhanced insights.
- Interactive web dashboard built with Flask to visualize analytics and trip details.
- Automatic database migration to update the trips schema with additional columns (e.g., trip_time, completed_by, coordinate_count).
- Command-line utilities for data export and consolidation.

## Installation

1. Clone this repository.
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Web Application

Run the main Flask application:
```
python app.py
```
This will start the interactive dashboard where you can:
- View trip analytics and insights.
- Update trip details and database records.
- Apply filters to analyze trip data.

### Data Export

To export data directly from Mixpanel, run:
```
python exportmix.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```
This command fetches event data from Mixpanel within the specified date range and saves it to 'mixpanel_export.xlsx'.

### Data Consolidation

To consolidate the exported data and merge it with mobile device specifications, run:
```
python consolidatemixpanel.py
```
This will:
- Read the exported Excel file.
- Remove duplicate trip entries (keeping the one with the most recent timestamp).
- Merge the data with mobile device specifications from an embedded CSV.
- Save the final consolidated file in the 'data' directory.

## Project Structure

- `app.py`: Main web application (Flask) that provides an interactive dashboard for trip analytics and data management.
- `exportmix.py`: Command-line utility to export event data from Mixpanel.
- `consolidatemixpanel.py`: Utility to consolidate and merge exported data with mobile device specifications.
- `db/`: Contains database configuration and model definitions.
- `templates/`: HTML templates for the Flask web interface.
- `static/`: Static assets (CSS, JS, images) for the web interface.
- `data/`: Directory for exported and consolidated data.
- `tests/`: Automated tests for validating functionality.

## Requirements

Refer to `requirements.txt` for a list of Python dependencies.

## License

[Insert License Information Here] 