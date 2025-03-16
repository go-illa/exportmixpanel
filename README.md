# Mixpanel Export Tool

A comprehensive tool for exporting, analyzing, and visualizing Mixpanel data.

## Features

- Export data from Mixpanel API
- Analyze event data and user profiles
- Visualize data through interactive dashboards
- Store and query historical data

## Installation

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

Run the main application:
```
python app.py
```

For data export only:
```
python exportmix.py
```

For data consolidation:
```
python consolidatemixpanel.py
```

## Project Structure

- `app.py`: Main web application
- `exportmix.py`: Mixpanel data export script
- `consolidatemixpanel.py`: Data consolidation utilities
- `publishfetch.py`: Publishing and fetching utilities
- `templates/`: HTML templates for web interface
- `static/`: Static assets (CSS, JS, images)
- `data/`: Exported data storage
- `db/`: Database files

## Requirements

See `requirements.txt` for a list of dependencies. 