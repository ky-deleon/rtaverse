from flask import Blueprint, jsonify, request, session, Response
from .auth import is_logged_in
from ..services.database import list_tables
from ..services.preprocessing import process_merge_and_save_to_db, make_display_copy
from ..services.forecasting import rf_monthly_payload, build_forecast_map_html
from ..extensions import get_db_connection, get_engine
from ..services.dashboard_forecasting import run_categorical_forecast, run_numerical_forecast, run_overall_timeseries_forecast
import traceback
import pandas as pd
import numpy as np
import io
import folium
from mysql.connector.errors import ProgrammingError
from datetime import datetime, date, time, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
# In api.py, add these to your existing imports
from ..services.preprocessing import apply_additional_preprocessing

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

api_bp = Blueprint("api", __name__)

# ==== START: NEW ROUTE FOR ADDING A SINGLE RECORD ====
@api_bp.route("/add_record", methods=["POST"])
def add_record():
    if not is_logged_in():
        return jsonify({"success": False, "message": "Not authorized"}), 401

    data = request.get_json()
    table_name = data.get('table_name')
    record = data.get('record') # This is a dictionary of the new record

    if not table_name or not record:
        return jsonify({"success": False, "message": "Table name and record data are required"}), 400

    conn = None
    cur = None
    try:
        # 1. Convert the single record (dict) into a one-row DataFrame
        # This is necessary to run it through your existing preprocessing pipeline
        df = pd.DataFrame([record], index=[0])

        # 2. Run the same preprocessing pipeline as your file uploads
        # This will create all the derived columns (MONTH_SIN, GENDER_CLUSTER, etc.)
        processed_df = apply_additional_preprocessing(df)

        offense_val = None
        if 'OFFENSE' in df.columns:
            offense_val = df.pop('OFFENSE').iloc[0] # Get "1" and remove column
        
        # 2. Run the same preprocessing pipeline as your file uploads
        # This will create all the derived columns (MONTH_SIN, GENDER_CLUSTER, etc.)
        processed_df = apply_additional_preprocessing(df)
        
        # Add the 'OFFENSE' value back to the processed dataframe
        if offense_val is not None:
            processed_df['OFFENSE'] = offense_val
        # --- END OF FIX ---
        
        # --- START: Logic to add DAY_OF_WEEK, YEAR, MONTH, DAY ---
        try:
            # Get the date string from the processed dataframe
            date_str = processed_df.at[0, 'DATE_COMMITTED']
            # Convert string to datetime object
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            
            # Add the new columns to the processed DataFrame
            # The database table has a column named "WEEKDAY", not "DAY_OF_WEEK"
            processed_df['WEEKDAY'] = dt.strftime('%A') # e.g., "Tuesday"
            processed_df['YEAR'] = dt.year
            processed_df['MONTH'] = dt.month
            processed_df['DAY'] = dt.day
            
        except Exception as e:
            print(f"Could not derive date components: {e}")
            processed_df['WEEKDAY'] = None # Add column as None if derivation fails
            processed_df['YEAR'] = None
            processed_df['MONTH'] = None
            processed_df['DAY'] = None
        # --- END: Updated logic ---



        # 3. Save the processed row to the database
        conn = get_db_connection()
        cur = conn.cursor()

        # Get the final list of columns in the database
        cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
        db_cols = [r[0] for r in cur.fetchall()]

        # Prepare the final row for insertion
        final_row_data = {}
        for col in db_cols:
            if col.lower() == 'id':
                continue # Skip auto-increment ID
            if col in processed_df.columns:
                # Get value, convert numpy/pandas types to standard python types
                val = processed_df.iloc[0][col]
                if pd.isna(val) or val is pd.NA:
                    final_row_data[col] = None
                elif isinstance(val, (np.integer, np.int64)):
                    final_row_data[col] = int(val)
                elif isinstance(val, (np.floating, np.float64)):
                    final_row_data[col] = float(val)
                else:
                    final_row_data[col] = str(val)
            else:
                # This handles columns in the DB that weren't in the form
                final_row_data[col] = None 

        cols_to_insert = final_row_data.keys()
        placeholders = ", ".join(["%s"] * len(cols_to_insert))
        values = tuple(final_row_data.values())

        insert_sql = f"INSERT INTO `{table_name}` ({', '.join(f'`{c}`' for c in cols_to_insert)}) VALUES ({placeholders})"

        cur.execute(insert_sql, values)
        new_id = cur.lastrowid # Get the new auto-incremented ID
        conn.commit()

        # 5. Fetch the newly inserted row to return to the frontend
        # This ensures the frontend gets all processed data AND the new ID
        # We use dictionary=True to get a {col: val} dict
        cur.close()
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT * FROM `{table_name}` WHERE `id` = %s", (new_id,))
        new_row_dict = cur.fetchone()
        
        if not new_row_dict:
            raise Exception("Failed to retrieve the newly added record.")

        # Convert date/time/timedelta objects to strings for JSON
        for key, val in new_row_dict.items():
            if isinstance(val, (date, time, timedelta)):
                new_row_dict[key] = str(val)

        # --- START OF FIX ---
        # The frontend table header is "DAY_OF_WEEK", but the DB column is "WEEKDAY".
        # We must create the "DAY_OF_WEEK" key in the returned object
        # so the frontend JavaScript can find and display it.
        if 'WEEKDAY' in new_row_dict:
            new_row_dict['DAY_OF_WEEK'] = new_row_dict['WEEKDAY']
        # --- END OF FIX ---

        return jsonify({"success": True, "message": "Record added successfully!", "new_record": new_row_dict})

    except Exception as e:
        if conn:
            conn.rollback()
        import traceback
        print(traceback.format_exc())
        return jsonify({"success": False, "message": f"An error occurred: {str(e)}"}), 500
    finally:
        if cur:
            cur.close()
        if conn and conn.is_connected():
            conn.close()
# ==== END: NEW ROUTE FOR ADDING A SINGLE RECORD ====

def build_filter_query(cols, req_obj=None):
    # If req_obj is not provided, default to the global request object
    q = req_obj if req_obj is not None else request.args
    where = []
    params = {}

    # Date Range (Format: YYYY-MM)
    start_date_str = q.get("start")
    end_date_str = q.get("end")
    if "DATE_COMMITTED" in cols:
        if start_date_str:
            where.append("`DATE_COMMITTED` >= %(start_date)s")
            params["start_date"] = f"{start_date_str}-01"

        if end_date_str:
            year, month = map(int, end_date_str.split('-'))
            end_of_month_exclusive = (datetime(year, month, 1) + relativedelta(months=1)).strftime('%Y-%m-%d')
            where.append("`DATE_COMMITTED` < %(end_date)s")
            params["end_date"] = end_of_month_exclusive

    # Location
    location_str = (q.get("location") or "").strip()
    if location_str and "BARANGAY" in cols:
        locations = [loc.strip() for loc in location_str.split(',') if loc.strip()]
        if locations:
            loc_placeholders = [f"%(loc_{i})s" for i in range(len(locations))]
            for i, loc in enumerate(locations):
                params[f"loc_{i}"] = loc
            where.append(f"BARANGAY IN ({', '.join(loc_placeholders)})")

    # Gender
    gender_req = (q.get("gender") or "").strip().lower()
    if gender_req:
        gender_cat = next((c for c in ["GENDER", "SEX", "VICTIM_GENDER", "SEX_OF_VICTIM"] if c in cols), None)
        gender_onehot = {
            "male": next((c for c in cols if str(c).upper().endswith("MALE") and str(c).startswith(("GENDER_", "SEX_"))), None),
            "female": next((c for c in cols if str(c).upper().endswith("FEMALE") and str(c).startswith(("GENDER_", "SEX_"))), None),
            "unknown": next((c for c in cols if str(c).upper().endswith("UNKNOWN") and str(c).startswith(("GENDER_", "SEX_"))), None),
            "other": next((c for c in cols if str(c).upper().endswith("OTHER") and str(c).startswith(("GENDER_", "SEX_"))), None),
        }
        if gender_cat:
            where.append(f"UPPER(TRIM(`{gender_cat}`)) = %(gender)s")
            params["gender"] = gender_req.upper()
        elif gender_onehot.get(gender_req):
            where.append(f"COALESCE(`{gender_onehot[gender_req]}`, 0) = 1")

    # Day of Week
    day_raw = [s.strip() for s in (q.get("day_of_week") or "").split(",") if s.strip()]
    if day_raw:
        weekday_expr = "WEEKDAY(`DATE_COMMITTED`)" if "DATE_COMMITTED" in cols else "CAST(`WEEKDAY` AS SIGNED)" if "WEEKDAY" in cols else None
        if weekday_expr:
            name_to_int = {"MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3, "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}
            wd_ints = []
            for item in day_raw:
                tok = item.split(".", 1)[0].strip()
                if tok.isdigit():
                    n = int(tok)
                    if 1 <= n <= 7: wd_ints.append(n - 1)
                else:
                    wd = name_to_int.get(tok.upper())
                    if wd is not None: wd_ints.append(wd)
            if wd_ints:
                day_placeholders = [f"%(day_{i})s" for i, _ in enumerate(wd_ints)]
                for i, day_val in enumerate(wd_ints):
                    params[f"day_{i}"] = day_val
                where.append(f"{weekday_expr} IN ({', '.join(day_placeholders)})")

    # Alcohol
    alcohol_raw = [s.strip() for s in (q.get("alcohol") or "").split(",") if s.strip()]
    if alcohol_raw:
        onehot_any = any(f"ALCOHOL_USED_{v}" in cols for v in ["Yes", "No", "Unknown"])
        cat_col = next((c for c in ["ALCOHOL_USED", "ALCOHOL_INVOLVEMENT", "ALCOHOL", "ALCOHOL_FLAG"] if c in cols), None)
        if onehot_any:
            pieces = [f"COALESCE(`ALCOHOL_USED_{v}`, 0) = 1" for v in alcohol_raw if f"ALCOHOL_USED_{v}" in cols]
            if pieces: where.append(f"({' OR '.join(pieces)})")
        elif cat_col:
            alc_placeholders = [f"%(alc_{i})s" for i, _ in enumerate(alcohol_raw)]
            for i, alc_val in enumerate(alcohol_raw):
                params[f"alc_{i}"] = alc_val.upper()
            where.append(f"UPPER(TRIM(`{cat_col}`)) IN ({', '.join(alc_placeholders)})")

    # Offense Type
    offense_raw = [s.strip() for s in (q.get("offense_type") or "").split(",") if s.strip()]
    if offense_raw:
        offense_col = next((c for c in ["OFFENSE", "OFFENSE_TYPE"] if c in cols), None)
        if offense_col:
            offense_placeholders = [f"%(offense_{i})s" for i, _ in enumerate(offense_raw)]
            for i, offense_val in enumerate(offense_raw):
                params[f"offense_{i}"] = offense_val
            where.append(f"`{offense_col}` IN ({', '.join(offense_placeholders)})")

    # Season Filter
    season_raw = [s.strip().capitalize() for s in (q.get("season") or "").split(",") if s.strip()]
    if season_raw:
        cat_col = next((c for c in ["SEASON_CLUSTER", "SEASON"] if c in cols), None)
        onehot_any = any(f"SEASON_CLUSTER_{v}" in cols for v in ["Dry", "Rainy"])

        if cat_col:
            season_placeholders = [f"%(season_{i})s" for i, _ in enumerate(season_raw)]
            for i, season_val in enumerate(season_raw):
                params[f"season_{i}"] = season_val
            where.append(f"`{cat_col}` IN ({', '.join(season_placeholders)})")
        elif onehot_any:
            pieces = []
            for season_val in season_raw:
                if f"SEASON_CLUSTER_{season_val}" in cols:
                    pieces.append(f"COALESCE(`SEASON_CLUSTER_{season_val}`, 0) = 1")
            if pieces:
                where.append(f"({' OR '.join(pieces)})")

    # Hour Range
    hour_from, hour_to = q.get("hour_from"), q.get("hour_to")
    if hour_from is not None and hour_to is not None:
        expr = None
        if "HOUR_COMMITTED" in cols: expr = "CAST(`HOUR_COMMITTED` AS SIGNED)"
        elif "TIME_COMMITTED" in cols: expr = "HOUR(`TIME_COMMITTED`)"
        elif "DATE_COMMITTED" in cols: expr = "HOUR(`DATE_COMMITTED`)"
        if expr:
            where.append(f"{expr} BETWEEN %(hour_from)s AND %(hour_to)s")
            params["hour_from"] = hour_from
            params["hour_to"] = hour_to

    # Age Range
    age_from, age_to = q.get("age_from"), q.get("age_to")
    age_col = next((c for c in ["AGE", "VICTIM_AGE", "AGE_OF_VICTIM"] if c in cols), None)
    if age_col and age_from is not None and age_to is not None:
        where.append(f"CAST(`{age_col}` AS SIGNED) BETWEEN %(age_from)s AND %(age_to)s")
        params["age_from"] = age_from
        params["age_to"] = age_to

    where_sql = " WHERE " + " AND ".join(where) if where else ""
    return where_sql, params

@api_bp.route("/accidents_by_hour", methods=["GET"])
def accidents_by_hour():
    if not is_logged_in():
        return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        hour_expr = "CAST(`HOUR_COMMITTED` AS SIGNED)" if "HOUR_COMMITTED" in cols else "HOUR(`TIME_COMMITTED`)" if "TIME_COMMITTED" in cols else "HOUR(`DATE_COMMITTED`)"
        
        where_sql, params = build_filter_query(cols)
        
        sql = f"SELECT {hour_expr} AS hr, COUNT(*) AS cnt FROM `{table}` {where_sql} GROUP BY hr ORDER BY hr"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        counts_by_hr = {int(hr): int(cnt) for hr, cnt in rows if hr is not None}

        hour_from_str = request.args.get("hour_from")
        hour_to_str = request.args.get("hour_to")

        if hour_from_str is not None and hour_to_str is not None:
            hour_from = int(hour_from_str)
            hour_to = int(hour_to_str)
        else:
            hour_from = 0
            hour_to = 23
            
        hours = list(range(hour_from, hour_to + 1))
        counts = [counts_by_hr.get(h, 0) for h in hours]
        
        return jsonify(success=True, data={"hours": hours, "counts": counts})
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")

@api_bp.route("/accidents_by_day", methods=["GET"])
def accidents_by_day():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        victim_col = next((c for c in ["VICTIM_COUNT", "VICTIM COUNT"] if c in cols), None)
        weekday_expr = "WEEKDAY(`DATE_COMMITTED`)" if "DATE_COMMITTED" in cols else "CAST(`WEEKDAY` AS SIGNED)"

        where_sql, params = build_filter_query(cols)

        cur.execute(f"SELECT {weekday_expr} AS wd, COUNT(*) AS cnt FROM `{table}` {where_sql} GROUP BY wd ORDER BY wd", params)
        rows_cnt = cur.fetchall()

        avg_map = {}
        if victim_col:
            cur.execute(f"SELECT {weekday_expr} AS wd, AVG(NULLIF(CAST(`{victim_col}` AS DECIMAL(10,2)), 0)) AS avg_v FROM `{table}` {where_sql} GROUP BY wd ORDER BY wd", params)
            for wd, avg_v in cur.fetchall():
                if wd is not None: avg_map[int(wd)] = float(avg_v) if avg_v is not None else 0.0

        cur.close(); conn.close()

        day_labels = ["1. Monday", "2. Tuesday", "3. Wednesday", "4. Thursday", "5. Friday", "6. Saturday", "7. Sunday"]
        counts_by_wd = {int(wd): int(cnt) for wd, cnt in rows_cnt if wd is not None}
        
        return jsonify(success=True, data={
            "days": day_labels,
            "counts": [counts_by_wd.get(i, 0) for i in range(7)],
            "avg_victims": [round(avg_map.get(i, 0.0), 2) for i in range(7)] if victim_col else None
        })
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")


@api_bp.route("/top_barangays", methods=["GET"])
def top_barangays():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        brgy_col = next((c for c in ["BARANGAY", "Barangay", "BRGY"] if c in cols), None)
        if not brgy_col: return jsonify(success=False, message="No BARANGAY column found."), 200

        where_sql, params = build_filter_query(cols)
        
        base_where = f"WHERE `{brgy_col}` IS NOT NULL AND TRIM(`{brgy_col}`) <> ''"
        final_where_sql = base_where + (where_sql.replace("WHERE", " AND") if where_sql else "")

        sql = f"SELECT `{brgy_col}` AS brgy, COUNT(*) AS cnt FROM `{table}` {final_where_sql} GROUP BY brgy ORDER BY cnt DESC LIMIT 10"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); conn.close()

        names = [r[0] for r in rows]
        counts = [int(r[1]) for r in rows]
        return jsonify(success=True, data={"names": names, "counts": counts})
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")


@api_bp.route("/alcohol_by_hour", methods=["GET"])
def alcohol_by_hour():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    model_req = request.args.get('model', 'random_forest') # Correctly define model_req
    horizon = int(request.args.get('horizon', 12))
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        hour_expr = "CAST(`HOUR_COMMITTED` AS SIGNED)" if "HOUR_COMMITTED" in cols else "HOUR(`TIME_COMMITTED`)" if "TIME_COMMITTED" in cols else "HOUR(`DATE_COMMITTED`)" if "DATE_COMMITTED" in cols else None
        if not hour_expr: return jsonify(success=False, message="No hour column found."), 200

        cat_col = next((c for c in ["ALCOHOL_USED", "ALCOHOL_INVOLVEMENT", "ALCOHOL", "ALCOHOL_FLAG"] if c in cols), None)
        one_hot_any = any(f"ALCOHOL_USED_{v}" in cols for v in ["Yes", "No", "Unknown"])
        if not cat_col and not one_hot_any: return jsonify(success=False, message="No alcohol column found."), 200
        
        if one_hot_any:
            yes_expr = f"SUM(COALESCE(`ALCOHOL_USED_Yes`, 0))" if "ALCOHOL_USED_Yes" in cols else "0"
            no_expr = f"SUM(COALESCE(`ALCOHOL_USED_No`, 0))" if "ALCOHOL_USED_No" in cols else "0"
            unk_expr = f"SUM(COALESCE(`ALCOHOL_USED_Unknown`, 0))" if "ALCOHOL_USED_Unknown" in cols else "0"
        else:
            yes_expr = f"SUM(CASE WHEN UPPER(TRIM(`{cat_col}`)) IN ('YES','Y','1','TRUE') THEN 1 ELSE 0 END)"
            no_expr = f"SUM(CASE WHEN UPPER(TRIM(`{cat_col}`)) IN ('NO','N','0','FALSE') THEN 1 ELSE 0 END)"
            unk_expr = f"SUM(CASE WHEN `{cat_col}` IS NULL OR UPPER(TRIM(`{cat_col}`)) NOT IN ('YES','Y','1','TRUE','NO','N','0','FALSE') THEN 1 ELSE 0 END)"
        
        where_sql, params = build_filter_query(cols)
        sql = f"SELECT {hour_expr} AS hr, {yes_expr} AS yes_cnt, {no_expr} AS no_cnt, {unk_expr} AS unk_cnt FROM `{table}` {where_sql} GROUP BY hr ORDER BY hr"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); conn.close()
        
        by_hour = {int(hr): (int(y or 0), int(n or 0), int(u or 0)) for hr, y, n, u in rows if hr is not None}
        hours, yes_pct, no_pct, unk_pct = list(range(24)), [], [], []
        for h in hours:
            y, n, u = by_hour.get(h, (0,0,0))
            total = y + n + u
            yes_pct.append(round(100 * y / total, 2) if total > 0 else 0)
            no_pct.append(round(100 * n / total, 2) if total > 0 else 0)
            unk_pct.append(round(100 * u / total, 2) if total > 0 else 0)
            
        return jsonify(success=True, data={"hours": hours, "yes_pct": yes_pct, "no_pct": no_pct, "unknown_pct": unk_pct})
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")


@api_bp.route("/victims_by_age", methods=["GET"])
def victims_by_age():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        age_num_col = next((c for c in ["AGE", "AGE_YEARS", "AGE_OF_VICTIM"] if c in cols), None)
        age_grp_col = next((c for c in ["AGE_GROUP", "AGE_BUCKET"] if c in cols), None)
        vic_count_col = next((c for c in ["VICTIM_COUNT", "TOTAL_VICTIMS"] if c in cols), None)
        vic_expr = f"COALESCE(CAST(`{vic_count_col}` AS SIGNED), 1)" if vic_count_col else "1"

        where_sql, params = build_filter_query(cols)

        if age_num_col:
            age_bin = f"CASE WHEN `{age_num_col}` IS NULL OR `{age_num_col}` < 0 THEN 'Unknown' WHEN CAST(`{age_num_col}` AS SIGNED) >= 80 THEN '80+' ELSE CONCAT(FLOOR(CAST(`{age_num_col}` AS SIGNED)/10)*10, '–', FLOOR(CAST(`{age_num_col}` AS SIGNED)/10)*10 + 9) END"
            sql = f"SELECT {age_bin} AS age_bin, SUM({vic_expr}) FROM `{table}` {where_sql} GROUP BY age_bin"
        elif age_grp_col:
            sql = f"SELECT COALESCE(NULLIF(TRIM(`{age_grp_col}`), ''), 'Unknown') AS age_bin, SUM({vic_expr}) FROM `{table}` {where_sql} GROUP BY age_bin"
        else:
            return jsonify(success=False, message="No age column found."), 200

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); conn.close()

        def sort_key(lbl):
            if lbl == "Unknown": return (2, 999)
            if lbl.endswith("+"): return (1, int(lbl[:-1]))
            if "–" in lbl: return (0, int(lbl.split("–")[0]))
            return (0, 999)
        
        sorted_rows = sorted(rows, key=lambda r: sort_key(r[0] or "Unknown"))
        labels = [r[0] or "Unknown" for r in sorted_rows]
        values = [int(r[1] or 0) for r in sorted_rows]

        return jsonify(success=True, data={"labels": labels, "values": values})
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")


@api_bp.route("/barangays")
def barangays():
    table = session.get('forecast_table', 'accidents')
    if table not in list_tables(): return jsonify(success=True, barangays=[])
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(f"SELECT DISTINCT BARANGAY FROM `{table}` WHERE BARANGAY IS NOT NULL AND BARANGAY <> '' ORDER BY BARANGAY")
        rows = sorted([str(r[0]).strip() for r in cur.fetchall() if r[0] is not None])
        cur.close(); conn.close()
        return jsonify(success=True, barangays=rows)
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")


@api_bp.route("/set_forecast_source", methods=["POST"])
def set_forecast_source():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized."), 401
    data = request.get_json(silent=True) or {}; table = (data.get('table') or "").strip()
    if not table: return jsonify(success=False, message="Missing table."), 400
    if table not in list_tables(): return jsonify(success=False, message=f'Unknown table "{table}".'), 400
    session['forecast_table'] = table
    return jsonify(success=True, message=f'"{table}" set as forecast source.')


@api_bp.route("/database_data")
def database_data():
    if not is_logged_in():
        return jsonify({"error": "Not authorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        table_name = request.args.get('table')
        if not table_name or table_name not in list_tables():
            return jsonify({"error": "Invalid table specified"}), 400

        draw = int(request.args.get('draw', 0))
        start = int(request.args.get('start', 0))
        length = int(request.args.get('length', 10))
        search_value = request.args.get('search[value]', '').strip()

        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        db_columns = [row['Field'] for row in cursor.fetchall()]
        
        column_map = ['select_col_placeholder'] + db_columns

        order_column_index = int(request.args.get('order[0][column]', 0))
        order_dir = request.args.get('order[0][dir]', 'asc').lower()
        order_column_name = column_map[order_column_index] if order_column_index < len(column_map) else db_columns[0]

        params = []
        where_clauses = []

        if search_value:
            search_likes = []
            for col in db_columns:
                search_likes.append(f"`{col}` LIKE %s")
            where_clauses.append(f"({' OR '.join(search_likes)})")
            params.extend([f"%{search_value}%"] * len(db_columns))

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        order_sql = f"ORDER BY `{order_column_name}` {order_dir}" if order_column_name in db_columns else ""
        limit_sql = "LIMIT %s OFFSET %s"
        params.extend([length, start])

        cursor.execute(f"SELECT COUNT(id) as count FROM `{table_name}`")
        records_total = cursor.fetchone()['count']

        count_query = f"SELECT COUNT(id) as count FROM `{table_name}` {where_sql}"
        cursor.execute(count_query, params[:-2] if search_value else [])
        records_filtered = cursor.fetchone()['count']

        data_query = f"SELECT * FROM `{table_name}` {where_sql} {order_sql} {limit_sql}"
        cursor.execute(data_query, tuple(params))
        data = cursor.fetchall()

        data_as_lists = []
        for row_dict in data:
            data_as_lists.append([str(row_dict.get(col, '')) for col in db_columns])

        return jsonify({
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data_as_lists
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
@api_bp.route("/export_table")
def export_table():
    if not is_logged_in():
        return jsonify({"success": False, "message": "Not authorized"}), 401

    table_name = request.args.get('table')
    export_format = request.args.get('format', 'csv').lower()

    if not table_name:
        return jsonify({"success": False, "message": "Table name is required"}), 400

    if table_name not in list_tables():
        return jsonify({"success": False, "message": f"Table '{table_name}' not found."}), 404

    COLUMNS_TO_EXPORT = [
        "STATION", "BARANGAY", "DATE_COMMITTED", "TIME_COMMITTED", "DAY_OF_WEEK",
        "OFFENSE", "LATITUDE", "LONGITUDE", "ACCIDENT_HOTSPOT", "VICTIM COUNT",
        "SUSPECT COUNT", "AGE", "GENDER_CLUSTER", "ALCOHOL_USED_CLUSTER", "VEHICLE KIND"
    ]

    try:
        engine = get_engine()
        df_full = pd.read_sql_table(table_name, engine)

        df_display = make_display_copy(df_full)

        final_columns = [col for col in COLUMNS_TO_EXPORT if col in df_display.columns]
        df_export = df_display[final_columns]

        safe_filename = "".join(c for c in table_name if c.isalnum() or c in (' ', '_')).rstrip()

        if export_format == 'csv':
            output = df_export.to_csv(index=False, encoding='utf-8')
            return Response(
                output,
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment;filename={safe_filename}.csv"}
            )

        elif export_format == 'excel':
            output = io.BytesIO()
            df_export.to_excel(output, index=False, sheet_name='Data', engine='xlsxwriter')
            output.seek(0)
            return Response(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment;filename={safe_filename}.xlsx"}
            )

        elif export_format == 'pdf':
            if FPDF is None:
                raise ImportError("FPDF (fpdf2) is not installed. Cannot generate PDF.")
            
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_font("Arial", size=7)

            page_width = pdf.w - 2 * pdf.l_margin
            num_columns = len(df_export.columns)
            col_width = page_width / num_columns if num_columns > 0 else page_width

            pdf.set_font('Arial', 'B', 7)
            for col_name in df_export.columns:
                pdf.cell(col_width, 8, str(col_name), border=1, align='C')
            pdf.ln()
            pdf.set_font('Arial', '', 7)

            for _, row in df_export.iterrows():
                for item in row:
                    pdf.cell(col_width, 8, str(item), border=1)
                pdf.ln()

            pdf_output = pdf.output(dest='S').encode('latin-1')
            return Response(
                pdf_output,
                mimetype='application/pdf',
                headers={'Content-Disposition': f'attachment;filename={safe_filename}.pdf'}
            )

        else:
            return jsonify({"success": False, "message": "Invalid format specified"}), 400

    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": f"An error occurred: {e}\n<pre>{traceback.format_exc()}</pre>"}), 500

@api_bp.route("/rf_monthly_forecast", methods=["GET"])
def rf_monthly_forecast():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized."), 401
    table = (request.args.get("table") or "accidents").strip()
    return jsonify(**rf_monthly_payload(table))

@api_bp.route("/forecast/overall_timeseries")
def forecast_overall_timeseries():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    model = request.args.get("model", "random_forest")
    horizon = int(request.args.get("horizon", 12))
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()
        conn.close()

        where_sql, params = build_filter_query(cols)

        result = run_overall_timeseries_forecast(
            table_name=table,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )
        return jsonify(result)
        
    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500

@api_bp.route("/overall_timeseries")
def overall_timeseries():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()

        where_sql, params = build_filter_query(cols)

        sql = f"SELECT DATE_COMMITTED FROM `{table}` {where_sql}"
        df = pd.read_sql_query(sql, conn, params=params, parse_dates=["DATE_COMMITTED"])
        conn.close()

        if df.empty:
            return jsonify(success=True, data={"dates": [], "counts": []})

        ts = df.set_index('DATE_COMMITTED').resample('ME').size().to_frame('count')

        data = {
            "dates": ts.index.strftime('%Y-%m-%d').tolist(),
            "counts": ts['count'].astype(int).tolist()
        }
        
        return jsonify(success=True, data=data)
        
    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500

@api_bp.route("/folium_map")
def folium_map():
    if not is_logged_in():
        return Response("<h4>Not authorized.</h4>", mimetype='text/html')

    table = session.get('forecast_table', 'accidents')
    if table not in list_tables():
        return Response(f"<h4>Error: Table '{table}' not found.</h4>", mimetype='text/html')

    try:
        q = request.args
        now = datetime.now()

        # 1. Get parameters, providing defaults for the current month and hour if they are missing.
        # This makes the map load with a relevant initial view.
        start_str = q.get("start") or now.strftime('%Y-%m')
        end_str = q.get("end") or now.strftime('%Y-%m')
        time_from_str = q.get("time_from") or str(now.hour)
        time_to_str = q.get("time_to") or str(now.hour)

        # 2. For the model training query, we use all filters *except* the date range.
        # This ensures the model is trained on all relevant historical data.
        training_filters = q.copy()
        training_filters.pop("start", None)
        training_filters.pop("end", None)

        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"SHOW COLUMNS FROM `{table}`"))
            cols = {str(row[0]) for row in result.fetchall()}

        # 3. Build the WHERE clause for training data using the non-date filters.
        where_sql, params = build_filter_query(cols, req_obj=training_filters)
        
        # 4. Call the map builder. Pass the training query, but also pass the original (or defaulted)
        # date and time strings so the forecast period and display are correct.
        html = build_forecast_map_html(
            table=table,
            where_sql=where_sql, 
            params=params,       
            start_str=start_str,
            end_str=end_str,
            time_from=time_from_str,
            time_to=time_to_str,
            legacy_time=q.get("legacy_time", "Live"),
            barangay_filter=q.get("barangay")
        )
        return Response(html, mimetype='text/html')

    except Exception as e:
        traceback.print_exc()
        return Response(f"<h4>An unexpected error occurred.</h4><pre>{e}</pre>", mimetype='text/html')

@api_bp.route("/upload_files", methods=["POST"])
def upload_files():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized."), 401
    try:
        file1, file2 = request.files.get("file1"), request.files.get("file2")
        custom_name = (request.form.get("file_name") or "").strip() or "accidents"
        append_mode = (request.form.get("append_mode") or "0").strip() == "1"
        append_target = (request.form.get("append_target") or "").strip()
        if not file1 or not file2: return jsonify(success=False, message="Please select two files."), 400
        table_name = append_target if append_mode and append_target else custom_name
        processed, saved = process_merge_and_save_to_db(file1, file2, table_name=table_name, append=append_mode)

        session['forecast_table'] = table_name

        verb = "Appended to" if append_mode else "Saved to"
        return jsonify(success=True, message=f"Files merged and {verb} '{table_name}'.", rows_saved=int(saved), processed_rows=int(processed))
    except Exception as e:
        print("--- FILE UPLOAD ERROR ---")
        traceback.print_exc()
        print("-------------------------")
        return jsonify(success=False, message=f"An internal error occurred during processing: {e}"), 500

@api_bp.route("/update_rows", methods=["POST"])
def update_rows():
    if not is_logged_in():
        return jsonify({"success": False, "message": "Not authorized"}), 401

    json_data = request.get_json()
    if not json_data:
        return jsonify({"success": False, "message": "Invalid JSON data"}), 400

    table_name = json_data.get('table')
    changes = json_data.get('changes')

    if not table_name or not changes:
        return jsonify({"success": False, "message": "Table name and changes are required"}), 400

    if not isinstance(changes, list):
        return jsonify({"success": False, "message": "Changes must be a list"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        allowed_columns = {row[0] for row in cursor.fetchall()}
        
        if 'id' in allowed_columns:
            allowed_columns.remove('id')

        updates_made = 0
        for change in changes:
            row_id = change.get('id')
            column_name = change.get('column')
            new_value = change.get('new_value')

            if column_name not in allowed_columns:
                raise ValueError(f"Invalid column name '{column_name}' provided. Aborting save.")

            if row_id is None or column_name is None:
                continue

            query = f"UPDATE `{table_name}` SET `{column_name}` = %s WHERE `id` = %s;"
            cursor.execute(query, (new_value, row_id))
            updates_made += cursor.rowcount

        conn.commit()

        return jsonify({"success": True, "message": f"{updates_made} change(s) saved successfully to {table_name}."})

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@api_bp.route("/save_table", methods=["POST"])
def save_table():
    if not is_logged_in(): return jsonify({"message":"Not authorized","success":False}), 401
    json_data = request.get_json()
    if not json_data: return jsonify({"message": "Invalid JSON data", "success": False}), 400
    headers, data = json_data.get('headers', []), json_data.get('data', [])
    if not headers or not data: return jsonify({"message": "No data to save", "success": False}), 400
    return jsonify({"message": "Not fully implemented", "success": False})


@api_bp.route("/delete_file", methods=["POST"])
def delete_file():
    if not is_logged_in(): return jsonify({"success":False,"message":"Not authorized"}), 401
    json_data = request.get_json()
    if not json_data: return jsonify({"success": False, "message": "Invalid JSON data"}), 400
    table_name = json_data.get('table')
    if not table_name: return jsonify({"success": False, "message": "No table specified"}), 400
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`;"); conn.commit()
        cursor.close(); conn.close()
        return jsonify({"success": True, "message": f"Table {table_name} deleted successfully."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
@api_bp.route("/append_table", methods=["POST"])
def append_table():
    if not is_logged_in():
        return jsonify({"success": False, "message": "Not authorized"}), 401
    
    data = request.get_json()
    source_table = data.get('source_table')
    target_table = data.get('target_table')
    delete_source = data.get('delete_source', False)

    if not source_table or not target_table:
        return jsonify({"success": False, "message": "Source and target tables are required"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"SHOW COLUMNS FROM `{source_table}`")
        source_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}
        
        cursor.execute(f"SHOW COLUMNS FROM `{target_table}`")
        target_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}

        cols_to_add = source_cols - target_cols
        if cols_to_add:
            for col in cols_to_add:
                cursor.execute(f"ALTER TABLE `{target_table}` ADD COLUMN `{col}` TEXT NULL")
        
        cursor.execute(f"SHOW COLUMNS FROM `{target_table}`")
        final_target_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}

        common_cols = sorted(list(source_cols.intersection(final_target_cols)))
        if not common_cols:
            raise ValueError("No common columns found between the two tables.")

        cols_sql = ", ".join([f"`{col}`" for col in common_cols])
        
        query = f"INSERT INTO `{target_table}` ({cols_sql}) SELECT {cols_sql} FROM `{source_table}`;"
        cursor.execute(query)
        rows_appended = cursor.rowcount

        if delete_source:
            cursor.execute(f"DROP TABLE `{source_table}`;")

        conn.commit()
        
        session['forecast_table'] = target_table
        
        message = f"Successfully appended {rows_appended} row(s) to '{target_table}'."
        if delete_source:
            message += f" Source file '{source_table}' has been deleted."

        return jsonify({"success": True, "message": message})

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()
    
@api_bp.route("/kpis", methods=["GET"])
def get_kpis():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        where_sql, params = build_filter_query(cols)

        cur.execute(f"SELECT COUNT(*) FROM `{table}` {where_sql}", params)
        total_accidents = cur.fetchone()[0] or 0

        total_victims = 0
        victim_col = next((c for c in ["VICTIM_COUNT", "VICTIM COUNT", "TOTAL_VICTIMS"] if c in cols), None)
        if victim_col:
            cur.execute(f"SELECT SUM(`{victim_col}`) FROM `{table}` {where_sql}", params)
            total_victims = cur.fetchone()[0] or 0

        alcohol_cases = 0
        if "ALCOHOL_USED_Yes" in cols:
            cur.execute(f"SELECT SUM(COALESCE(`ALCOHOL_USED_Yes`, 0)) FROM `{table}` {where_sql}", params)
            alcohol_cases = cur.fetchone()[0] or 0
        else:
            alc_cat_col = next((c for c in ["ALCOHOL_USED", "ALCOHOL_INVOLVEMENT"] if c in cols), None)
            if alc_cat_col:
                sql = f"SELECT COUNT(*) FROM `{table}` {where_sql} AND UPPER(TRIM(`{alc_cat_col}`)) = 'YES'"
                cur.execute(sql, params)
                alcohol_cases = cur.fetchone()[0] or 0
        
        cur.close()
        conn.close()

        avg_victims_per_accident = np.divide(total_victims, total_accidents) if total_accidents > 0 else 0
        alcohol_involvement_rate = np.divide(alcohol_cases, total_accidents) if total_accidents > 0 else 0

        return jsonify(success=True, data={
            "total_accidents": int(total_accidents),
            "total_victims": int(total_victims),
            "avg_victims_per_accident": float(avg_victims_per_accident),
            "alcohol_involvement_rate": float(alcohol_involvement_rate),
            "alcohol_cases": int(alcohol_cases)
        })

    except ProgrammingError as e:
        if e.errno == 1146:
            return jsonify(success=False, error_type="NO_TABLE", message=f"Data table '{table}' not found. Please upload data on the Database page."), 404
        else:
            return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500


@api_bp.route("/offense_types", methods=["GET"])
def get_offense_types():
    if not is_logged_in(): return jsonify(success=False, message="Not authorized"), 401
    table = session.get("forecast_table", "accidents")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        
        offense_col = next((c for c in ["OFFENSE", "OFFENSE_TYPE", "CRIME_TYPE"] if c in cols), None)
        if not offense_col:
            return jsonify(success=False, message="No offense type column found.")

        where_sql, params = build_filter_query(cols)
        
        sql = f"SELECT `{offense_col}`, COUNT(*) as cnt FROM `{table}` {where_sql} GROUP BY `{offense_col}` ORDER BY cnt DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify(success=True, data={
            "labels": [r[0] for r in rows],
            "values": [r[1] for r in rows]
        })
    except Exception as e:
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")

@api_bp.route("/by_season", methods=["GET"])
def get_by_season():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        
        season_col = next((c for c in ["SEASON_CLUSTER", "SEASON"] if c in cols), None)
        if not season_col:
            return jsonify(success=False, message="No season column found in the table.")

        where_sql, params = build_filter_query(cols)
        
        sql = f"SELECT `{season_col}`, COUNT(*) as cnt FROM `{table}` {where_sql} GROUP BY `{season_col}` ORDER BY `{season_col}`"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify(success=True, data={
            "labels": [r[0] for r in rows],
            "values": [r[1] for r in rows]
        })
    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>")

@api_bp.route("/gender_kpis", methods=["GET"])
def get_gender_kpis():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True) 
        
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r['Field']) for r in cur.fetchall()}

        where_sql, params = build_filter_query(cols)

        male_col = next((c for c in cols if 'GENDER_MALE' in c.upper()), None)
        unknown_col = next((c for c in cols if 'GENDER_UNKNOWN' in c.upper()), None)
        
        if not male_col or not unknown_col:
             return jsonify(success=False, message="Required gender columns (e.g., GENDER_Male, GENDER_Unknown) not found in the table."), 500

        query = f"""
            SELECT
                SUM(CASE WHEN `{male_col}` = 1 THEN 1 ELSE 0 END) as male_count,
                SUM(CASE WHEN `{male_col}` = 0 AND `{unknown_col}` = 0 THEN 1 ELSE 0 END) as female_count,
                SUM(CASE WHEN `{unknown_col}` = 1 THEN 1 ELSE 0 END) as unknown_count
            FROM `{table}`
        """

        if where_sql:
            query += where_sql

        cur.execute(query, params)
        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": True, "data": {"male_count": 0, "female_count": 0, "unknown_count": 0}})

        data = {
            "male_count": result.get('male_count') or 0,
            "female_count": result.get('female_count') or 0,
            "unknown_count": result.get('unknown_count') or 0
        }

        return jsonify({"success": True, "data": data})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if 'conn' in locals() and conn and conn.is_connected():
            conn.close()

@api_bp.route("/forecast/hourly", methods=["GET"])
def forecast_hourly():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model = request.args.get('model', 'random_forest')
    try:
        horizon = int(request.args.get('horizon', 12))
    except (ValueError, TypeError):
        horizon = 12

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()
        conn.close()

        where_sql, params = build_filter_query(cols)
        
        hour_expr = "CAST(`HOUR_COMMITTED` AS SIGNED)" if "HOUR_COMMITTED" in cols else \
                    "HOUR(`TIME_COMMITTED`)" if "TIME_COMMITTED" in cols else \
                    "HOUR(`DATE_COMMITTED`)"
        
        if not hour_expr.startswith("CAST") and not hour_expr.startswith("HOUR"):
             return jsonify(success=False, message="No suitable hour/time column found for forecasting.")

        result = run_categorical_forecast(
            table_name=table,
            grouping_key=hour_expr,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )
        
        return jsonify(**result)

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print("--- FORECASTING ERROR ---")
        print(error_trace)
        print("-------------------------")
        return jsonify(success=False, message=f"<pre>{error_trace}</pre>"), 500
    
@api_bp.route("/forecast/day_of_week", methods=["GET"])
def forecast_day_of_week():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model_req = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()
        conn.close()

        victim_col = next((c for c in ["VICTIM_COUNT", "VICTIM COUNT", "TOTAL_VICTIMS"] if c in cols), None)
        if not victim_col:
            return jsonify(success=False, message="VICTIM_COUNT column not found in table.")

        where_sql, params = build_filter_query(cols)
        weekday_expr = "WEEKDAY(`DATE_COMMITTED`)" if "DATE_COMMITTED" in cols else "CAST(`WEEKDAY` AS SIGNED)"
        
        count_result = run_categorical_forecast(
            table_name=table, grouping_key=weekday_expr, model_type=model_req,
            forecast_horizon=horizon, where_sql=where_sql, params=params
        )
        
        victim_result = run_numerical_forecast(
            table_name=table, grouping_key=weekday_expr, target_column=victim_col,
            model_type=model_req, forecast_horizon=horizon, where_sql=where_sql, params=params
        )

        if not count_result.get("success") or not victim_result.get("success"):
            return jsonify(success=False, message="Failed to generate one or both forecasts.")

        day_map = {0: "1. Monday", 1: "2. Tuesday", 2: "3. Wednesday", 3: "4. Thursday", 4: "5. Friday", 5: "6. Saturday", 6: "7. Sunday"}
        labels = [day_map.get(int(label)) for label in count_result["data"]["labels"]]

        h_counts = np.array(count_result["data"]["historical"])
        f_counts = np.array(count_result["data"]["forecast"])
        h_victims = np.array(victim_result["historical"])
        f_victims = np.array(victim_result["forecast"])

        h_avg = np.divide(h_victims, h_counts, out=np.zeros_like(h_victims, dtype=float), where=h_counts!=0)
        f_avg = np.divide(f_victims, f_counts, out=np.zeros_like(f_victims, dtype=float), where=f_counts!=0)

        model_display_name = 'Random Forest'
        if model_req == 'adaboost':
            model_display_name = 'Decision Tree'

        final_data = {
            "labels": labels,
            "historical_counts": h_counts.tolist(),
            "forecast_counts": f_counts.tolist(),
            "historical_avg_victims": np.round(h_avg, 2).tolist(),
            "forecast_avg_victims": np.round(f_avg, 2).tolist(),
            "model_used": model_display_name,
            "horizon": horizon
        }
        
        return jsonify(success=True, data=final_data)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500
    
@api_bp.route("/forecast/top_barangays", methods=["GET"])
def forecast_top_barangays():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        brgy_col = next((c for c in ["BARANGAY", "Barangay", "BRGY"] if c in cols), None)
        if not brgy_col:
            cur.close(); conn.close()
            return jsonify(success=False, message="No BARANGAY column found."), 200

        where_sql, params = build_filter_query(cols)
        
        top_10_query = f"""
            SELECT `{brgy_col}` FROM `{table}` {where_sql}
            GROUP BY `{brgy_col}` ORDER BY COUNT(*) DESC LIMIT 10
        """
        cur.execute(top_10_query, params)
        top_10_barangays = [row[0] for row in cur.fetchall()]
        cur.close(); conn.close()

        if not top_10_barangays:
            return jsonify(success=False, message="Not enough data to determine top barangays for forecasting.")

        brgy_placeholders = []
        for i, brgy_name in enumerate(top_10_barangays):
            key = f"brgy_{i}"
            brgy_placeholders.append(f"%({key})s")
            params[key] = brgy_name
            
        brgy_in_clause = ", ".join(brgy_placeholders)
        
        if where_sql:
            where_sql += f" AND `{brgy_col}` IN ({brgy_in_clause})"
        else:
            where_sql = f"WHERE `{brgy_col}` IN ({brgy_in_clause})"

        result = run_categorical_forecast(
            table_name=table,
            grouping_key=brgy_col,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )
        
        return jsonify(**result)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500

@api_bp.route("/forecast/alcohol_by_hour", methods=["GET"])
def forecast_alcohol_by_hour():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model_req = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close(); conn.close()

        hour_expr = "CAST(`HOUR_COMMITTED` AS SIGNED)" if "HOUR_COMMITTED" in cols else \
                    "HOUR(`TIME_COMMITTED`)" if "TIME_COMMITTED" in cols else \
                    "HOUR(`DATE_COMMITTED`)"
        
        alc_cat_col = next((c for c in ["ALCOHOL_USED_CLUSTER", "ALCOHOL_USED", "ALCOHOL_INVOLVEMENT"] if c in cols), None)
        
        if not alc_cat_col:
            return jsonify(success=False, message="A categorical alcohol column (e.g., 'ALCOHOL_USED_CLUSTER') is required for this forecast.")

        base_where_sql, base_params = build_filter_query(cols)

        results = {}
        for status in ["Yes", "No", "Unknown"]:
            params = base_params.copy()
            if base_where_sql:
                where_sql = base_where_sql + f" AND `{alc_cat_col}` = %(alc_status)s"
            else:
                where_sql = f"WHERE `{alc_cat_col}` = %(alc_status)s"
            params['alc_status'] = status
            results[status] = run_categorical_forecast(
                table_name=table, grouping_key=hour_expr, model_type=model_req,
                forecast_horizon=horizon, where_sql=where_sql, params=params
            )

        df_hist = pd.DataFrame(index=range(24))
        df_fcst = pd.DataFrame(index=range(24))

        for status in ["Yes", "No", "Unknown"]:
            if results[status].get("success") and results[status]["data"]["labels"]:
                res_data = results[status]["data"]
                s_hist = pd.Series(res_data["historical"], index=res_data["labels"], name=f"h_{status.lower()}")
                s_fcst = pd.Series(res_data["forecast"], index=res_data["labels"], name=f"f_{status.lower()}")
                df_hist = df_hist.join(s_hist)
                df_fcst = df_fcst.join(s_fcst)

        df_hist = df_hist.fillna(0).astype(int)
        df_fcst = df_fcst.fillna(0).astype(int)
        
        h_yes = df_hist.get("h_yes", pd.Series(0, index=range(24))).values
        h_no = df_hist.get("h_no", pd.Series(0, index=range(24))).values
        h_unk = df_hist.get("h_unknown", pd.Series(0, index=range(24))).values

        f_yes = df_fcst.get("f_yes", pd.Series(0, index=range(24))).values
        f_no = df_fcst.get("f_no", pd.Series(0, index=range(24))).values
        f_unk = df_fcst.get("f_unknown", pd.Series(0, index=range(24))).values

        h_total = h_yes + h_no + h_unk
        f_total = f_yes + f_no + f_unk

        h_yes_pct = np.divide(h_yes * 100, h_total, out=np.zeros_like(h_total, dtype=float), where=h_total!=0)
        f_yes_pct = np.divide(f_yes * 100, f_total, out=np.zeros_like(f_total, dtype=float), where=f_total!=0)
        h_no_pct = np.divide(h_no * 100, h_total, out=np.zeros_like(h_total, dtype=float), where=h_total!=0)
        f_no_pct = np.divide(f_no * 100, f_total, out=np.zeros_like(f_total, dtype=float), where=f_total!=0)
        h_unk_pct = np.divide(h_unk * 100, h_total, out=np.zeros_like(h_total, dtype=float), where=h_total!=0)
        f_unk_pct = np.divide(f_unk * 100, f_total, out=np.zeros_like(f_total, dtype=float), where=f_total!=0)

        model_display_name = 'Random Forest'
        if model_req == 'adaboost':
            model_display_name = 'Decision Tree'

        final_data = {
            "hours": list(range(24)),
            "historical_yes_pct": np.round(h_yes_pct, 2).tolist(),
            "forecast_yes_pct": np.round(f_yes_pct, 2).tolist(),
            "historical_no_pct": np.round(h_no_pct, 2).tolist(),
            "forecast_no_pct": np.round(f_no_pct, 2).tolist(),
            "historical_unknown_pct": np.round(h_unk_pct, 2).tolist(),
            "forecast_unknown_pct": np.round(f_unk_pct, 2).tolist(),
            "model_used": model_req,
            "horizon": horizon
        }
        
        return jsonify(success=True, data=final_data)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500

@api_bp.route("/forecast/victims_by_age", methods=["GET"])
def forecast_victims_by_age():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model_req = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close(); conn.close()

        age_num_col = next((c for c in ["AGE", "VICTIM_AGE", "AGE_OF_VICTIM", "AGE_YEARS"] if c in cols), None)
        vic_count_col = next((c for c in ["VICTIM COUNT", "VICTIM_COUNT", "TOTAL_VICTIMS"] if c in cols), None)

        if not age_num_col or not vic_count_col:
            error_msg = (
                f"Required AGE or VICTIM_COUNT columns not found for forecast. "
                f"Age column found: '{age_num_col}'. "
                f"Victim count column found: '{vic_count_col}'. "
                f"Available columns in table '{table}': {sorted(list(cols))}"
            )
            return jsonify(success=False, message=error_msg)

        age_bin_expr = f"""
            CASE 
                WHEN `{age_num_col}` IS NULL OR `{age_num_col}` < 10 THEN '0-9'
                WHEN CAST(`{age_num_col}` AS SIGNED) >= 80 THEN '80+' 
                ELSE CONCAT(FLOOR(CAST(`{age_num_col}` AS SIGNED)/10)*10, '-', FLOOR(CAST(`{age_num_col}` AS SIGNED)/10)*10 + 9) 
            END
        """
        age_bin_where_condition = f" `{age_num_col}` IS NOT NULL "

        where_sql, params = build_filter_query(cols)
        if where_sql:
            where_sql += f" AND {age_bin_where_condition}"
        else:
            where_sql = f"WHERE {age_bin_where_condition}"
        
        result = run_numerical_forecast(
            table_name=table,
            grouping_key=age_bin_expr,
            target_column=vic_count_col,
            model_type=model_req,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )

        if result.get("success"):
            def sort_key(label):
                if label == "Unknown": return (2, 999)
                if label.endswith("+"): return (1, int(label[:-1]))
                if "-" in label: return (0, int(label.split("-")[0]))
                return (0, 999)

            zipped_data = sorted(
                zip(result["labels"], result["historical"], result["forecast"]),
                key=lambda x: sort_key(x[0])
            )
            
            if zipped_data:
                labels, historical, forecast = zip(*zipped_data)
                result["labels"] = list(labels)
                result["historical"] = list(historical)
                result["forecast"] = list(forecast)
                
        model_display_name = 'Random Forest'
        if model_req == 'adaboost':
            model_display_name = 'Decision Tree'
        
        final_payload = {
            "success": result.get("success"),
            "data": {
                "labels": result.get("labels", []),
                "historical": result.get("historical", []),
                "forecast": result.get("forecast", []),
                "model_used": model_display_name,
                "horizon": horizon
            } if result.get("success") else None,
            "message": result.get("message")
        }

        return jsonify(final_payload)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500
    
@api_bp.route("/forecast/offense_types", methods=["GET"])
def forecast_offense_types():
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close(); conn.close()

        offense_col = next((c for c in ["OFFENSE", "OFFENSE_TYPE", "CRIME_TYPE"] if c in cols), None)
        if not offense_col:
            return jsonify(success=False, message="No offense type column found.")

        where_sql, params = build_filter_query(cols)
        
        result = run_categorical_forecast(
            table_name=table,
            grouping_key=offense_col,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )
        
        return jsonify(**result)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500

@api_bp.route("/forecast/by_season", methods=["GET"])
def forecast_by_season():
    if not is_logged_in():
        return jsonify(success=False, message="Not authorized"), 401

    table = session.get("forecast_table", "accidents")
    model = request.args.get('model', 'random_forest')
    horizon = int(request.args.get('horizon', 12))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()
        conn.close()

        season_col = next((c for c in ["SEASON_CLUSTER", "SEASON"] if c in cols), None)
        if not season_col:
            return jsonify(success=False, message="No season column (e.g., SEASON_CLUSTER) found.")

        where_sql, params = build_filter_query(cols)

        result = run_categorical_forecast(
            table_name=table,
            grouping_key=season_col,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )

        return jsonify(**result)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500
    
@api_bp.route("/delete_rows", methods=["POST"])
def delete_rows():
    if not is_logged_in(): 
        return jsonify({"success": False, "message": "Not authorized"}), 401
    
    json_data = request.get_json()
    if not json_data:
        return jsonify({"success": False, "message": "Invalid JSON data"}), 400
        
    table_name = json_data.get('table')
    row_ids = json_data.get('row_ids')

    if not table_name or not row_ids:
        return jsonify({"success": False, "message": "Table name and row IDs are required"}), 400
        
    if not isinstance(row_ids, list) or not all(isinstance(i, int) for i in row_ids):
        return jsonify({"success": False, "message": "row_ids must be a list of integers"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        placeholders = ', '.join(['%s'] * len(row_ids))
        query = f"DELETE FROM `{table_name}` WHERE `id` IN ({placeholders});"
        
        cursor.execute(query, tuple(row_ids))
        rows_deleted = cursor.rowcount
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({"success": True, "message": f"{rows_deleted} row(s) deleted successfully from {table_name}."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500