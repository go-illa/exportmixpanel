# Mixpanel Export and Analysis Tool

A Flask-based web application for exporting data from Mixpanel, analyzing trip data, and displaying insights through an interactive dashboard. The application focuses on analyzing trip quality and GPS tracking data.

## Project Overview

This tool is designed to:
1. Export trip data from Mixpanel
2. Analyze GPS tracking quality
3. Calculate and categorize trip quality based on GPS logs
4. Visualize trip metrics and insights
5. Manage trip metadata including tags and quality assessments

## Project Structure

```
exportmixpanel/
├── app.py                 # Main Flask application
├── exportmix.py           # Command-line tool for Mixpanel export
├── consolidatemixpanel.py # Command-line tool for data consolidation
├── mobile_specs.py        # Mobile device specifications data
├── db/                    # Database configuration and models
│   ├── config.py          # Database and API configuration
│   └── models.py          # Database model definitions
├── data/                  # Directory for data files
├── templates/             # HTML templates for web interface
│   ├── analytics.html     # Dashboard template
│   ├── trips.html         # Trip list view template
│   ├── trip_detail.html   # Trip details template
│   ├── trip_insights.html # Trip insights dashboard
│   └── ...
└── static/               # Static assets (CSS, JS, images)
```

## Key Features

- **Data Export**: Extract trip data from Mixpanel API
- **Data Consolidation**: Merge trip data with mobile device specifications
- **Trip Quality Analysis**: Calculate trip quality based on GPS data characteristics
- **Interactive Dashboards**: Visualize trip metrics and insights
- **Trip Management**: Filter, tag, and manage trip data
- **Device Analysis**: Examine device specifications and their impact on tracking quality

## Trip Quality Calculation

The application calculates "Expected Trip Quality" based on GPS tracking data analysis. This is one of the core features, and the calculation is based on the following metrics:

### Trip Quality Metrics:

1. **Logs Count**: Number of GPS data points recorded during a trip
2. **Segment Distance Analysis**:
   - Short segments: Segments with distance < 1km
   - Medium segments: Segments with distance between 1-5km
   - Long segments: Segments with distance > 5km
3. **GPS Accuracy**: Boolean flag indicating if tracking had accuracy issues

### Quality Calculation Algorithm:

The quality is determined using the following algorithm:

```python
def calculate_expected_trip_quality(
    logs_count, 
    lack_of_accuracy, 
    medium_segments_count, 
    long_segments_count, 
    short_dist_total, 
    medium_dist_total, 
    long_dist_total,
    calculated_distance
):
    # Special cases
    if (short_dist_total + medium_dist_total + long_dist_total) <= 0 or logs_count <= 1:
        return "No Logs Trip"
        
    if logs_count < 5 and medium_segments_count == 0 and long_segments_count == 0:
        return "No Logs Trip"
        
    if logs_count < 50 and (medium_segments_count > 0 or long_segments_count > 0):
        return "Trip Points Only Exist"
    
    # Calculate logs factor (normalized to 500 logs)
    logs_factor = min(logs_count / 500.0, 1.0)
    
    # Calculate segment ratio
    ratio = short_dist_total / (medium_dist_total + long_dist_total + 0.01)  # epsilon to avoid division by zero
    
    # Segment factor based on ratio
    if ratio >= 5:
        segment_factor = 1.0
    elif ratio <= 0.5:
        segment_factor = 0.0
    else:
        segment_factor = (ratio - 0.5) / 4.5
    
    # Overall quality score
    quality_score = 0.5 * logs_factor + 0.5 * segment_factor
    
    # Apply penalty for GPS accuracy issues
    if lack_of_accuracy:
        quality_score *= 0.8

    # Map to quality categories
    if quality_score >= 0.8:
        return "High Quality Trip"
    elif quality_score >= 0.5:
        return "Moderate Quality Trip"
    else:
        return "Low Quality Trip"
```

### Quality Categories:

- **High Quality Trip**: Score ≥ 0.8
- **Moderate Quality Trip**: 0.5 ≤ Score < 0.8
- **Low Quality Trip**: Score < 0.5
- **Trip Points Only Exist**: Few logs (<50) but with medium/long segments
- **No Logs Trip**: Minimal or non-existent GPS data

## Distance Calculations

Trip distances are calculated using the Haversine formula, which determines the great-circle distance between two points on a sphere based on their latitude and longitude:

```python
def haversine_distance(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r
```

## Additional Metrics Calculations

The application calculates several additional metrics to provide comprehensive insights into trip quality and tracking performance:

### 1. Distance Variance

**Average Distance Variance (%)**
- Calculated as the average percentage difference between calculated distance and manually recorded distance across all trips.
- Formula: `variance = abs(calculated_distance - manual_distance) / manual_distance * 100`
- The system aggregates this across all trips with valid distance values.

```python
variance_sum = 0.0
variance_count = 0

for trip in filtered_trips:
    try:
        md = float(trip.manual_distance)
        cd = float(trip.calculated_distance)
        
        if md > 0:
            variance = abs(cd - md) / md * 100
            variance_sum += variance
            variance_count += 1
    except:
        pass

avg_distance_variance = variance_sum / variance_count if variance_count else 0
```

### 2. Accurate Trips

**Accurate Trips (<25% variance)**
- Counts trips where the variance between calculated and manual distance is less than 25%.
- This identifies trips with reliable GPS tracking data.

```python
accurate_count = 0

for trip in filtered_trips:
    try:
        md = float(trip.manual_distance)
        cd = float(trip.calculated_distance)
        
        if md > 0:
            variance = abs(cd - md) / md * 100
            if variance < 25.0:
                accurate_count += 1
    except:
        pass

accurate_count_pct = (accurate_count / total_trips * 100) if total_trips else 0
```

### 3. App Killed Issue Trips

**App Killed Issue Trips**
- Identifies trips where the app was likely killed by the device's operating system during tracking.
- Detection criteria:
  - No lack of accuracy flag
  - Non-zero calculated distance
  - Medium and long segments make up at least 40% of the total calculated distance
  - At least one medium or long segment exists

```python
app_killed_count = 0

for trip in filtered_trips:
    try:
        if trip.lack_of_accuracy is False and float(trip.calculated_distance) > 0:
            lm_distance = (float(trip.medium_segments_distance or 0) 
                           + float(trip.long_segments_distance or 0))
            lm_count = (trip.medium_segments_count or 0) + (trip.long_segments_count or 0)
            if lm_count > 0 and (lm_distance / float(trip.calculated_distance)) >= 0.4:
                app_killed_count += 1
    except:
        pass

app_killed_pct = (app_killed_count / total_trips * 100) if total_trips else 0
```

### 4. Single Log Trips

**Trips with Only 1 Log**
- Counts trips with exactly one coordinate logged, indicating a failure in continuous tracking.
- These are trips where the app started tracking but failed to continue recording coordinates.

```python
one_log_count = 0

for trip in filtered_trips:
    if trip.coordinate_count == 1:
        one_log_count += 1

one_log_pct = (one_log_count / total_trips * 100) if total_trips else 0
```

### 5. Segment Distance Percentages

**Distance Distribution Percentages**
- Calculates what percentage of the total calculated distance comes from each segment type:
  - **Short Dist % of Total Calc Distance**: Percentage of total distance from segments < 1km
  - **Medium Dist % of Total Calc Distance**: Percentage of total distance from segments 1-5km
  - **Long Dist % of Total Calc Distance**: Percentage of total distance from segments > 5km

```python
total_short_dist = 0.0
total_medium_dist = 0.0
total_long_dist = 0.0
total_calculated = 0.0

for trip in filtered_trips:
    try:
        cd = float(trip.calculated_distance)
        total_calculated += cd
        
        if trip.short_segments_distance:
            total_short_dist += float(trip.short_segments_distance)
        if trip.medium_segments_distance:
            total_medium_dist += float(trip.medium_segments_distance)
        if trip.long_segments_distance:
            total_long_dist += float(trip.long_segments_distance)
    except:
        pass

short_dist_pct = (total_short_dist / total_calculated * 100) if total_calculated else 0
medium_dist_pct = (total_medium_dist / total_calculated * 100) if total_calculated else 0
long_dist_pct = (total_long_dist / total_calculated * 100) if total_calculated else 0
```

## Prerequisites

- Python 3.8+
- Flask
- SQLAlchemy
- Pandas
- Requests
- Openpyxl

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/exportmixpanel.git
   cd exportmixpanel
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Running the Web Application

```
python app.py
```

The application will be available at `http://localhost:5000`.

### Exporting Data from Mixpanel

```
python exportmix.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

This command exports data from Mixpanel for the specified date range and saves it to `mixpanel_export.xlsx`.

### Consolidating Exported Data

```
python consolidatemixpanel.py --input-file mixpanel_export.xlsx --output-dir data --output-file data.xlsx
```

This command consolidates the exported data, merges it with mobile device specifications, and saves it to the specified output file.

## Web Interface Features

- **Dashboard**: Overview of trip statistics and device metrics
- **Trips View**: Browse, filter, and manage trip records
- **Trip Details**: View detailed information about a specific trip
- **Trip Insights**: Advanced analytics on trip patterns and quality
- **Automatic Insights**: AI-powered insights on trip data

## Database Schema

The application uses SQLAlchemy with SQLite by default. The main database tables are:

- **Trip**: Stores trip information, quality metrics, and analysis results
  - trip_id: Unique identifier from the source system
  - manual_distance: Manually recorded distance
  - calculated_distance: Distance calculated from GPS coordinates
  - route_quality: Manual quality assessment
  - expected_trip_quality: Calculated quality based on GPS data
  - coordinate_count: Number of GPS coordinates recorded
  - short/medium/long_segments_count: Count of segments by distance
  - short/medium/long_segments_distance: Total distance by segment type

- **Tag**: Stores tag information with many-to-many relationship to trips
  - id: Primary key
  - name: Tag name (unique)

## Asynchronous Processing

The application uses ThreadPoolExecutor for asynchronous processing of data updates:
- Update trip details from API
- Process bulk updates
- Track update progress

## API Endpoints

- `/api/update_db` - Update database with trip information
- `/api/update_db_async` - Start asynchronous update for a trip
- `/api/update_all_db_async` - Start asynchronous update for all trips
- `/api/update_progress` - Get progress of an asynchronous update

## License

This project is licensed under the MIT License - see the LICENSE file for details. 