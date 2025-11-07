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
from datetime import datetime
from dateutil.relativedelta import relativedelta

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

api_bp = Blueprint("api", __name__)


def build_filter_query(cols, req_obj=None):
    q = (req_obj or request).args
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

# --- START OF FIX: This entire function is replaced ---
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

        # Robustly get the hour range for the chart's x-axis
        hour_from_str = request.args.get("hour_from")
        hour_to_str = request.args.get("hour_to")

        # If a time filter is active, use that range; otherwise, use the full 24-hour day.
        # This prevents errors from trying to convert `None` to an integer.
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

# In api.py

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

        # --- DataTables Request Parsing ---
        draw = int(request.args.get('draw', 0))
        start = int(request.args.get('start', 0))
        length = int(request.args.get('length', 10))
        search_value = request.args.get('search[value]', '').strip()

        # Get column names to map sorting index to actual column name
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        db_columns = [row['Field'] for row in cursor.fetchall()]
        
        # Add a placeholder for the select checkbox column at the start
        # This aligns the sorting index from the request with your DB columns
        column_map = ['select_col_placeholder'] + db_columns

        order_column_index = int(request.args.get('order[0][column]', 0))
        order_dir = request.args.get('order[0][dir]', 'asc').lower()
        order_column_name = column_map[order_column_index] if order_column_index < len(column_map) else db_columns[0]

        # --- Database Query Construction ---
        params = []
        where_clauses = []

        # Global search logic
        if search_value:
            search_likes = []
            for col in db_columns:
                # Search only in text-like columns for efficiency
                search_likes.append(f"`{col}` LIKE %s")
            where_clauses.append(f"({' OR '.join(search_likes)})")
            # Add the search term for each column being searched
            params.extend([f"%{search_value}%"] * len(db_columns))

        # Final query parts
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        order_sql = f"ORDER BY `{order_column_name}` {order_dir}" if order_column_name in db_columns else ""
        limit_sql = "LIMIT %s OFFSET %s"
        params.extend([length, start])

        # --- Execute Queries ---
        # Get total records without filtering
        cursor.execute(f"SELECT COUNT(id) as count FROM `{table_name}`")
        records_total = cursor.fetchone()['count']

        # Get total records with filtering
        count_query = f"SELECT COUNT(id) as count FROM `{table_name}` {where_sql}"
        # Use only the search parameters for the filtered count
        cursor.execute(count_query, params[:-2] if search_value else [])
        records_filtered = cursor.fetchone()['count']

        # Get the paginated and filtered data
        data_query = f"SELECT * FROM `{table_name}` {where_sql} {order_sql} {limit_sql}"
        cursor.execute(data_query, tuple(params))
        data = cursor.fetchall()

        # Convert all values to strings for robust rendering
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
            
# ADD THE NEW ROUTE AND FUNCTION BELOW
@api_bp.route("/export_table")
def export_table():
    """
    Exports data from a specified table to CSV, Excel, or PDF format.
    """
    if not is_logged_in():
        return jsonify({"success": False, "message": "Not authorized"}), 401

    table_name = request.args.get('table')
    export_format = request.args.get('format', 'csv').lower()

    if not table_name:
        return jsonify({"success": False, "message": "Table name is required"}), 400

    if table_name not in list_tables():
        return jsonify({"success": False, "message": f"Table '{table_name}' not found."}), 404

    # Define the specific columns to be included in the export
    COLUMNS_TO_EXPORT = [
        "STATION", "BARANGAY", "DATE_COMMITTED", "TIME_COMMITTED", "DAY_OF_WEEK",
        "OFFENSE", "LATITUDE", "LONGITUDE", "ACCIDENT_HOTSPOT", "VICTIM COUNT",
        "SUSPECT COUNT", "AGE", "GENDER_CLUSTER", "ALCOHOL_USED_CLUSTER", "VEHICLE KIND"
    ]

    try:
        engine = get_engine()
        df_full = pd.read_sql_table(table_name, engine)

        # Generate derived columns (like DAY_OF_WEEK, etc.)
        df_display = make_display_copy(df_full)

        # Filter the DataFrame to only include existing columns from our export list
        final_columns = [col for col in COLUMNS_TO_EXPORT if col in df_display.columns]
        df_export = df_display[final_columns]

        # Sanitize the table name for use as a filename
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
            # Use xlsxwriter engine for modern .xlsx format
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
            
            pdf = FPDF(orientation='L', unit='mm', format='A4') # Landscape
            pdf.add_page()
            pdf.set_font("Arial", size=7)

            page_width = pdf.w - 2 * pdf.l_margin
            num_columns = len(df_export.columns)
            col_width = page_width / num_columns if num_columns > 0 else page_width

            # Table Header
            pdf.set_font('Arial', 'B', 7)
            for col_name in df_export.columns:
                pdf.cell(col_width, 8, str(col_name), border=1, align='C')
            pdf.ln()
            pdf.set_font('Arial', '', 7)

            # Table Rows
            for _, row in df_export.iterrows():
                for item in row:
                    pdf.cell(col_width, 8, str(item), border=1)
                pdf.ln()

            # The output must be encoded for the Response object
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

        # Use pandas to easily resample the data by month
        sql = f"SELECT DATE_COMMITTED FROM `{table}` {where_sql}"
        df = pd.read_sql_query(sql, conn, params=params, parse_dates=["DATE_COMMITTED"])
        conn.close()

        if df.empty:
            return jsonify(success=True, data={"dates": [], "counts": []})

        # Resample to get monthly counts
        ts = df.set_index('DATE_COMMITTED').resample('ME').size().to_frame('count')

        # Format for JSON response
        data = {
            "dates": ts.index.strftime('%Y-%m-%d').tolist(),
            "counts": ts['count'].astype(int).tolist()
        }
        
        return jsonify(success=True, data=data)
        
    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500



import traceback


@api_bp.route("/folium_map")
def folium_map():
    # This route now ONLY gathers filter parameters and passes them on.
    # All data loading and filtering logic is now handled inside build_forecast_map_html.
    
    table = session.get('forecast_table', 'accidents')
    if table not in list_tables():
        # Return a simple HTML response for "table not found"
        return Response("<h4>No data: The selected table was not found.</h4>", mimetype='text/html')
        
    try:
        q = request.args
        
        # Pass all filter parameters directly to the forecasting function
        html = build_forecast_map_html(
            table=table,
            start_str=q.get("start"),
            end_str=q.get("end"),
            time_from=q.get("time_from"),
            time_to=q.get("time_to"),
            legacy_time=q.get("legacy_time", "Live"), # Default to "Live" if not provided
            barangay_filter=q.get("barangay")
        )
        return Response(html, mimetype='text/html')

    except Exception as e:
        traceback.print_exc()
        return Response(f"<h4>An unexpected error occurred while generating the map.</h4><pre>{e}</pre>", mimetype='text/html')

# In api.py

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
        # Return a more helpful error message to the user
        return jsonify(success=False, message=f"An internal error occurred during processing: {e}"), 500

# --- Add this new route to api.py ---

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

        # Get a list of valid column names from the table to prevent SQL injection
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        allowed_columns = {row[0] for row in cursor.fetchall()}
        
        # You cannot update the primary key
        if 'id' in allowed_columns:
            allowed_columns.remove('id')

        updates_made = 0
        for change in changes:
            row_id = change.get('id')
            column_name = change.get('column')
            new_value = change.get('new_value')

            # --- Security Check ---
            if column_name not in allowed_columns:
                # If an invalid column is provided, abort the whole transaction
                raise ValueError(f"Invalid column name '{column_name}' provided. Aborting save.")

            if row_id is None or column_name is None:
                continue # Skip malformed change objects

            # Use parameterized queries to safely update the database
            query = f"UPDATE `{table_name}` SET `{column_name}` = %s WHERE `id` = %s;"
            cursor.execute(query, (new_value, row_id))
            updates_made += cursor.rowcount

        # If all updates are successful, commit them as a single transaction
        conn.commit()

        return jsonify({"success": True, "message": f"{updates_made} change(s) saved successfully to {table_name}."})

    except Exception as e:
        # If any error occurs, roll back all changes from this request
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
    # ... (code continues)
    return jsonify({"message": "Not fully implemented", "success": False}) # Placeholder for brevity


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
    
# In api.py, add this new route. A good place is after the /delete_file route.

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

        # 1. Get columns for both tables to find common columns
        cursor.execute(f"SHOW COLUMNS FROM `{source_table}`")
        source_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}
        
        cursor.execute(f"SHOW COLUMNS FROM `{target_table}`")
        target_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}

        # Add any missing columns from source to target
        cols_to_add = source_cols - target_cols
        if cols_to_add:
            # You need a way to determine the SQL type, let's reuse a helper if available
            # For simplicity, we'll default to TEXT here, but a robust solution would map types.
            for col in cols_to_add:
                 # This is a simplification. A full implementation would need _sql_type from preprocessing.py
                cursor.execute(f"ALTER TABLE `{target_table}` ADD COLUMN `{col}` TEXT NULL")
        
        # Re-fetch target columns after potential alteration
        cursor.execute(f"SHOW COLUMNS FROM `{target_table}`")
        final_target_cols = {row[0] for row in cursor.fetchall() if row[0].lower() != 'id'}

        # 2. Find intersection of columns for the INSERT statement
        common_cols = sorted(list(source_cols.intersection(final_target_cols)))
        if not common_cols:
            raise ValueError("No common columns found between the two tables.")

        cols_sql = ", ".join([f"`{col}`" for col in common_cols])
        
        # 3. Perform the append operation
        query = f"INSERT INTO `{target_table}` ({cols_sql}) SELECT {cols_sql} FROM `{source_table}`;"
        cursor.execute(query)
        rows_appended = cursor.rowcount

        # 4. Optionally, delete the source table
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
        
        # 1. Get all column names from the table
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}

        # 2. Use the central filter builder to get the correct WHERE clause and parameters
        where_sql, params = build_filter_query(cols)

        # 3. Calculate Total Accidents (this part was likely working already)
        cur.execute(f"SELECT COUNT(*) FROM `{table}` {where_sql}", params)
        total_accidents = cur.fetchone()[0] or 0

        # 4. Calculate Total Victims
        total_victims = 0
        victim_col = next((c for c in ["VICTIM_COUNT", "VICTIM COUNT", "TOTAL_VICTIMS"] if c in cols), None)
        if victim_col:
            # Use NULLIF to handle zeros correctly if you want to exclude them, or just SUM directly
            cur.execute(f"SELECT SUM(`{victim_col}`) FROM `{table}` {where_sql}", params)
            # The result can be None if no rows match, so we handle that.
            total_victims = cur.fetchone()[0] or 0

        # 5. Calculate Alcohol Involvement
        alcohol_cases = 0
        # Check for one-hot encoded column first
        if "ALCOHOL_USED_Yes" in cols:
            cur.execute(f"SELECT SUM(COALESCE(`ALCOHOL_USED_Yes`, 0)) FROM `{table}` {where_sql}", params)
            alcohol_cases = cur.fetchone()[0] or 0
        else:
            # Fallback to a categorical column
            alc_cat_col = next((c for c in ["ALCOHOL_USED", "ALCOHOL_INVOLVEMENT"] if c in cols), None)
            if alc_cat_col:
                # Build a query that counts 'Yes' values, ignoring case.
                sql = f"SELECT COUNT(*) FROM `{table}` {where_sql} AND UPPER(TRIM(`{alc_cat_col}`)) = 'YES'"
                cur.execute(sql, params)
                alcohol_cases = cur.fetchone()[0] or 0
        
        cur.close()
        conn.close()

        # 6. Perform final calculations safely in Python
        # Use np.divide for safe division to prevent "division by zero" errors
        avg_victims_per_accident = np.divide(total_victims, total_accidents) if total_accidents > 0 else 0
        alcohol_involvement_rate = np.divide(alcohol_cases, total_accidents) if total_accidents > 0 else 0

        # 7. Send the complete data payload to the frontend
        return jsonify(success=True, data={
            "total_accidents": int(total_accidents),
            "total_victims": int(total_victims),
            "avg_victims_per_accident": float(avg_victims_per_accident),
            "alcohol_involvement_rate": float(alcohol_involvement_rate) # The frontend will multiply by 100
        })

    except ProgrammingError as e:
        # Check for the specific "Table doesn't exist" error code
        if e.errno == 1146:
            return jsonify(success=False, error_type="NO_TABLE", message=f"Data table '{table}' not found. Please upload data on the Database page."), 404
        else:
            # For other database errors, it's still useful to see the traceback during development
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
        
        # Adjust 'OFFENSE_TYPE' to match your actual column name
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

@api_bp.route("/gender_kpis", methods=["GET"])
def get_gender_kpis():
    """
    Provides KPI counts for Male, Female, and Unknown genders based on filters.
    """
    if not is_logged_in(): 
        return jsonify(success=False, message="Not authorized"), 401
        
    table = session.get("forecast_table", "accidents")
    
    try:
        conn = get_db_connection()
        # Use dictionary=True to access results by column name
        cur = conn.cursor(dictionary=True) 
        
        # 1. Get all column names from the table
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r['Field']) for r in cur.fetchall()}

        # 2. Use the central filter builder to get the correct WHERE clause and parameters
        where_sql, params = build_filter_query(cols)

        # 3. Dynamically find the one-hot encoded gender columns
        male_col = next((c for c in cols if 'GENDER_MALE' in c.upper()), None)
        unknown_col = next((c for c in cols if 'GENDER_UNKNOWN' in c.upper()), None)
        
        if not male_col or not unknown_col:
             return jsonify(success=False, message="Required gender columns (e.g., GENDER_Male, GENDER_Unknown) not found in the table."), 500

        # 4. Build the query to count each gender category
        query = f"""
            SELECT
                SUM(CASE WHEN `{male_col}` = 1 THEN 1 ELSE 0 END) as male_count,
                SUM(CASE WHEN `{male_col}` = 0 AND `{unknown_col}` = 0 THEN 1 ELSE 0 END) as female_count,
                SUM(CASE WHEN `{unknown_col}` = 1 THEN 1 ELSE 0 END) as unknown_count
            FROM `{table}`
        """

        # Append the WHERE clause if filters are present
        if where_sql:
            query += where_sql

        cur.execute(query, params)
        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": True, "data": {"male_count": 0, "female_count": 0, "unknown_count": 0}})

        # Prepare the final data, ensuring nulls are converted to 0
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
        # 1. Get database columns and build the powerful filter query
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = {str(r[0]) for r in cur.fetchall()}
        cur.close()
        conn.close()

        where_sql, params = build_filter_query(cols)
        
        # 2. Dynamically determine the best SQL expression for the hour
        hour_expr = "CAST(`HOUR_COMMITTED` AS SIGNED)" if "HOUR_COMMITTED" in cols else \
                    "HOUR(`TIME_COMMITTED`)" if "TIME_COMMITTED" in cols else \
                    "HOUR(`DATE_COMMITTED`)"
        
        if not hour_expr.startswith("CAST") and not hour_expr.startswith("HOUR"):
             return jsonify(success=False, message="No suitable hour/time column found for forecasting.")

        # 3. Call the newly robust forecasting function
        result = run_categorical_forecast(
            table_name=table,
            grouping_key=hour_expr, # Pass the complex expression
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params
        )
        
        return jsonify(**result)

    except Exception as e:
        # Revert this to a generic message after you confirm it works
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

        # Find the victim count column, similar to how you do in other routes
        victim_col = next((c for c in ["VICTIM_COUNT", "VICTIM COUNT", "TOTAL_VICTIMS"] if c in cols), None)
        if not victim_col:
            return jsonify(success=False, message="VICTIM_COUNT column not found in table.")

        where_sql, params = build_filter_query(cols)
        weekday_expr = "WEEKDAY(`DATE_COMMITTED`)" if "DATE_COMMITTED" in cols else "CAST(`WEEKDAY` AS SIGNED)"
        
        # --- Run BOTH Forecasts ---
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

        # --- Combine the results ---
        day_map = {0: "1. Monday", 1: "2. Tuesday", 2: "3. Wednesday", 3: "4. Thursday", 4: "5. Friday", 5: "6. Saturday", 6: "7. Sunday"}
        labels = [day_map.get(int(label)) for label in count_result["data"]["labels"]]

        h_counts = np.array(count_result["data"]["historical"])
        f_counts = np.array(count_result["data"]["forecast"])
        h_victims = np.array(victim_result["historical"])
        f_victims = np.array(victim_result["forecast"])

        # Calculate average, handling division by zero
        h_avg = np.divide(h_victims, h_counts, out=np.zeros_like(h_victims, dtype=float), where=h_counts!=0)
        f_avg = np.divide(f_victims, f_counts, out=np.zeros_like(f_victims, dtype=float), where=f_counts!=0)

        # Prepare final payload for the frontend
        model_display_name = 'Random Forest'
        if model_req == 'adaboost':
            model_display_name = 'Decision Tree'

        final_data = {
            "labels": labels,
            "historical_counts": h_counts.tolist(),
            "forecast_counts": f_counts.tolist(),
            "historical_avg_victims": np.round(h_avg, 2).tolist(),
            "forecast_avg_victims": np.round(f_avg, 2).tolist(),
            "model_used": model_display_name, # Send display name
            "horizon": horizon
        }
        
        return jsonify(success=True, data=final_data)

    except Exception as e:
        import traceback
        return jsonify(success=False, message=f"<pre>{traceback.format_exc()}</pre>"), 500
    
# --- Replace your existing /forecast/top_barangays route with this one ---

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

        # 1. Get the standard filters as a dictionary (this part is correct)
        where_sql, params = build_filter_query(cols)
        
        # 2. Find the Top 10 Barangays using the initial filters
        top_10_query = f"""
            SELECT `{brgy_col}` FROM `{table}` {where_sql}
            GROUP BY `{brgy_col}` ORDER BY COUNT(*) DESC LIMIT 10
        """
        cur.execute(top_10_query, params)
        top_10_barangays = [row[0] for row in cur.fetchall()]
        cur.close(); conn.close()

        if not top_10_barangays:
            return jsonify(success=False, message="Not enough data to determine top barangays for forecasting.")

        # --- START OF THE FIX ---
        # 3. Add the Top 10 Barangays to the filter for the main forecast query.
        # Instead of creating a flat list, we will add new entries to our 'params' DICTIONARY
        # and create corresponding named placeholders.
        
        brgy_placeholders = []
        for i, brgy_name in enumerate(top_10_barangays):
            key = f"brgy_{i}"  # e.g., 'brgy_0', 'brgy_1'
            brgy_placeholders.append(f"%({key})s")
            params[key] = brgy_name # Add to the dictionary: {'brgy_0': 'BALIBAGO', 'brgy_1': 'MALABANIAS', ...}
            
        # Join the placeholders for the SQL IN clause: IN (%(brgy_0)s, %(brgy_1)s, ...)
        brgy_in_clause = ", ".join(brgy_placeholders)
        
        # Append this new condition to our existing WHERE clause
        if where_sql:
            where_sql += f" AND `{brgy_col}` IN ({brgy_in_clause})"
        else:
            where_sql = f"WHERE `{brgy_col}` IN ({brgy_in_clause})"
        # --- END OF THE FIX ---

        # 4. Run the forecast. The 'params' dictionary now correctly contains ALL parameters
        # (original filters + the new barangay filters) with unique keys.
        result = run_categorical_forecast(
            table_name=table,
            grouping_key=brgy_col,
            model_type=model,
            forecast_horizon=horizon,
            where_sql=where_sql,
            params=params # Pass the complete dictionary
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

        # --- START OF THE FIX ---
        # 4. Combine results using a DataFrame to align data by hour.
        
        # Create DataFrames for historical and forecast data.
        df_hist = pd.DataFrame(index=range(24)) # Ensure a full 0-23 index
        df_fcst = pd.DataFrame(index=range(24))

        for status in ["Yes", "No", "Unknown"]:
            # Check if the forecast for this category was successful and returned data
            if results[status].get("success") and results[status]["data"]["labels"]:
                res_data = results[status]["data"]
                # Create a temporary Series with the hour as the index
                s_hist = pd.Series(res_data["historical"], index=res_data["labels"], name=f"h_{status.lower()}")
                s_fcst = pd.Series(res_data["forecast"], index=res_data["labels"], name=f"f_{status.lower()}")
                # Join it to our main DataFrame. Pandas handles the alignment.
                df_hist = df_hist.join(s_hist)
                df_fcst = df_fcst.join(s_fcst)

        # After joining, any missing data will be NaN. Fill it with 0.
        df_hist = df_hist.fillna(0).astype(int)
        df_fcst = df_fcst.fillna(0).astype(int)
        
        # Now, extract the aligned and cleaned data as numpy arrays. They are guaranteed to have the same length.
        h_yes = df_hist.get("h_yes", pd.Series(0, index=range(24))).values
        h_no = df_hist.get("h_no", pd.Series(0, index=range(24))).values
        h_unk = df_hist.get("h_unknown", pd.Series(0, index=range(24))).values

        f_yes = df_fcst.get("f_yes", pd.Series(0, index=range(24))).values
        f_no = df_fcst.get("f_no", pd.Series(0, index=range(24))).values
        f_unk = df_fcst.get("f_unknown", pd.Series(0, index=range(24))).values
        # --- END OF THE FIX ---

        # The rest of the calculation is now safe.
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
            "hours": list(range(24)), # Send a full list of 24 hours
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

# --- Replace your existing forecast_victims_by_age route with this one ---

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

        # 2. If columns are still not found, return an error that lists the available columns for easy debugging.
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
    
# --- Add this new route to api.py ---

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

        # 1. Find the correct offense column name
        offense_col = next((c for c in ["OFFENSE", "OFFENSE_TYPE", "CRIME_TYPE"] if c in cols), None)
        if not offense_col:
            return jsonify(success=False, message="No offense type column found.")

        # 2. Get the standard filters from the user request
        where_sql, params = build_filter_query(cols)
        
        # 3. Run the forecast, grouping by the offense column
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
        
        # Use placeholders to prevent SQL injection
        placeholders = ', '.join(['%s'] * len(row_ids))
        query = f"DELETE FROM `{table_name}` WHERE `id` IN ({placeholders});"
        
        cursor.execute(query, tuple(row_ids))
        rows_deleted = cursor.rowcount
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({"success": True, "message": f"{rows_deleted} row(s) deleted successfully from {table_name}."})
    except Exception as e:
        # For security, you might want to log the error instead of returning it
        return jsonify({"success": False, "message": str(e)}), 500