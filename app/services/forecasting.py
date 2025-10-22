import numpy as np, pandas as pd, folium
from flask import jsonify, request, session, Response
from datetime import datetime
from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from .database import list_tables
from ..extensions import get_engine   # ⬅ use engine for pandas
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score, mean_squared_error
from sklearn.model_selection import train_test_split
import joblib
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'xgboost_hotspot_model.joblib')

def rf_monthly_payload(table: str):
    engine = get_engine()
    df = pd.read_sql_query(
        f"SELECT DATE_COMMITTED FROM `{table}` WHERE DATE_COMMITTED IS NOT NULL",
        engine,
        parse_dates=["DATE_COMMITTED"],
    )
    if df.empty:
        return {"success": True, "data": None, "message": "No rows found."}

    ts = df.set_index("DATE_COMMITTED").resample("ME").size().to_frame("accident_count")
    if len(ts) < 15:
        return {"success": True, "data": None, "message": "Not enough monthly history (need ≥15 months for lags)."}

    # --- Feature Engineering (No changes here) ---
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

    # --- STAGE 1: Get realistic performance metrics ---
    print(f"\n--- Generating RF Monthly Performance Metrics for table: '{table}' ---")
    X_train, X_test, y_train, y_test = train_test_split(X_full, y_full, test_size=0.25, shuffle=False)

    if X_test.empty:
        print("Warning: Test set is empty after split. Skipping metric evaluation.")
    else:
        eval_rf = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2)
        eval_rf.fit(X_train, y_train)
        y_pred_test = eval_rf.predict(X_test)

        mae = mean_absolute_error(y_test, y_pred_test)
        non_zero_mask = y_test > 0
        mape = mean_absolute_percentage_error(y_test[non_zero_mask], y_pred_test[non_zero_mask]) * 100 if np.any(non_zero_mask) else 0.0
        r2 = r2_score(y_test, y_pred_test)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))

        print(f"Mean Absolute Error (MAE): {mae:.2f}")
        print(f"Mean Absolute Percentage Error (MAPE): {mape:.2f}%")
        print(f"R-squared (R2): {r2:.2f}")
        print(f"Root Mean Squared Error (RMSE): {rmse:.2f}\n")

    # --- STAGE 2: Train final model on ALL data for forecasting ---
    rf = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2)
    rf.fit(X_full, y_full)

    # --- Forecasting Loop (uses the final 'rf' model) ---
    months_to_forecast = 12
    last_idx = ts.index.max()
    future_idx = pd.date_range(start=last_idx + pd.DateOffset(months=1), periods=months_to_forecast, freq="ME")

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
    
    # ... (rest of the function is the same) ...
    last_actual_year = ts.index.max().year
    last_year_mask = ts.index.year == last_actual_year
    last_year_actuals = ts.loc[last_year_mask, "accident_count"]
    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    actual_by_month = [float(last_year_actuals[last_year_actuals.index.month == m].sum() or 0) for m in range(1, 13)]
    forecast_by_month = [float(v) for v in future_preds[:12]]
    payload = {
        "title": f"Last Actual Year ({last_actual_year}) vs Forecast ({last_actual_year + 1})",
        "months": month_names, "actual": actual_by_month, "forecast": forecast_by_month,
    }
    return {"success": True, "data": payload}

def build_forecast_map_html(
    table: str,
    start_str: str = "", end_str: str = "", time_from: str = "", time_to: str = "",
    legacy_time: str = "Live", barangay_filter: str = ""
):
    engine = get_engine()
    DEFAULT_LOCATION = [14.5995, 120.9842]

    # --- Initial Full Data Load ---
    try:
        df_full = pd.read_sql_table(table, engine)
    except ValueError:
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        folium.Marker(DEFAULT_LOCATION, popup=f"Error: Table '{table}' could not be loaded.").add_to(m)
        return m.get_root().render()

    if df_full.empty:
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()
        
    # ==============================================================================
    # PART 1: UNFILTERED BASELINE PERFORMANCE EVALUATION (WITH CORRECT FEATURES)
    # ==============================================================================
    
    print(f"\n--- [EVALUATION] Generating Baseline XGBoost Performance for table: '{table}' (All Hours) ---")
    
    # --- Feature Engineering on FULL UNFILTERED Data ---
    df_eval = df_full.copy()
    df_eval["DATE_COMMITTED"] = pd.to_datetime(df_eval["DATE_COMMITTED"], errors="coerce")
    df_eval["ACCIDENT_HOTSPOT"] = pd.to_numeric(df_eval["ACCIDENT_HOTSPOT"], errors="coerce").fillna(-1).astype(int)
    df_eval = df_eval.dropna(subset=["DATE_COMMITTED", "ACCIDENT_HOTSPOT"])

    # --- START OF THE FIX: Replicate the Notebook's Aggregation ---
    # Dynamically find all TIME_CLUSTER columns
    time_cluster_cols = [c for c in df_eval.columns if 'TIME_CLUSTER' in str(c)]
    for col in time_cluster_cols:
        # This forces the columns to be numbers, turning any errors into 0.
        df_eval[col] = pd.to_numeric(df_eval[col], errors='coerce').fillna(0).astype(int)
    
    agg_dict_eval = {col: 'sum' for col in time_cluster_cols}
    agg_dict_eval['OFFENSE'] = 'size' # Use a temporary column for counting

    # Group by and aggregate, which is the core logic from the notebook
    ts_data_unfiltered = (
        df_eval.set_index('DATE_COMMITTED')
        .groupby(['ACCIDENT_HOTSPOT', pd.Grouper(freq='ME')])
        .agg(agg_dict_eval)
        .rename(columns={'OFFENSE': 'accident_count'})
        .reset_index()
    )
    # --- END OF THE FIX ---

    ts_data_unfiltered.sort_values(by=['ACCIDENT_HOTSPOT', 'DATE_COMMITTED'], inplace=True)

    ts_data_unfiltered['lag_1_month'] = ts_data_unfiltered.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1)
    ts_data_unfiltered['rolling_mean_3_months'] = ts_data_unfiltered.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1).rolling(window=3).mean()
    ts_data_unfiltered['month_of_year'] = ts_data_unfiltered['DATE_COMMITTED'].dt.month
    ts_data_unfiltered['quarter_of_year'] = ts_data_unfiltered['DATE_COMMITTED'].dt.quarter
    ts_data_unfiltered = ts_data_unfiltered.dropna().reset_index(drop=True)

    if not ts_data_unfiltered.empty:
        # The feature set `X_eval` will now correctly include the TIME_CLUSTER columns
        y_eval = ts_data_unfiltered['accident_count']
        X_eval = ts_data_unfiltered.drop(columns=['accident_count','DATE_COMMITTED'])
        
        X_train, X_test, y_train, y_test = train_test_split(X_eval, y_eval, test_size=0.2, shuffle=False)

        if not X_test.empty:
            eval_model = XGBRegressor(objective='count:poisson', n_estimators=1000, learning_rate=0.01, max_depth=4, random_state=42)
            eval_model.fit(X_train, y_train, verbose=False)
            y_pred_test = eval_model.predict(X_test)

            mae = mean_absolute_error(y_test, y_pred_test)
            mape = mean_absolute_percentage_error(y_test[y_test > 0], y_pred_test[y_test > 0]) * 100 if np.any(y_test > 0) else 0.0
            r2 = r2_score(y_test, y_pred_test)
            rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))

            print(f"Mean Absolute Error (MAE): {mae:.2f}")
            print(f"Mean Absolute Percentage Error (MAPE): {mape:.2f}%")
            print(f"R-squared (R²): {r2:.2f}")
            print(f"Root Mean Squared Error (RMSE): {rmse:.2f}\n")
        else:
            print("Warning: Test set for evaluation was empty. Skipping metric calculation.\n")
    else:
        print("Warning: Not enough data in the full dataset to perform an evaluation.\n")

    # ==============================================================================
    # PART 2: FILTERED FORECASTING FOR THE MAP VISUALIZATION
    # ==============================================================================
    # This part remains the same, as it correctly uses a simpler feature set
    # appropriate for data that has already been filtered by time.
    
    df = df_full.copy() 
    df["DATE_COMMITTED"] = pd.to_datetime(df["DATE_COMMITTED"], errors="coerce")
    df = df.dropna(subset=["DATE_COMMITTED"]).copy()
    df["HOUR_COMMITTED"] = pd.to_numeric(df["HOUR_COMMITTED"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["HOUR_COMMITTED"]).copy()
    df["HOUR_COMMITTED"] = df["HOUR_COMMITTED"].astype(int)
    df["ACCIDENT_HOTSPOT"] = pd.to_numeric(df["ACCIDENT_HOTSPOT"], errors="coerce").fillna(-1).astype(int)
    
    def parse_hour(hmm: str) -> int | None:
        if not hmm: return None
        try: return int(hmm.split(":")[0])
        except Exception: return None

    h_from, h_to = parse_hour(time_from), parse_hour(time_to)
    display_hour_str = ""
    use_range = (h_from is not None) and (h_to is not None)

    df_time_filtered = df
    if use_range:
        if h_from <= h_to: hours = list(range(h_from, h_to + 1))
        else: hours = list(range(h_from, 24)) + list(range(0, h_to + 1))
        df_time_filtered = df[df["HOUR_COMMITTED"].isin(hours)].copy()
        display_hour_str = f"{h_from:02d}:00–{h_to:02d}:00"
    else:
        t = (legacy_time or "Live").lower()
        if t == "live":
            try:
                import pytz; tz = pytz.timezone("Asia/Manila"); current_hour = datetime.now(tz).hour
            except Exception: current_hour = pd.Timestamp.now().hour
            df_time_filtered = df[df["HOUR_COMMITTED"] == int(current_hour)].copy()
            display_hour_str = f"Live ({current_hour:02d}:00)"
        elif t == "all":
            df_time_filtered = df.copy()
            display_hour_str = "All Hours"
        else:
            try:
                hour_val = max(0, min(23, int(t)))
                df_time_filtered = df[df["HOUR_COMMITTED"] == hour_val].copy()
                display_hour_str = f"Hour {hour_val:02d}:00"
            except Exception:
                df_time_filtered = df.copy()
                display_hour_str = "All Hours"

    df_filtered = df_time_filtered
    if barangay_filter:
        barangays = [b.strip() for b in barangay_filter.split(',') if b.strip()]
        if barangays:
            df_filtered = df_filtered[df_filtered['BARANGAY'].isin(barangays)].copy()

    if df_filtered.empty:
        safe_center_lat = df["LATITUDE"].astype(float).mean(); safe_center_lon = df["LONGITUDE"].astype(float).mean()
        if pd.isna(safe_center_lat) or pd.isna(safe_center_lon): safe_center_lat, safe_center_lon = DEFAULT_LOCATION
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()
        
    grouping_cols_fcst = ['ACCIDENT_HOTSPOT', pd.Grouper(key='DATE_COMMITTED', freq='ME')]
    ts_counts_fcst = (df_filtered.groupby(grouping_cols_fcst).size().to_frame('accident_count').reset_index())
    all_clusters_fcst = pd.DataFrame({'ACCIDENT_HOTSPOT': df_filtered['ACCIDENT_HOTSPOT'].unique()})
    
    if df_filtered.empty or df_filtered['DATE_COMMITTED'].isnull().all():
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()

    month_range_fcst = pd.date_range(df_filtered['DATE_COMMITTED'].min(), df_filtered['DATE_COMMITTED'].max(), freq='ME')
    full_grid_fcst = pd.MultiIndex.from_product(
        [all_clusters_fcst['ACCIDENT_HOTSPOT'], month_range_fcst], names=['ACCIDENT_HOTSPOT','DATE_COMMITTED']
    ).to_frame(index=False)
    ts_data_for_forecast = (pd.merge(full_grid_fcst, ts_counts_fcst, on=['ACCIDENT_HOTSPOT','DATE_COMMITTED'], how='left')
               .fillna({'accident_count': 0}).sort_values(['ACCIDENT_HOTSPOT','DATE_COMMITTED']).reset_index(drop=True))

    ts_data_for_forecast['lag_1_month'] = ts_data_for_forecast.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1)
    ts_data_for_forecast['rolling_mean_3_months'] = ts_data_for_forecast.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1).rolling(window=3).mean()
    ts_data_for_forecast['month_of_year'] = ts_data_for_forecast['DATE_COMMITTED'].dt.month
    ts_data_for_forecast['quarter_of_year'] = ts_data_for_forecast['DATE_COMMITTED'].dt.quarter
    ts_data_for_forecast = ts_data_for_forecast.dropna().reset_index(drop=True)

    if ts_data_for_forecast.empty:
        safe_center_lat = df["LATITUDE"].astype(float).mean(); safe_center_lon = df["LONGITUDE"].astype(float).mean()
        if pd.isna(safe_center_lat) or pd.isna(safe_center_lon): safe_center_lat, safe_center_lon = DEFAULT_LOCATION
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()

    y_final = ts_data_for_forecast['accident_count']
    X_final = ts_data_for_forecast.drop(columns=['accident_count','DATE_COMMITTED'])
    final_model = XGBRegressor(objective='count:poisson', n_estimators=1000, learning_rate=0.01, max_depth=4, random_state=42)
    final_model.fit(X_final, y_final, verbose=False)

    last_known_date = df_filtered["DATE_COMMITTED"].max()
    start_date = pd.to_datetime((start_str + "-01") if start_str else f"{last_known_date.year}-{last_known_date.month:02d}-01", errors="coerce")
    end_date = (pd.to_datetime(end_str + "-01", errors="coerce") + pd.offsets.MonthEnd(0)) if end_str else last_known_date + pd.offsets.MonthEnd(0)
    last_known_month = ts_data_for_forecast['DATE_COMMITTED'].max()
    
    hist_in_range = pd.DataFrame()
    if start_date <= last_known_month:
        historical_end = min(end_date, last_known_month)
        hist_in_range = ts_data_for_forecast[(ts_data_for_forecast['DATE_COMMITTED'] >= start_date) & (ts_data_for_forecast['DATE_COMMITTED'] <= historical_end)][['ACCIDENT_HOTSPOT','DATE_COMMITTED','accident_count']].copy()

    future_forecast_df = pd.DataFrame()
    if end_date > last_known_month:
        months_to_forecast = (end_date.year - last_known_month.year)*12 + (end_date.month - last_known_month.month)
        last_rows_idx = ts_data_for_forecast.groupby('ACCIDENT_HOTSPOT')['DATE_COMMITTED'].idxmax()
        current_features_df = ts_data_for_forecast.loc[last_rows_idx].copy()
        for need in ['lag_1_month','lag_2_month','lag_3_month']:
            if need not in current_features_df.columns: current_features_df[need] = 0.0
        feature_names = X_final.columns.tolist()
        preds_accum = []
        for i in range(months_to_forecast):
            preds = final_model.predict(current_features_df[feature_names])
            next_month = last_known_month + pd.DateOffset(months=i+1)
            preds_accum.append(pd.DataFrame({'ACCIDENT_HOTSPOT': current_features_df['ACCIDENT_HOTSPOT'].values, 'DATE_COMMITTED': next_month, 'accident_count': preds}))
            current_features_df['lag_3_month'] = current_features_df['lag_2_month']
            current_features_df['lag_2_month'] = current_features_df['lag_1_month']
            current_features_df['lag_1_month'] = preds
            current_features_df['rolling_mean_3_months'] = current_features_df[['lag_1_month','lag_2_month','lag_3_month']].mean(axis=1)
            nm = next_month + pd.DateOffset(months=1)
            current_features_df['month_of_year'] = nm.month
            current_features_df['quarter_of_year'] = nm.quarter
        future_forecast_df = pd.concat(preds_accum, ignore_index=True) if preds_accum else pd.DataFrame()

    if not hist_in_range.empty: hist_summary = (hist_in_range.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum().to_frame('Total_Actual_Accidents').reset_index())
    else: hist_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Actual_Accidents'])
    if not future_forecast_df.empty: future_summary = (future_forecast_df.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum().to_frame('Total_Forecasted_Accidents').reset_index())
    else: future_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Forecasted_Accidents'])
    
    barangay_counts = (df_filtered.groupby(['ACCIDENT_HOTSPOT','BARANGAY']).size().to_frame('count').reset_index())
    top_barangays = (barangay_counts.sort_values('count', ascending=False).groupby('ACCIDENT_HOTSPOT')['BARANGAY'].apply(lambda s: list(s.head(3))).to_frame(name='Top_Barangays').reset_index())
    centroids = (df_filtered.groupby('ACCIDENT_HOTSPOT').agg(Center_Lat=('LATITUDE','mean'), Center_Lon=('LONGITUDE','mean')).reset_index())
    
    final_map_data = (pd.DataFrame({'ACCIDENT_HOTSPOT': df_filtered['ACCIDENT_HOTSPOT'].unique()}).merge(hist_summary, on='ACCIDENT_HOTSPOT', how='left').merge(future_summary, on='ACCIDENT_HOTSPOT', how='left').merge(centroids, on='ACCIDENT_HOTSPOT', how='left').merge(top_barangays, on='ACCIDENT_HOTSPOT', how='left'))
    final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']] = final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']].fillna(0).astype(float)
    final_map_data['Total_Events'] = final_map_data['Total_Actual_Accidents'] + final_map_data['Total_Forecasted_Accidents']
    
    nz = final_map_data.loc[final_map_data['Total_Events'] > 0, 'Total_Events']
    median_th, high_th = (nz.quantile(0.50), nz.quantile(0.75)) if not nz.empty else (0.0, 0.0)
    def color_for(v):
        if v <= 0: return 'grey'
        if v <= median_th: return 'green'
        if v <= high_th: return '#ffb200'
        return 'red'
     
    safe_center_lat = df_filtered["LATITUDE"].astype(float).mean(); safe_center_lon = df_filtered["LONGITUDE"].astype(float).mean()
    if pd.isna(safe_center_lat) or pd.isna(safe_center_lon): safe_center_lat, safe_center_lon = DEFAULT_LOCATION
    m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
    
    for _, row in final_map_data.iterrows():
        if pd.isna(row['Center_Lat']) or pd.isna(row['Center_Lon']): continue
        top3 = row.get('Top_Barangays', None); barangay_str = ', '.join(top3) if isinstance(top3, list) else 'N/A'
        popup_html = (f"<b>Hotspot #{int(row['ACCIDENT_HOTSPOT'])} ({display_hour_str})</b><br>"
                      f"-----------------------------<br>"
                      f"<b>Top Barangays:</b> {barangay_str}<br>"
                      f"-----------------------------<br>")
        if row['Total_Actual_Accidents'] > 0: popup_html += f"<b>Actual Accidents (Historical): {row['Total_Actual_Accidents']:.2f}</b><br>"
        if row['Total_Forecasted_Accidents'] > 0: popup_html += f"<b>Forecasted Accidents (Future): {row['Total_Forecasted_Accidents']:.2f}</b><br>"
        color = color_for(float(row['Total_Events']))
        radius = 5 + (np.log1p(float(row['Total_Events'])) * 5)
        folium.CircleMarker(location=[float(row['Center_Lat']), float(row['Center_Lon'])], radius=radius, popup=folium.Popup(popup_html, max_width=300), color=color, fill=True, fill_color=color, fill_opacity=0.8).add_to(m)
        
    return m.get_root().render()