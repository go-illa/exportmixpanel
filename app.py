import os
import io
import requests
import openpyxl
from openpyxl import Workbook
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    send_file,
    session as flask_session
)
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from datetime import datetime
import shutil
import subprocess
from collections import defaultdict, Counter

from db.config import DB_URI, API_TOKEN, BASE_API_URL, API_EMAIL, API_PASSWORD
from db.models import Base, Trip

app = Flask(__name__)
app.secret_key = "your_secret_key"  # for flashing and session

# Create engine with SQLite thread-safety; disable expire_on_commit so instances remain populated.
engine = create_engine(DB_URI, echo=True, connect_args={"check_same_thread": False})
Session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))

# --- Begin Migration to update schema with new columns ---
def migrate_db():
    try:
        with engine.connect() as connection:
            result = connection.execute("PRAGMA table_info(trips)")
            # Get column names from PRAGMA result; index 1 is the column name
            columns = [row[1] for row in result]
            if "trip_time" not in columns:
                connection.execute("ALTER TABLE trips ADD COLUMN trip_time FLOAT")
                app.logger.info("Added column trip_time to trips table")
            if "completed_by" not in columns:
                connection.execute("ALTER TABLE trips ADD COLUMN completed_by TEXT")
                app.logger.info("Added column completed_by to trips table")
    except Exception as e:
        app.logger.error("Migration error: %s", e)

migrate_db()
# --- End Migration ---

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

# ---------------------------
# Utility Functions
# ---------------------------

def get_saved_filters():
    return flask_session.get("saved_filters", {})

def save_filter_to_session(name, filters):
    saved = flask_session.get("saved_filters", {})
    saved[name] = filters
    flask_session["saved_filters"] = saved

def fetch_api_token():
    url = f"{BASE_API_URL}/auth/sign_in"
    payload = {"admin_user": {"email": API_EMAIL, "password": API_PASSWORD}}
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        return resp.json().get("token", None)
    else:
        print("Error fetching primary token:", resp.text)
        return None

def fetch_api_token_alternative():
    alt_email = "SupplyPartner@illa.com.eg"
    alt_password = "654321"
    url = f"{BASE_API_URL}/auth/sign_in"
    payload = {"admin_user": {"email": alt_email, "password": alt_password}}
    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("token", None)
    except Exception as e:
        print("Error fetching alternative token:", e)
        return None

def load_excel_data(excel_path):
    workbook = openpyxl.load_workbook(excel_path)
    sheet = workbook.active
    headers = []
    data = []
    for i, row in enumerate(sheet.iter_rows(values_only=True)):
        if i == 0:
            headers = row
        else:
            row_dict = {headers[j]: row[j] for j in range(len(row))}
            data.append(row_dict)
    print(f"Loaded {len(data)} rows from Excel.")
    return data

# Carrier grouping
CARRIER_GROUPS = {
    "Vodafone": ["vodafone", "voda fone", "tegi ne3eesh"],
    "Orange": ["orange", "orangeeg", "orange eg"],
    "Etisalat": ["etisalat", "e& etisalat", "e&"],
    "We": ["we"]
}

def normalize_carrier(carrier_name):
    if not carrier_name:
        return ""
    lower = carrier_name.lower().strip()
    for group, variants in CARRIER_GROUPS.items():
        for variant in variants:
            if variant in lower:
                return group
    return carrier_name.title()

def fetch_trip_from_api(trip_id, token=API_TOKEN):
    url = f"{BASE_API_URL}/trips/{trip_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        calc = data.get("data", {}).get("attributes", {}).get("calculatedDistance")
        if not calc or calc in [None, "", "N/A"]:
            raise ValueError("Missing calculatedDistance")
        return data
    except Exception as e:
        print("Error fetching trip data with primary token:", e)
        alt_token = fetch_api_token_alternative()
        if alt_token:
            headers = {"Authorization": f"Bearer {alt_token}", "Content-Type": "application/json"}
            try:
                resp = requests.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                data["used_alternative"] = True
                return data
            except Exception as e:
                print("Error fetching trip data with alternative token:", e)
                return None
        else:
            return None

def update_trip_db(trip_id, force_update=False):
    """
    Fetch trip from API if needed, update or create DB record.
    """
    session_local = Session()
    try:
        db_trip = session_local.query(Trip).filter_by(trip_id=trip_id).first()
        # If we already have a completed trip and not forcing update, skip fetching from the API
        if db_trip and not force_update and db_trip.status and db_trip.status.lower() == "completed":
            return db_trip
        api_data = fetch_trip_from_api(trip_id)
        if api_data and "data" in api_data:
            trip_attributes = api_data["data"]["attributes"]
            if db_trip is None:
                db_trip = Trip(
                    trip_id=trip_id,
                    status=trip_attributes.get("status"),
                    manual_distance=trip_attributes.get("manualDistance"),
                    calculated_distance=trip_attributes.get("calculatedDistance")
                )
                session_local.add(db_trip)
            else:
                db_trip.status = trip_attributes.get("status")
                try:
                    db_trip.manual_distance = float(trip_attributes.get("manualDistance") or 0)
                except ValueError:
                    db_trip.manual_distance = None
                try:
                    db_trip.calculated_distance = float(trip_attributes.get("calculatedDistance") or 0)
                except ValueError:
                    db_trip.calculated_distance = None
            if api_data.get("used_alternative"):
                db_trip.supply_partner = True

            # Calculate trip time and determine who completed the trip
            pickup_time_str = trip_attributes.get("pickupTime")
            if pickup_time_str:
                try:
                    pickup_time = datetime.strptime(pickup_time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    try:
                        pickup_time = datetime.strptime(pickup_time_str, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        try:
                            pickup_time = datetime.strptime(pickup_time_str, "%Y-%m-%d %H:%M:%S")
                        except Exception as e:
                            pickup_time = None
                            print("Error parsing pickupTime:", e)
            else:
                pickup_time = None

            candidate = None
            candidate_time = None
            for event in trip_attributes.get("activity", []):
                if "changes" in event:
                    status_change = event["changes"].get("status")
                    if status_change and isinstance(status_change, list) and status_change[-1] == "completed":
                        created_str = event.get("created_at", "").replace(" UTC", "")
                        if created_str:
                            parsed = False
                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"]:
                                try:
                                    event_time = datetime.strptime(created_str, fmt)
                                    parsed = True
                                    break
                                except ValueError:
                                    continue
                            if parsed:
                                if candidate_time is None or event_time > candidate_time:
                                    candidate_time = event_time
                                    candidate = event

            if pickup_time and candidate_time:
                try:
                    trip_duration_hours = (candidate_time - pickup_time).total_seconds() / 3600.0
                    db_trip.trip_time = trip_duration_hours
                    app.logger.info(f"Trip {trip_id}: pickup_time={pickup_time}, completion_time={candidate_time}, duration_hours={trip_duration_hours}")
                except Exception as e:
                    print("Error calculating trip time:", e)
                    db_trip.trip_time = None
            else:
                db_trip.trip_time = None

            if candidate:
                user_name = candidate.get("user_name", "")
                local_part = user_name.split("@")[0] if user_name else ""
                if local_part.isdigit():
                    db_trip.completed_by = "driver"
                else:
                    db_trip.completed_by = "admin"
                app.logger.info(f"Trip {trip_id}: completed_by set to {db_trip.completed_by} based on user_name {user_name}")
            else:
                db_trip.completed_by = None
                app.logger.info(f"Trip {trip_id}: No candidate event found, completed_by remains None")

            session_local.commit()
            session_local.refresh(db_trip)
        return db_trip
    except Exception as e:
        print("Error in update_trip_db:", e)
        session_local.rollback()
        return session_local.query(Trip).filter_by(trip_id=trip_id).first()
    finally:
        session_local.close()

# ---------------------------
# Routes
# ---------------------------

@app.route("/update_db", methods=["POST"])
def update_db():
    """
    Bulk update DB from Excel (fetch each trip from the API).
    """
    session_local = Session()
    excel_path = os.path.join("data", "data.xlsx")
    excel_data = load_excel_data(excel_path)
    updated_ids = []
    for row in excel_data:
        trip_id = row.get("tripId")
        if trip_id:
            db_trip = update_trip_db(trip_id)
            if db_trip:
                updated_ids.append(trip_id)
    session_local.close()
    flash(f"Updated database for {len(updated_ids)} trips.", "success")
    return redirect(url_for("trips"))

@app.route("/export_trips")
def export_trips():
    """
    Export filtered trips to XLSX, merging with DB data (route_quality, distances, etc.).
    """
    session_local = Session()
    filters = {
        "driver": request.args.get("driver"),
        "trip_id": request.args.get("trip_id"),
        "route_quality": request.args.get("route_quality"),
        "model": request.args.get("model"),
        "ram": request.args.get("ram"),
        "carrier": request.args.get("carrier"),
        "variance_min": request.args.get("variance_min"),
        "variance_max": request.args.get("variance_max"),
        "export_name": request.args.get("export_name", "exported_trips")
    }
    excel_path = os.path.join("data", "data.xlsx")
    excel_data = load_excel_data(excel_path)

    # Apply filters on the Excel data
    if filters["driver"]:
        excel_data = [row for row in excel_data if str(row.get("UserName", "")).strip() == filters["driver"]]
    if filters["trip_id"]:
        try:
            tid = int(filters["trip_id"])
            excel_data = [row for row in excel_data if row.get("tripId") == tid]
        except ValueError:
            pass
    if filters["model"]:
        excel_data = [row for row in excel_data if str(row.get("model", "")).strip() == filters["model"]]
    if filters["ram"]:
        excel_data = [row for row in excel_data if str(row.get("RAM", "")).strip() == filters["ram"]]
    if filters["carrier"]:
        excel_data = [row for row in excel_data if str(row.get("carrier", "")).strip().lower() == filters["carrier"].lower()]
    if filters["route_quality"]:
        excel_data = [row for row in excel_data if str(row.get("route_quality", "")) == filters["route_quality"]]

    # Merge with DB
    excel_trip_ids = [row.get("tripId") for row in excel_data if row.get("tripId")]
    db_trips = session_local.query(Trip).filter(Trip.trip_id.in_(excel_trip_ids)).all()
    db_trip_map = {trip.trip_id: trip for trip in db_trips}

    merged = []
    for row in excel_data:
        trip_id = row.get("tripId")
        db_trip = db_trip_map.get(trip_id)
        if db_trip:
            try:
                md = float(db_trip.manual_distance)
            except (TypeError, ValueError):
                md = None
            try:
                cd = float(db_trip.calculated_distance)
            except (TypeError, ValueError):
                cd = None
            row["route_quality"] = db_trip.route_quality or ""
            row["manual_distance"] = md if md is not None else ""
            row["calculated_distance"] = cd if cd is not None else ""
            if md and cd and md != 0:
                pct = (cd / md) * 100
                row["distance_percentage"] = f"{pct:.2f}%"
                variance = abs(cd - md) / md * 100
                row["variance"] = variance
            else:
                row["distance_percentage"] = "N/A"
                row["variance"] = None
        else:
            row["route_quality"] = ""
            row["manual_distance"] = ""
            row["calculated_distance"] = ""
            row["distance_percentage"] = "N/A"
            row["variance"] = None
        merged.append(row)

    # Additional variance filters
    if filters["variance_min"]:
        try:
            vmin = float(filters["variance_min"])
            merged = [r for r in merged if r.get("variance") is not None and r["variance"] >= vmin]
        except ValueError:
            pass
    if filters["variance_max"]:
        try:
            vmax = float(filters["variance_max"])
            merged = [r for r in merged if r.get("variance") is not None and r["variance"] <= vmax]
        except ValueError:
            pass

    wb = Workbook()
    ws = wb.active
    if merged:
        headers = list(merged[0].keys())
        ws.append(headers)
        for row in merged:
            ws.append([row.get(col) for col in headers])
    else:
        ws.append(["No data found"])

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    filename = f"{filters['export_name']}.xlsx"
    session_local.close()
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=filename,  # For Flask 2.2+ 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ---------------------------
# Dashboard (Analytics) - Consolidated by User, with Date Range
# ---------------------------
@app.route("/")
def analytics():
    """
    Main dashboard page with a toggle for:
      - data_scope = 'all'   => analyze ALL trips in DB
      - data_scope = 'excel' => only the trip IDs in the current data.xlsx
    We store the user's choice in the session so it persists until changed.
    """
    session_local = Session()

    # 1) Check if user provided data_scope in request
    if "data_scope" in request.args:
        chosen_scope = request.args.get("data_scope", "all")
        flask_session["data_scope"] = chosen_scope
    else:
        chosen_scope = flask_session.get("data_scope", "all")  # default 'all'

    # 2) Additional filters for analytics page
    driver_filter = request.args.get("driver", "").strip()
    carrier_filter = request.args.get("carrier", "").strip()

    # 3) Load Excel data & merge route_quality from DB
    excel_path = os.path.join("data", "data.xlsx")
    excel_data = load_excel_data(excel_path)
    excel_trip_ids = [r["tripId"] for r in excel_data if r.get("tripId")]
    session_local = Session()
    db_trips_for_excel = session_local.query(Trip).filter(Trip.trip_id.in_(excel_trip_ids)).all()
    db_map = {t.trip_id: t for t in db_trips_for_excel}
    for row in excel_data:
        trip_id = row.get("tripId")
        if trip_id in db_map:
            row["route_quality"] = db_map[trip_id].route_quality or ""
        else:
            row.setdefault("route_quality", "")

    # 4) Decide which DB trips to analyze for distance accuracy
    if chosen_scope == "excel":
        trips_db = db_trips_for_excel
    else:
        trips_db = session_local.query(Trip).all()

    # 5) Compute distance accuracy
    correct = 0
    incorrect = 0
    for trip in trips_db:
        try:
            md = float(trip.manual_distance)
            cd = float(trip.calculated_distance)
            if md and md != 0:
                if abs(cd - md) / md <= 0.2:
                    correct += 1
                else:
                    incorrect += 1
        except:
            pass
    total_trips = correct + incorrect
    if total_trips > 0:
        correct_pct = correct / total_trips * 100
        incorrect_pct = incorrect / total_trips * 100
    else:
        correct_pct = 0
        incorrect_pct = 0

    # 6) Build a filtered "excel-like" dataset for the user-level charts
    if chosen_scope == "excel":
        # Just the real Excel data
        filtered_excel_data = excel_data[:]
    else:
        # All DB trips, but we create placeholders if a trip isn't in Excel
        all_db = trips_db
        excel_map = {r["tripId"]: r for r in excel_data if r.get("tripId")}
        all_data_rows = []
        for tdb in all_db:
            if tdb.trip_id in excel_map:
                row_copy = dict(excel_map[tdb.trip_id])
                row_copy["route_quality"] = tdb.route_quality or ""
            else:
                row_copy = {
                    "tripId": tdb.trip_id,
                    "UserName": "",
                    "carrier": "",
                    "Android Version": "",
                    "manufacturer": "",
                    "model": "",
                    "RAM": "",
                    "route_quality": tdb.route_quality or ""
                }
            all_data_rows.append(row_copy)
        filtered_excel_data = all_data_rows

    # 7) Apply driver & carrier filters
    if driver_filter:
        filtered_excel_data = [r for r in filtered_excel_data if str(r.get("UserName","")).strip() == driver_filter]

    if carrier_filter:
        # user picked one of the 4 carriers => keep only matching normalized
        new_list = []
        for row in filtered_excel_data:
            norm_car = normalize_carrier(row.get("carrier",""))
            if norm_car == carrier_filter:
                new_list.append(row)
        filtered_excel_data = new_list

    # 8) Consolidate user-latest for charts
    user_latest = {}
    for row in filtered_excel_data:
        user = str(row.get("UserName","")).strip()
        if user:
            user_latest[user] = row
    consolidated_rows = list(user_latest.values())

    # Prepare chart data
    carrier_counts = {}
    os_counts = {}
    manufacturer_counts = {}
    model_counts = {}

    for row in consolidated_rows:
        c = normalize_carrier(row.get("carrier",""))
        carrier_counts[c] = carrier_counts.get(c,0)+1

        osv = row.get("Android Version","Unknown")
        os_counts[osv] = os_counts.get(osv,0)+1

        manu = row.get("manufacturer","Unknown")
        manufacturer_counts[manu] = manufacturer_counts.get(manu,0)+1

        mdl = row.get("model","UnknownModel")
        model_counts[mdl] = model_counts.get(mdl,0)+1

    total_users = len(consolidated_rows)
    device_usage = []
    for mdl, cnt in model_counts.items():
        pct = (cnt / total_users * 100) if total_users else 0
        device_usage.append({"model": mdl, "count": cnt, "percentage": round(pct,2)})

    # Build user_data for High/Low/Other
    user_data = {}
    for row in filtered_excel_data:
        user = str(row.get("UserName","")).strip()
        if not user:
            continue
        if user not in user_data:
            user_data[user] = {
                "total_trips": 0,
                "No Logs Trips": 0,
                "Trip Points Only Exist": 0,
                "Low": 0,
                "Moderate": 0,
                "High": 0,
                "Other": 0
            }
        user_data[user]["total_trips"] += 1
        q = row.get("route_quality", "")
        if q in ["No Logs Trips", "Trip Points Only Exist", "Low", "Moderate", "High"]:
            user_data[user][q] += 1
        else:
            user_data[user]["Other"] += 1

    # Quality analysis
    high_quality_models = {}
    low_quality_models = {}
    high_quality_android = {}
    low_quality_android = {}
    high_quality_ram = {}
    low_quality_ram = {}

    sensor_cols = [
        "Fingerprint Sensor","Accelerometer","Gyro",
        "Proximity Sensor","Compass","Barometer",
        "Background Task Killing Tendency"
    ]
    high_quality_sensors = {s:0 for s in sensor_cols}
    total_high_quality = 0

    for row in filtered_excel_data:
        q = row.get("route_quality","")
        mdl = row.get("model","UnknownModel")
        av = row.get("Android Version","Unknown")
        ram = row.get("RAM","")
        if q == "High":
            total_high_quality +=1
            high_quality_models[mdl] = high_quality_models.get(mdl,0)+1
            high_quality_android[av] = high_quality_android.get(av,0)+1
            high_quality_ram[ram] = high_quality_ram.get(ram,0)+1
            for sensor in sensor_cols:
                val = row.get(sensor,"")
                if (isinstance(val,str) and val.lower()=="true") or (val is True):
                    high_quality_sensors[sensor]+=1
        elif q == "Low":
            low_quality_models[mdl] = low_quality_models.get(mdl,0)+1
            low_quality_android[av] = low_quality_android.get(av,0)+1
            low_quality_ram[ram] = low_quality_ram.get(ram,0)+1

    session_local.close()

    # Build driver list for the dropdown
    all_drivers = sorted({str(r.get("UserName","")).strip() for r in excel_data if r.get("UserName")})
    carriers_for_dropdown = ["Vodafone","Orange","Etisalat","We"]

    return render_template(
        "analytics.html",
        data_scope=chosen_scope,
        driver_filter=driver_filter,
        carrier_filter=carrier_filter,
        drivers=all_drivers,
        carriers_for_dropdown=carriers_for_dropdown,
        carrier_counts=carrier_counts,
        os_counts=os_counts,
        manufacturer_counts=manufacturer_counts,
        device_usage=device_usage,
        total_trips=total_trips,
        correct_pct=correct_pct,
        incorrect_pct=incorrect_pct,
        user_data=user_data,
        high_quality_models=high_quality_models,
        low_quality_models=low_quality_models,
        high_quality_android=high_quality_android,
        low_quality_android=low_quality_android,
        high_quality_ram=high_quality_ram,
        low_quality_ram=low_quality_ram,
        high_quality_sensors=high_quality_sensors,
        total_high_quality=total_high_quality
    )


# ---------------------------
# Trips Page with Variance, Pagination, etc.
# ---------------------------
@app.route("/trips")
def trips():
    """
    Trips page with a carrier dropdown (Vodafone, Orange, Etisalat, We),
    plus your usual filters, pagination, etc.
    """
    session_local = Session()
    page = request.args.get("page", type=int, default=1)
    page_size = 100
    if page<1:
        page=1

    driver_filter = request.args.get("driver","").strip()
    trip_id_search = request.args.get("trip_id","").strip()
    route_quality_filter = request.args.get("route_quality","").strip()
    model_filter = request.args.get("model","").strip()
    ram_filter = request.args.get("ram","").strip()
    carrier_filter = request.args.get("carrier","").strip()
    variance_min = request.args.get("variance_min", type=float)
    variance_max = request.args.get("variance_max", type=float)

    excel_path = os.path.join("data","data.xlsx")
    excel_data = load_excel_data(excel_path)

    # min/max date logic if needed
    all_times = []
    for row in excel_data:
        if row.get("time"):
            if isinstance(row["time"],str):
                try:
                    dt = datetime.strptime(row["time"],"%Y-%m-%d %H:%M:%S")
                    all_times.append(dt)
                except ValueError:
                    pass
            else:
                all_times.append(row["time"])
    min_date = min(all_times) if all_times else None
    max_date = max(all_times) if all_times else None

    # Filter
    if driver_filter:
        excel_data = [r for r in excel_data if str(r.get("UserName","")).strip()==driver_filter]
    if trip_id_search:
        try:
            tid = int(trip_id_search)
            excel_data = [r for r in excel_data if r.get("tripId")==tid]
        except ValueError:
            pass
    if model_filter:
        excel_data = [r for r in excel_data if str(r.get("model","")).strip()==model_filter]
    if ram_filter:
        excel_data = [r for r in excel_data if str(r.get("RAM","")).strip()==ram_filter]
    if carrier_filter:
        new_list=[]
        for row in excel_data:
            norm_car = normalize_carrier(row.get("carrier",""))
            if norm_car==carrier_filter:
                new_list.append(row)
        excel_data = new_list

    # Merge with DB
    excel_trip_ids = [r["tripId"] for r in excel_data if r.get("tripId")]
    db_trips = session_local.query(Trip).filter(Trip.trip_id.in_(excel_trip_ids)).all()
    db_map = {t.trip_id: t for t in db_trips}
    for row in excel_data:
        tdb = db_map.get(row["tripId"])
        if tdb:
            try:
                md = float(tdb.manual_distance)
            except:
                md=None
            try:
                cd = float(tdb.calculated_distance)
            except:
                cd=None
            row["route_quality"] = tdb.route_quality or ""
            row["manual_distance"] = md if md is not None else ""
            row["calculated_distance"] = cd if cd is not None else ""
            if md and cd and md!=0:
                pct = (cd/md)*100
                row["distance_percentage"]=f"{pct:.2f}%"
                var = abs(cd-md)/md*100
                row["variance"]=var
            else:
                row["distance_percentage"]="N/A"
                row["variance"]=None
        else:
            row["route_quality"]=""
            row["manual_distance"]=""
            row["calculated_distance"]=""
            row["distance_percentage"]="N/A"
            row["variance"]=None

    if route_quality_filter:
        excel_data = [r for r in excel_data if r["route_quality"]==route_quality_filter]
    if variance_min is not None:
        excel_data = [r for r in excel_data if r.get("variance") is not None and r["variance"]>=variance_min]
    if variance_max is not None:
        excel_data = [r for r in excel_data if r.get("variance") is not None and r["variance"]<=variance_max]

    total_rows = len(excel_data)
    total_pages = (total_rows+page_size-1)//page_size if total_rows else 1
    if page>total_pages and total_pages>0:
        page=total_pages
    start = (page-1)*page_size
    end = start+page_size
    page_data = excel_data[start:end]

    session_local.close()

    # For the filter dropdown
    full_excel = load_excel_data(excel_path)
    drivers = sorted({str(r.get("UserName","")).strip() for r in full_excel if r.get("UserName")})
    carriers_for_dropdown = ["Vodafone","Orange","Etisalat","We"]

    return render_template(
        "trips.html",
        driver_filter=driver_filter,
        trips=page_data,
        trip_id_search=trip_id_search,
        route_quality_filter=route_quality_filter,
        model_filter=model_filter,
        ram_filter=ram_filter,
        carrier_filter=carrier_filter,
        variance_min=variance_min if variance_min else "",
        variance_max=variance_max if variance_max else "",
        total_rows=total_rows,
        page=page,
        total_pages=total_pages,
        page_size=page_size,
        min_date=min_date,
        max_date=max_date,
        drivers=drivers,
        carriers_for_dropdown=carriers_for_dropdown
    )

@app.route("/trip/<int:trip_id>")
def trip_detail(trip_id):
    """
    Show detail page for a single trip, merges with DB.
    """
    session_local = Session()
    db_trip = update_trip_db(trip_id)
    if db_trip and db_trip.status and db_trip.status.lower() == "completed":
        api_data = None
    else:
        api_data = fetch_trip_from_api(trip_id)
    trip_attributes = {}
    if api_data and "data" in api_data:
        trip_attributes = api_data["data"]["attributes"]

    excel_path = os.path.join("data", "data.xlsx")
    excel_data = load_excel_data(excel_path)
    excel_trip_data = None
    for row in excel_data:
        if row.get("tripId") == trip_id:
            excel_trip_data = row
            break

    distance_verification = "N/A"
    trip_insight = ""
    distance_percentage = "N/A"
    if db_trip:
        try:
            md = float(db_trip.manual_distance)
        except (TypeError, ValueError):
            md = None
        try:
            cd = float(db_trip.calculated_distance)
        except (TypeError, ValueError):
            cd = None
        if md is not None and cd is not None:
            lower_bound = md * 0.8
            upper_bound = md * 1.2
            if lower_bound <= cd <= upper_bound:
                distance_verification = "Calculated distance is true"
                trip_insight = "Trip data is consistent."
            else:
                distance_verification = "Manual distance is true"
                trip_insight = "Trip data is inconsistent."
            if md != 0:
                distance_percentage = f"{(cd / md * 100):.2f}%"
        else:
            distance_verification = "N/A"
            trip_insight = "N/A"
            distance_percentage = "N/A"

    session_local.close()
    return render_template(
        "trip_detail.html",
        db_trip=db_trip,
        trip_attributes=trip_attributes,
        excel_trip_data=excel_trip_data,
        distance_verification=distance_verification,
        trip_insight=trip_insight,
        distance_percentage=distance_percentage
    )

@app.route("/update_route_quality", methods=["POST"])
def update_route_quality():
    """
    AJAX endpoint to update route_quality for a given trip_id.
    """
    session_local = Session()
    data = request.get_json()
    trip_id = data.get("trip_id")
    quality = data.get("route_quality")
    db_trip = session_local.query(Trip).filter_by(trip_id=trip_id).first()
    if not db_trip:
        db_trip = Trip(
            trip_id=trip_id,
            route_quality=quality,
            status="",
            manual_distance=None,
            calculated_distance=None
        )
        session_local.add(db_trip)
    else:
        db_trip.route_quality = quality
    session_local.commit()
    session_local.close()
    return jsonify({"status": "success", "message": "Route quality updated."}), 200

@app.route("/trip_insights")
def trip_insights():
    """
    Shows route quality counts, distance averages, distance consistency.
    Respects the data_scope from session so it matches the user's choice
    (all data or excel-only).
    """
    session_local = Session()

    data_scope = flask_session.get("data_scope","all")

    # If excel-only, limit to those trip IDs in data.xlsx
    excel_path = os.path.join("data","data.xlsx")
    excel_data = load_excel_data(excel_path)
    excel_trip_ids = [r["tripId"] for r in excel_data if r.get("tripId")]

    if data_scope == "excel":
        trips_db = session_local.query(Trip).filter(Trip.trip_id.in_(excel_trip_ids)).all()
    else:
        trips_db = session_local.query(Trip).all()

    quality_counts = {
        "No Logs Trips": 0,
        "Trip Points Only Exist": 0,
        "Low": 0,
        "Moderate": 0,
        "High": 0,
        "": 0
    }
    total_manual = 0
    total_calculated = 0
    count_manual = 0
    count_calculated = 0
    consistent = 0
    inconsistent = 0

    for trip in trips_db:
        q = trip.route_quality if trip.route_quality else ""
        quality_counts[q] = quality_counts.get(q,0)+1
        try:
            md = float(trip.manual_distance)
            cd = float(trip.calculated_distance)
            total_manual += md
            total_calculated += cd
            count_manual += 1
            count_calculated += 1
            if md!=0 and abs(cd-md)/md <= 0.2:
                consistent+=1
            else:
                inconsistent+=1
        except:
            pass

    avg_manual = total_manual/count_manual if count_manual else 0
    avg_calculated = total_calculated/count_calculated if count_calculated else 0

    excel_map = {r['tripId']: r for r in excel_data if r.get('tripId')}
    device_specs = defaultdict(lambda: defaultdict(list))
    for trip in trips_db:
        trip_id = trip.trip_id
        quality = trip.route_quality if trip.route_quality else "Unknown"
        if trip_id in excel_map:
            row = excel_map[trip_id]
            device_specs[quality]['model'].append(row.get('model', 'Unknown'))
            device_specs[quality]['android'].append(row.get('Android Version', 'Unknown'))
            device_specs[quality]['manufacturer'].append(row.get('manufacturer', 'Unknown'))
            device_specs[quality]['ram'].append(row.get('RAM', 'Unknown'))
    automatic_insights = {}
    for quality, specs in device_specs.items():
        model_counter = Counter(specs['model'])
        android_counter = Counter(specs['android'])
        manufacturer_counter = Counter(specs['manufacturer'])
        ram_counter = Counter(specs['ram'])
        most_common_model = model_counter.most_common(1)[0][0] if model_counter else 'N/A'
        most_common_android = android_counter.most_common(1)[0][0] if android_counter else 'N/A'
        most_common_manufacturer = manufacturer_counter.most_common(1)[0][0] if manufacturer_counter else 'N/A'
        most_common_ram = ram_counter.most_common(1)[0][0] if ram_counter else 'N/A'
        insight = f"For trips with quality '{quality}', most devices are {most_common_manufacturer} {most_common_model} (Android {most_common_android}, RAM {most_common_ram})."
        if quality.lower() == 'high':
            insight += " This suggests that high quality trips are associated with robust mobile specs, contributing to accurate tracking."
        elif quality.lower() == 'low':
            insight += " This might indicate that lower quality trips could be influenced by devices with suboptimal specifications."
        automatic_insights[quality] = insight

    # --- New Dashboard Aggregations ---
    # quality_drilldown: aggregated counts for device specs per quality (using model, android, manufacturer, and ram)
    quality_drilldown = {}
    for quality, specs in device_specs.items():
        quality_drilldown[quality] = {
            'model': dict(Counter(specs['model'])),
            'android': dict(Counter(specs['android'])),
            'manufacturer': dict(Counter(specs['manufacturer'])),
            'ram': dict(Counter(specs['ram']))
        }

    # New aggregation: RAM Quality Counts: counts of trip qualities per RAM capacity
    allowed_ram_str = ["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB"]
    ram_quality_counts = {ram: {} for ram in allowed_ram_str}
    import re
    for trip in trips_db:
        row = excel_map.get(trip.trip_id)
        if row:
            ram_str = row.get("RAM", "")
            match = re.search(r'(\d+(?:\.\d+)?)', str(ram_str))
            if match:
                ram_value = float(match.group(1))
                try:
                    ram_int = int(round(ram_value))
                except:
                    continue
                nearest = min([2,3,4,6,8,12,16], key=lambda v: abs(v - ram_int))
                ram_label = f"{nearest}GB"
                quality_val = trip.route_quality if trip.route_quality in ["High", "Moderate", "Low", "No Logs Trips", "Trip Points Only Exist"] else "Empty"
                if quality_val not in ram_quality_counts[ram_label]:
                    ram_quality_counts[ram_label][quality_val] = 0
                ram_quality_counts[ram_label][quality_val] += 1

    # sensor_stats: Calculate sensor availability percentages per quality category
    sensor_cols = ["Fingerprint Sensor","Accelerometer","Gyro","Proximity Sensor","Compass","Barometer","Background Task Killing Tendency"]
    sensor_stats = {}
    for sensor in sensor_cols:
        sensor_stats[sensor] = {}
    for trip in trips_db:
        quality_val = trip.route_quality if trip.route_quality else "Unspecified"
        row = excel_map.get(trip.trip_id)
        if row:
            for sensor in sensor_cols:
                value = row.get(sensor, "")
                present = False
                if isinstance(value, str) and value.lower() == "true":
                    present = True
                elif value is True:
                    present = True
                if quality_val not in sensor_stats[sensor]:
                    sensor_stats[sensor][quality_val] = {"present": 0, "total": 0}
                sensor_stats[sensor][quality_val]["total"] += 1
                if present:
                    sensor_stats[sensor][quality_val]["present"] += 1

    # quality_by_os: Distribution of trip quality by Android Version
    quality_by_os = {}
    for trip in trips_db:
        row = excel_map.get(trip.trip_id)
        if row:
            os_ver = row.get("Android Version", "Unknown")
            q = trip.route_quality if trip.route_quality else "Unspecified"
            if os_ver not in quality_by_os:
                quality_by_os[os_ver] = {}
            quality_by_os[os_ver][q] = quality_by_os[os_ver].get(q, 0) + 1

    # manufacturer_quality: Distribution of trip quality by manufacturer
    manufacturer_quality = {}
    for trip in trips_db:
        row = excel_map.get(trip.trip_id)
        if row:
            manu = row.get("manufacturer", "Unknown")
            q = trip.route_quality if trip.route_quality else "Unspecified"
            if manu not in manufacturer_quality:
                manufacturer_quality[manu] = {}
            manufacturer_quality[manu][q] = manufacturer_quality[manu].get(q, 0) + 1

    # carrier_quality: Distribution of trip quality by normalized carrier
    carrier_quality = {}
    for trip in trips_db:
        row = excel_map.get(trip.trip_id)
        if row:
            carrier_val = normalize_carrier(row.get("carrier", "Unknown"))
            q = trip.route_quality if trip.route_quality else "Unspecified"
            if carrier_val not in carrier_quality:
                carrier_quality[carrier_val] = {}
            carrier_quality[carrier_val][q] = carrier_quality[carrier_val].get(q, 0) + 1

    # time_series: Aggregate trip quality counts by date (using 'time' from excel data)
    time_series = {}
    for row in excel_data:
        try:
            time_str = row.get("time", "")
            if time_str:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%Y-%m-%d")
                q = row.get("route_quality", "Unspecified")
                if date_str not in time_series:
                    time_series[date_str] = {}
                time_series[date_str][q] = time_series[date_str].get(q, 0) + 1
        except:
            continue

    session_local.close()
    return render_template(
        "trip_insights.html",
        quality_counts=quality_counts,
        avg_manual=avg_manual,
        avg_calculated=avg_calculated,
        consistent=consistent,
        inconsistent=inconsistent,
        automatic_insights=automatic_insights,
        quality_drilldown=quality_drilldown,
        ram_quality_counts=ram_quality_counts,
        sensor_stats=sensor_stats,
        quality_by_os=quality_by_os,
        manufacturer_quality=manufacturer_quality,
        carrier_quality=carrier_quality,
        time_series=time_series
    )


@app.route("/save_filter", methods=["POST"])
def save_filter():
    """
    Store current filter parameters in session under a filter name.
    """
    filter_name = request.form.get("filter_name")
    filters = {
        "trip_id": request.form.get("trip_id"),
        "route_quality": request.form.get("route_quality"),
        "model": request.form.get("model"),
        "ram": request.form.get("ram"),
        "carrier": request.form.get("carrier"),
        "variance_min": request.form.get("variance_min"),
        "variance_max": request.form.get("variance_max"),
        "driver": request.form.get("driver")
    }
    if filter_name:
        saved = flask_session.get("saved_filters", {})
        saved[filter_name] = filters
        flask_session["saved_filters"] = saved
        flash(f"Filter '{filter_name}' saved.", "success")
    else:
        flash("Please provide a filter name.", "danger")
    return redirect(url_for("trips"))

@app.route("/apply_filter/<filter_name>")
def apply_filter(filter_name):
    """
    Apply a saved filter by redirecting to /trips with the saved query params.
    """
    saved = flask_session.get("saved_filters", {})
    filters = saved.get(filter_name)
    if filters:
        qs = "&".join(f"{key}={value}" for key, value in filters.items() if value)
        return redirect(url_for("trips") + "?" + qs)
    else:
        flash("Saved filter not found.", "danger")
        return redirect(url_for("trips"))

@app.route('/update_date_range', methods=['POST'])
def update_date_range():
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    if not start_date or not end_date:
        return jsonify({'error': 'Both start_date and end_date are required.'}), 400

    # Backup existing consolidated data
    data_file = 'data/data.xlsx'
    backup_dir = 'data/backup'
    if os.path.exists(data_file):
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        backup_file = os.path.join(backup_dir, f"data_{start_date}_{end_date}.xlsx")
        try:
            shutil.move(data_file, backup_file)
        except Exception as e:
            return jsonify({'error': 'Failed to backup data file: ' + str(e)}), 500

    # Run exportmix.py with new dates
    try:
        subprocess.check_call(['python3', 'exportmix.py', '--start-date', start_date, '--end-date', end_date])
    except subprocess.CalledProcessError as e:
        return jsonify({'error': 'Failed to export data: ' + str(e)}), 500

    # Run consolidatemixpanel.py
    try:
        subprocess.check_call(['python3', 'consolidatemixpanel.py'])
    except subprocess.CalledProcessError as e:
        return jsonify({'error': 'Failed to consolidate data: ' + str(e)}), 500

    return jsonify({'message': 'Data updated successfully.'})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
