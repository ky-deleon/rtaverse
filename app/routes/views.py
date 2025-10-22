from flask import Blueprint, render_template, session, redirect, url_for
from .auth import is_logged_in
from ..extensions import get_engine
from ..services.preprocessing import make_display_copy
from ..services.database import list_tables
from ..extensions import get_db_connection
from markupsafe import Markup
from flask import request
import pandas as pd

views_bp = Blueprint("views", __name__)

# --- NEW HELPER FUNCTION ---
def generate_no_data_html():
    """Generates the HTML for the 'No Data' message."""
    # Using Markup to ensure the HTML is rendered correctly by Jinja2
    return Markup("""
    <div class="no-data">
        <svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" fill="#0437F2" viewBox="0 0 24 24">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
        </svg>
        <p>
              No data available in the database. Upload a file to get started.
            </p>
    </div>
    """)
# --- END NEW HELPER FUNCTION ---


# In views.py

@views_bp.route("/graphs")
def graphs():
    if not is_logged_in():
        return redirect(url_for("auth.login"))

    # --- START OF FIX ---
    # 1. Get all usable tables, using the same filter logic as your database page
    all_tables = list_tables()
    EXCLUDE_PREFIXES = {"sys_","mysql_","tmp_","app_"}
    EXCLUDE_EXACT = {"app_settings","schema_migrations"}
    available_tables = sorted([
        t for t in all_tables 
        if t not in EXCLUDE_EXACT and not any(t.startswith(p) for p in EXCLUDE_PREFIXES)
    ])

    # 2. Check the table currently in the session
    active_table = session.get("forecast_table")

    # 3. Check if the session table is invalid (e.g., None or was deleted)
    if not active_table or active_table not in available_tables:
        
        # 4. If it's invalid, check if ANY other tables exist
        if not available_tables:
            # 5. No tables exist at all. Show the "No data" message.
            no_data_message = generate_no_data_html()
            return render_template(
                "graphs.html", 
                no_data_html=no_data_message, 
                missing_table=active_table or "Not Set"
            )
        else:
            # 6. Tables DO exist. Automatically select the first one.
            active_table = available_tables[0]
            session["forecast_table"] = active_table
            
    # 7. By this point, a valid table is selected. Render the graph page normally.
    return render_template("graphs.html")
    # --- END OF FIX ---


# In views.py, the existing database_page function remains the same
@views_bp.route("/database")
def database_page():
    if not is_logged_in():
        return redirect(url_for("auth.login"))
    
    all_tables = list_tables()
    EXCLUDE_PREFIXES = {"sys_","mysql_","tmp_","app_"}
    EXCLUDE_EXACT = {"app_settings","schema_migrations"}
    available_tables = sorted([t for t in all_tables if t not in EXCLUDE_EXACT and not any(t.startswith(p) for p in EXCLUDE_PREFIXES)])
    
    table = (request.args.get("table") or "").strip()
    if not table or table not in all_tables:
        return render_template("database.html", table_data=None, available_tables=available_tables)

    engine = get_engine()
    df = pd.read_sql_query(f"SELECT * FROM `{table}`", engine)
    
    if df.empty:
        empty_html = pd.DataFrame({"Info":[f'No rows in "{table}".']}).to_html(classes="data-table", table_id="uploadedTable", index=False)
        return render_template("database.html", table_data=Markup(empty_html), available_tables=available_tables)
    
    display_df = make_display_copy(df)
    
    COLUMNS_TO_SHOW = [
        "id",
        "STATION",
        "BARANGAY",
        "DATE_COMMITTED",
        "TIME_COMMITTED",
        "DAY_OF_WEEK",
        "OFFENSE",
        "LATITUDE",
        "LONGITUDE",
        "ACCIDENT_HOTSPOT",
        "VICTIM COUNT",
        "SUSPECT COUNT",
        "AGE",
        "GENDER_CLUSTER",
        "ALCOHOL_USED_CLUSTER",
        "VEHICLE KIND",
    ]
    
    final_columns = [col for col in COLUMNS_TO_SHOW if col in display_df.columns]
    final_df = display_df[final_columns]
    
    table_html = final_df.to_html(classes="data-table", table_id="uploadedTable", index=False, border=0)

    return render_template("database.html", table_data=Markup(table_html), available_tables=available_tables)