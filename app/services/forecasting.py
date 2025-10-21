import numpy as np, pandas as pd, folium
from flask import jsonify, request, session, Response
from datetime import datetime
from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from .database import list_tables
from ..extensions import get_engine   # ⬅ use engine for pandasz

# === 1) RF monthly API (from your /api/rf_monthly_forecast) ===
def rf_monthly_payload(table: str):
    # read with SQLAlchemy engine (no pandas warning)
    engine = get_engine()
    df = pd.read_sql_query(
        f"SELECT DATE_COMMITTED FROM `{table}` WHERE DATE_COMMITTED IS NOT NULL",
        engine,
        parse_dates=["DATE_COMMITTED"],
    )
    if df.empty:
        return {"success": True, "data": None, "message": "No rows found."}

    # use 'ME' (month end) instead of deprecated 'M'
    ts = df.set_index("DATE_COMMITTED").resample("ME").size().to_frame("accident_count")
    if len(ts) < 15:
        return {"success": True, "data": None, "message": "Not enough monthly history (need ≥15 months for lags)."}

    ts["lag_1_month"] = ts["accident_count"].shift(1)
    ts["lag_2_month"] = ts["accident_count"].shift(2)
    ts["lag_3_month"] = ts["accident_count"].shift(3)
    ts["lag_12_month"] = ts["accident_count"].shift(12)
    ts["rolling_mean_3_months"] = ts["accident_count"].shift(1).rolling(3).mean()
    ts["month_of_year"] = ts.index.month
    ts["quarter_of_year"] = ts.index.quarter
    ts = ts.dropna()
    if ts.empty:
        return {"success": True, "data": None, "message": "Not enough rows after feature engineering."}

    y_full = ts["accident_count"].astype(float)
    X_full = ts.drop(columns=["accident_count"]).astype(float)
    feature_cols = X_full.columns.tolist()

    rf = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2)
    rf.fit(X_full, y_full)

    months_to_forecast = 12
    last_idx = ts.index.max()
    future_idx = pd.date_range(start=last_idx + pd.DateOffset(months=1),
                               periods=months_to_forecast, freq="ME")

    future_preds = []
    history_series = ts["accident_count"].copy()
    current_features = ts.iloc[[-1]][feature_cols].copy()

    for i, fdate in enumerate(future_idx):
        pred = float(np.round(rf.predict(current_features[feature_cols])[0]))
        future_preds.append(pred)

        history_plus_future = pd.concat([history_series, pd.Series(future_preds, index=future_idx[: i + 1])])
        next_row = current_features.copy(); next_row.index = [fdate]
        next_row.loc[fdate, "lag_3_month"] = current_features["lag_2_month"].values[0]
        next_row.loc[fdate, "lag_2_month"] = current_features["lag_1_month"].values[0]
        next_row.loc[fdate, "lag_1_month"] = pred

        lag12_val = history_plus_future.shift(12).get(fdate, np.nan)
        if pd.isna(lag12_val):
            lag12_val = current_features.get("lag_12_month", pd.Series([0.0])).values[0]
        next_row.loc[fdate, "lag_12_month"] = float(lag12_val)

        rmean = np.mean([
            next_row.loc[fdate, "lag_1_month"],
            next_row.loc[fdate, "lag_2_month"],
            next_row.loc[fdate, "lag_3_month"],
        ])
        next_row.loc[fdate, "rolling_mean_3_months"] = float(rmean)
        next_row.loc[fdate, "month_of_year"] = fdate.month
        next_row.loc[fdate, "quarter_of_year"] = fdate.quarter

        current_features = next_row[feature_cols].copy()

    last_actual_year = ts.index.max().year
    last_year_mask = ts.index.year == last_actual_year
    last_year_actuals = ts.loc[last_year_mask, "accident_count"]

    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    actual_by_month = [float(last_year_actuals[last_year_actuals.index.month == m].sum() or 0) for m in range(1, 13)]
    forecast_by_month = [float(v) for v in future_preds[:12]]

    payload = {
        "title": f"Last Actual Year ({last_actual_year}) vs Forecast ({last_actual_year + 1})",
        "months": month_names,
        "actual": actual_by_month,
        "forecast": forecast_by_month,
    }
    return {"success": True, "data": payload}


# === 2) Folium map builder (from your _build_forecast_map_html) ===
# In forecasting.py, replace the entire function

def build_forecast_map_html(
    table: str,
    where_sql: str = "",
    params: dict = None,
    start_str: str = "", end_str: str = "", time_from: str = "", time_to: str = "",
    legacy_time: str = "Live", barangay_filter: str = "" # This parameter is now only for display text, not filtering
):
    engine = get_engine()
    
    # Define a default fallback location for the map center
    DEFAULT_LOCATION = [14.5995, 120.9842] # Manila as a fallback
    
    # The SQL query now correctly uses the pre-built where_sql from api.py
    cols_to_select = ["DATE_COMMITTED", "HOUR_COMMITTED", "ACCIDENT_HOTSPOT", "LATITUDE", "LONGITUDE", "BARANGAY", "OFFENSE"]
    sql_select_clause = ", ".join(f"`{c}`" for c in cols_to_select)
    sql = f"SELECT {sql_select_clause} FROM `{table}` {where_sql}"
    df = pd.read_sql_query(sql, engine, params=params, parse_dates=["DATE_COMMITTED"])

    # If the initial query returns no data at all, show a default empty map
    if df.empty:
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()

    # --- Clean types ---
    df["DATE_COMMITTED"] = pd.to_datetime(df["DATE_COMMITTED"], errors="coerce")
    df = df.dropna(subset=["DATE_COMMITTED"]).copy()
    df["HOUR_COMMITTED"] = pd.to_numeric(df["HOUR_COMMITTED"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["HOUR_COMMITTED"]).copy()
    df["HOUR_COMMITTED"] = df["HOUR_COMMITTED"].astype(int)
    df["ACCIDENT_HOTSPOT"] = pd.to_numeric(df["ACCIDENT_HOTSPOT"], errors="coerce").fillna(-1).astype(int)

    # --- Date window (month-year range) ---
    last_known_date = df["DATE_COMMITTED"].max()
    start_date = pd.to_datetime((start_str + "-01") if start_str else f"{last_known_date.year}-{last_known_date.month:02d}-01", errors="coerce")
    end_date   = (pd.to_datetime(end_str + "-01", errors="coerce") + pd.offsets.MonthEnd(0)) if end_str else last_known_date + pd.offsets.MonthEnd(0)

    # --- ROBUST MAP CENTERING ---
    # Calculate a safe center from the initial unfiltered data
    safe_center_lat = df["LATITUDE"].astype(float).mean()
    safe_center_lon = df["LONGITUDE"].astype(float).mean()
    if pd.isna(safe_center_lat) or pd.isna(safe_center_lon):
        safe_center_lat, safe_center_lon = DEFAULT_LOCATION

    # --- REMOVED REDUNDANT FILTERING ---
    # The line that was incorrectly filtering by the barangay_filter string has been removed.

    # --- Time selection (range or legacy) ---
    def parse_hour(hmm: str) -> int | None:
        if not hmm: return None
        try: return int(hmm.split(":")[0])
        except Exception: return None

    h_from, h_to = parse_hour(time_from), parse_hour(time_to)
    display_hour_str = ""
    use_range = (h_from is not None) and (h_to is not None)

    if use_range:
        if h_from <= h_to: hours = list(range(h_from, h_to + 1))
        else: hours = list(range(h_from, 24)) + list(range(0, h_to + 1))
        df_filtered = df[df["HOUR_COMMITTED"].isin(hours)].copy()
        display_hour_str = f"{h_from:02d}:00–{h_to:02d}:00"
    else:
        # Legacy time logic remains the same
        t = (legacy_time or "Live").lower()
        if t == "live":
            try:
                import pytz
                tz = pytz.timezone("Asia/Manila")
                current_hour = datetime.now(tz).hour
            except Exception:
                current_hour = pd.Timestamp.now().hour
            df_filtered = df[df["HOUR_COMMITTED"] == int(current_hour)].copy()
            display_hour_str = f"Live ({current_hour:02d}:00)"
        elif t == "all":
            df_filtered = df.copy()
            display_hour_str = "All Hours"
        else:
            try:
                hour_val = max(0, min(23, int(t)))
                df_filtered = df[df["HOUR_COMMITTED"] == hour_val].copy()
                display_hour_str = f"Hour {hour_val:02d}:00"
            except Exception:
                df_filtered = df.copy()
                display_hour_str = "All Hours"

    # If all time-based filtering results in an empty DataFrame, render a map centered on the original data
    if df_filtered.empty:
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()

    # --- Monthly counts per hotspot (restricted to chosen hours) ---
    grouping_cols = ['ACCIDENT_HOTSPOT', pd.Grouper(key='DATE_COMMITTED', freq='ME')]
    ts_counts = (df_filtered
                 .groupby(grouping_cols)
                 .size()
                 .to_frame('accident_count')
                 .reset_index())

    # Build full grid for continuity
    all_clusters = pd.DataFrame({'ACCIDENT_HOTSPOT': df['ACCIDENT_HOTSPOT'].unique()})
    month_range  = pd.date_range(df['DATE_COMMITTED'].min(), df['DATE_COMMITTED'].max(), freq='ME')
    full_grid = pd.MultiIndex.from_product(
        [all_clusters['ACCIDENT_HOTSPOT'], month_range],
        names=['ACCIDENT_HOTSPOT','DATE_COMMITTED']
    ).to_frame(index=False)

    ts_data = (pd.merge(full_grid, ts_counts, on=['ACCIDENT_HOTSPOT','DATE_COMMITTED'], how='left')
               .fillna({'accident_count': 0})
               .sort_values(['ACCIDENT_HOTSPOT','DATE_COMMITTED'])
               .reset_index(drop=True))

    # Simple lag features per hotspot
    ts_data['lag_1_month'] = ts_data.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1)
    ts_data['rolling_mean_3_months'] = ts_data.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1).rolling(window=3).mean()
    ts_data['month_of_year'] = ts_data['DATE_COMMITTED'].dt.month
    ts_data['quarter_of_year'] = ts_data['DATE_COMMITTED'].dt.quarter
    ts_data = ts_data.dropna().reset_index(drop=True)

    if ts_data.empty:
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()

    # === Train the Poisson XGB on counts (same as Colab structure) ===
    y_full = ts_data['accident_count']
    X_full = ts_data.drop(columns=['accident_count','DATE_COMMITTED'])

    final_model = XGBRegressor(
        objective='count:poisson',
        n_estimators=1000, learning_rate=0.01,
        max_depth=4, min_child_weight=1, gamma=0.1,
        random_state=42
    )
    final_model.fit(X_full, y_full, verbose=False)

    last_known_month = ts_data['DATE_COMMITTED'].max()

    # Actuals within date window
    hist_in_range = pd.DataFrame()
    if start_date <= last_known_month:
        historical_end = min(end_date, last_known_month)
        hist_in_range = ts_data[
            (ts_data['DATE_COMMITTED'] >= start_date) &
            (ts_data['DATE_COMMITTED'] <= historical_end)
        ][['ACCIDENT_HOTSPOT','DATE_COMMITTED','accident_count']].copy()

    # Forecast months until end_date
    future_forecast_df = pd.DataFrame()
    if end_date > last_known_month:
        months_to_forecast = (end_date.year - last_known_month.year)*12 + (end_date.month - last_known_month.month)
        last_rows_idx = ts_data.groupby('ACCIDENT_HOTSPOT')['DATE_COMMITTED'].idxmax()
        current_features_df = ts_data.loc[last_rows_idx].copy()

        # ensure lag columns exist
        for need in ['lag_1_month','lag_2_month','lag_3_month']:
            if need not in current_features_df.columns:
                current_features_df[need] = 0.0

        feature_names = X_full.columns.tolist()
        preds_accum = []
        for i in range(months_to_forecast):
            preds = final_model.predict(current_features_df[feature_names])
            next_month = last_known_month + pd.DateOffset(months=i+1)
            preds_accum.append(pd.DataFrame({
                'ACCIDENT_HOTSPOT': current_features_df['ACCIDENT_HOTSPOT'].values,
                'DATE_COMMITTED': next_month,
                'accident_count': preds
            }))
            # roll lags
            current_features_df['lag_3_month'] = current_features_df['lag_2_month']
            current_features_df['lag_2_month'] = current_features_df['lag_1_month']
            current_features_df['lag_1_month'] = preds
            current_features_df['rolling_mean_3_months'] = current_features_df[['lag_1_month','lag_2_month','lag_3_month']].mean(axis=1)
            nm = next_month + pd.DateOffset(months=1)
            current_features_df['month_of_year'] = nm.month
            current_features_df['quarter_of_year'] = nm.quarter

        future_forecast_df = pd.concat(preds_accum, ignore_index=True) if preds_accum else pd.DataFrame()

    # Summaries (actual + future)
    if not hist_in_range.empty:
        hist_summary = (hist_in_range.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum()
                        .to_frame('Total_Actual_Accidents').reset_index())
    else:
        hist_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Actual_Accidents'])

    if not future_forecast_df.empty:
        future_summary = (future_forecast_df.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum()
                          .to_frame('Total_Forecasted_Accidents').reset_index())
    else:
        future_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Forecasted_Accidents'])

    # === NEW: Top 3 Barangays per hotspot (matches your Colab) ===
    barangay_counts = (df.groupby(['ACCIDENT_HOTSPOT','BARANGAY'])
                         .size()
                         .to_frame('count')
                         .reset_index())
    top_barangays = (barangay_counts.sort_values('count', ascending=False)
                     .groupby('ACCIDENT_HOTSPOT')['BARANGAY']
                     .apply(lambda s: list(s.head(3)))
                     .to_frame(name='Top_Barangays')
                     .reset_index())

    # Centroids for marker placement
    centroids = (df.groupby('ACCIDENT_HOTSPOT')
                 .agg(Center_Lat=('LATITUDE','mean'),
                      Center_Lon=('LONGITUDE','mean'))
                 .reset_index())

    # Final map data
    final_map_data = (pd.DataFrame({'ACCIDENT_HOTSPOT': df['ACCIDENT_HOTSPOT'].unique()})
                      .merge(hist_summary, on='ACCIDENT_HOTSPOT', how='left')
                      .merge(future_summary, on='ACCIDENT_HOTSPOT', how='left')
                      .merge(centroids, on='ACCIDENT_HOTSPOT', how='left')
                      .merge(top_barangays, on='ACCIDENT_HOTSPOT', how='left'))

    final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']] = (
        final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']].fillna(0).astype(float)
    )
    final_map_data['Total_Events'] = final_map_data['Total_Actual_Accidents'] + final_map_data['Total_Forecasted_Accidents']

    # thresholds for coloring based on quartile analysis (Median and Upper Quartile)
    nz = final_map_data.loc[final_map_data['Total_Events'] > 0, 'Total_Events']
    median_th, high_th = (nz.quantile(0.50), nz.quantile(0.75)) if not nz.empty else (0.0, 0.0)

    def color_for(v):
        if v <= 0: return 'grey'
        if v <= median_th: return 'green'
        if v <= high_th: return 'orange'
        return 'red'

    # Build map using the safe center point
    m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)

    for _, row in final_map_data.iterrows():
        if pd.isna(row['Center_Lat']) or pd.isna(row['Center_Lon']):
            continue
        top3 = row.get('Top_Barangays', None)
        barangay_str = ', '.join(top3) if isinstance(top3, list) else 'N/A'

        popup_html = (
            f"<b>Hotspot #{int(row['ACCIDENT_HOTSPOT'])} ({display_hour_str})</b><br>"
            f"-----------------------------<br>"
            f"<b>Top Barangays:</b> {barangay_str}<br>"
            f"-----------------------------<br>"
        )
        if row['Total_Actual_Accidents'] > 0:
            popup_html += f"<b>Actual Accidents (Historical): {row['Total_Actual_Accidents']:.2f}</b><br>"
        if row['Total_Forecasted_Accidents'] > 0:
            popup_html += f"<b>Forecasted Accidents (Future): {row['Total_Forecasted_Accidents']:.2f}</b><br>"

        color = color_for(float(row['Total_Events']))
        radius = 5 + (np.log1p(float(row['Total_Events'])) * 5)

        folium.CircleMarker(
            location=[float(row['Center_Lat']), float(row['Center_Lon'])],
            radius=radius,
            popup=folium.Popup(popup_html, max_width=300),
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7
        ).add_to(m)

    return m.get_root().render()