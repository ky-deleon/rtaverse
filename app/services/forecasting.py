# In forecasting.py, replace the entire file content with this

import numpy as np, pandas as pd, folium
from flask import jsonify, request, session, Response
from datetime import datetime
from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from .database import list_tables
from ..extensions import get_engine   # ⬅ use engine for pandas
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score, mean_squared_error
from sklearn.model_selection import train_test_split, TimeSeriesSplit
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

    # --- Feature Engineering ---
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


# === FIX: Add `where_sql` and `params` to the function signature ===
def build_forecast_map_html(
    table: str,
    where_sql: str = "",
    params: dict = None,
    start_str: str = "", end_str: str = "", time_from: str = "", time_to: str = "",
    legacy_time: str = "Live", barangay_filter: str = ""
):
    engine = get_engine()
    DEFAULT_LOCATION = [14.5995, 120.9842]

    # === FIX: Use read_sql_query with the where_sql clause for efficient filtering ===
    try:
        # We read all columns initially because the model evaluation part needs them
        sql = f"SELECT * FROM `{table}` {where_sql}"
        df_full = pd.read_sql_query(sql, engine, params=params)
    except Exception as e:
        print(f"Error loading data for table '{table}': {e}")
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        folium.Marker(DEFAULT_LOCATION, popup=f"Error: Could not load data from table '{table}'.").add_to(m)
        return m.get_root().render()

    if df_full.empty:
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()
    
    df_full["ACCIDENT_HOTSPOT"] = pd.to_numeric(df_full["ACCIDENT_HOTSPOT"], errors='coerce').fillna(-1).astype(int)
    df_full = df_full[df_full['ACCIDENT_HOTSPOT'] != -1].copy()
    
    # If filtering removes all data, return an empty map.
    if df_full.empty:
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()
        
    # ==============================================================================
    # PART 1: UNFILTERED BASELINE PERFORMANCE EVALUATION (NOW CONSISTENT)
    # ==============================================================================
    print(f"\n--- [EVALUATION] Generating Baseline XGBoost Performance for table: '{table}' (All Hours) ---")
    df_eval = df_full.copy()
    df_eval["DATE_COMMITTED"] = pd.to_datetime(df_eval["DATE_COMMITTED"], errors="coerce")
    df_eval["ACCIDENT_HOTSPOT"] = pd.to_numeric(df_eval["ACCIDENT_HOTSPOT"], errors="coerce").fillna(-1).astype(int)
    df_eval = df_eval.dropna(subset=["DATE_COMMITTED", "ACCIDENT_HOTSPOT"])

    time_cluster_cols = [c for c in df_eval.columns if 'TIME_CLUSTER' in str(c)]
    for col in time_cluster_cols:
        df_eval[col] = pd.to_numeric(df_eval[col], errors='coerce').fillna(0).astype(int)

    agg_dict = {col: 'sum' for col in time_cluster_cols}
    agg_dict['OFFENSE'] = 'size'

    ts_data_unfiltered = (
        df_eval.set_index('DATE_COMMITTED')
        .groupby(['ACCIDENT_HOTSPOT', pd.Grouper(freq='ME')])
        .agg(agg_dict)
        .rename(columns={'OFFENSE': 'accident_count'})
        .reset_index()
    )
    ts_data_unfiltered.sort_values(by=['ACCIDENT_HOTSPOT', 'DATE_COMMITTED'], inplace=True)
    ts_data_unfiltered['lag_1_month'] = ts_data_unfiltered.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1)
    ts_data_unfiltered['rolling_mean_3_months'] = ts_data_unfiltered.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1).rolling(window=3).mean()
    ts_data_unfiltered['month_of_year'] = ts_data_unfiltered['DATE_COMMITTED'].dt.month
    ts_data_unfiltered['quarter_of_year'] = ts_data_unfiltered['DATE_COMMITTED'].dt.quarter
    ts_data_unfiltered = ts_data_unfiltered.dropna().reset_index(drop=True)

    # --- START OF THE UPGRADED LOGIC ---
    if not ts_data_unfiltered.empty:
        y_eval = ts_data_unfiltered['accident_count']
        X_eval = ts_data_unfiltered.drop(columns=['accident_count', 'DATE_COMMITTED'])

        # Use TimeSeriesSplit for more robust cross-validation
        tscv = TimeSeriesSplit(n_splits=4)
        all_y_test, all_forecasts = [], []
        
        print("Starting Cross-Validation for Performance Metrics...")
        
        for fold, (train_index, test_index) in enumerate(tscv.split(X_eval), 1):
            X_train, X_test = X_eval.iloc[train_index], X_eval.iloc[test_index]
            y_train, y_test = y_eval.iloc[train_index], y_eval.iloc[test_index]

            if X_test.empty:
                continue

            # Add early_stopping_rounds to prevent overfitting
            eval_model = XGBRegressor(objective='count:poisson', n_estimators=1000, learning_rate=0.01, 
                                    max_depth=4, min_child_weight=1, gamma=0.1, random_state=42,
                                    early_stopping_rounds=10)
            
            eval_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
            forecasts = eval_model.predict(X_test)

            all_y_test.append(y_test)
            all_forecasts.append(forecasts)
            fold_mae = mean_absolute_error(y_test, forecasts)
            print(f"Fold {fold} complete. MAE: {fold_mae:.2f}")

        print("Cross-validation complete.")

        # Aggregate results across all folds for a single set of metrics
        if all_y_test:
                y_test_full = pd.concat(all_y_test)
                forecasts_full = np.concatenate(all_forecasts)

                mae = mean_absolute_error(y_test_full, forecasts_full)
                mse = mean_squared_error(y_test_full, forecasts_full) # <-- NEW: Calculate MSE
                mape = mean_absolute_percentage_error(y_test_full.replace(0, 1e-6), forecasts_full) * 100
                r2 = r2_score(y_test_full, forecasts_full)
                rmse = np.sqrt(mse) # <-- Can now reuse the mse variable
                
                print(f"Mean Absolute Error (MAE): {mae:.2f}")
                print(f"Mean Absolute Percentage Error (MAPE): {mape:.2f}%")
                print(f"R-squared (R²): {r2:.2f}")
                print(f"Mean Squared Error (MSE): {mse:.2f}") # <-- NEW: Print MSE
                print(f"Root Mean Squared Error (RMSE): {rmse:.2f}\n")
        else:
            print("Warning: Not enough data to perform cross-validation.\n")
    else:
        print("Warning: Not enough data in the full dataset to perform an evaluation.\n")

    df_filtered = df_full.copy()
    df_filtered = df_filtered[df_filtered['ACCIDENT_HOTSPOT'] != -1].copy()
    df_filtered["DATE_COMMITTED"] = pd.to_datetime(df_filtered["DATE_COMMITTED"], errors="coerce")
    df_filtered = df_filtered.dropna(subset=["DATE_COMMITTED"]).copy()
    df_filtered["HOUR_COMMITTED"] = pd.to_numeric(df_filtered["HOUR_COMMITTED"], errors="coerce").astype("Int64")
    
    def parse_hour(hmm: str) -> int | None:
        if not hmm: return None
        try: return int(hmm.split(":")[0])
        except Exception: return None

    h_from, h_to = parse_hour(time_from), parse_hour(time_to)
    display_hour_str = ""
    use_range = (h_from is not None) and (h_to is not None)

    if use_range:
        # Time range is specified, so we filter by it.
        if h_from <= h_to: hours = list(range(h_from, h_to + 1))
        else: hours = list(range(h_from, 24)) + list(range(0, h_to + 1))
        
        # Ensure we don't try to filter on rows with no hour data
        df_filtered = df_filtered.dropna(subset=["HOUR_COMMITTED"])
        df_filtered = df_filtered[df_filtered["HOUR_COMMITTED"].astype(int).isin(hours)].copy()
        display_hour_str = f"{h_from:02d}:00–{h_to:02d}:00"
    else:
        # If no time filter is applied, we assume a full day's view
        display_hour_str = "00:00–23:00"

    # Redundant barangay and date filtering is now REMOVED from this section.
    
    safe_center_lat = df_filtered["LATITUDE"].astype(float).mean(); safe_center_lon = df_filtered["LONGITUDE"].astype(float).mean()
    if pd.isna(safe_center_lat) or pd.isna(safe_center_lon): safe_center_lat, safe_center_lon = DEFAULT_LOCATION

    if df_filtered.empty:
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()
        
    # --- Consistent aggregation logic from Part 1 ---
    time_cluster_cols_fcst = [c for c in df_filtered.columns if 'TIME_CLUSTER' in str(c)]
    for col in time_cluster_cols_fcst:
        df_filtered[col] = pd.to_numeric(df_filtered[col], errors='coerce').fillna(0).astype(int)

    agg_dict_fcst = {col: 'sum' for col in time_cluster_cols_fcst}
    agg_dict_fcst['OFFENSE'] = 'size' 

    ts_aggregated_fcst = (
        df_filtered.set_index('DATE_COMMITTED')
        .groupby(['ACCIDENT_HOTSPOT', pd.Grouper(freq='ME')])
        .agg(agg_dict_fcst)
        .rename(columns={'OFFENSE': 'accident_count'})
        .reset_index()
    )

    all_clusters_fcst = pd.DataFrame({'ACCIDENT_HOTSPOT': df_filtered['ACCIDENT_HOTSPOT'].unique()})
    
    if df_filtered.empty or df_filtered['DATE_COMMITTED'].isnull().all():
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=11)
        return m.get_root().render()

    month_range_fcst = pd.date_range(df_filtered['DATE_COMMITTED'].min(), df_filtered['DATE_COMMITTED'].max(), freq='ME')
    full_grid_fcst = pd.MultiIndex.from_product(
        [all_clusters_fcst['ACCIDENT_HOTSPOT'], month_range_fcst], names=['ACCIDENT_HOTSPOT','DATE_COMMITTED']
    ).to_frame(index=False)
    
    ts_data_for_forecast = pd.merge(
        full_grid_fcst, ts_aggregated_fcst, on=['ACCIDENT_HOTSPOT','DATE_COMMITTED'], how='left'
    ).fillna(0).sort_values(['ACCIDENT_HOTSPOT','DATE_COMMITTED']).reset_index(drop=True)

    ts_data_for_forecast['lag_1_month'] = ts_data_for_forecast.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1)
    ts_data_for_forecast['rolling_mean_3_months'] = ts_data_for_forecast.groupby('ACCIDENT_HOTSPOT')['accident_count'].shift(1).rolling(window=3).mean()
    ts_data_for_forecast['month_of_year'] = ts_data_for_forecast['DATE_COMMITTED'].dt.month
    ts_data_for_forecast['quarter_of_year'] = ts_data_for_forecast['DATE_COMMITTED'].dt.quarter
    ts_data_for_forecast = ts_data_for_forecast.dropna().reset_index(drop=True)

    if ts_data_for_forecast.empty:
        m = folium.Map(location=[safe_center_lat, safe_center_lon], zoom_start=13)
        return m.get_root().render()

    y_final = ts_data_for_forecast['accident_count']
    X_final = ts_data_for_forecast.drop(columns=['accident_count','DATE_COMMITTED'])
    X_final['ACCIDENT_HOTSPOT'] = X_final['ACCIDENT_HOTSPOT'].astype(int)
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

        feature_names = X_final.columns.tolist()
        
        preds_accum = []
        for i in range(months_to_forecast):
            
            current_X = current_features_df[feature_names]
            current_X['ACCIDENT_HOTSPOT'] = current_X['ACCIDENT_HOTSPOT'].astype(int)
            preds = final_model.predict(current_X)
            
            next_month = last_known_month + pd.DateOffset(months=i+1)
            preds_accum.append(pd.DataFrame({'ACCIDENT_HOTSPOT': current_features_df['ACCIDENT_HOTSPOT'].values, 'DATE_COMMITTED': next_month, 'accident_count': preds}))
            
            current_features_df['lag_1_month'] = preds
            current_features_df['rolling_mean_3_months'] = current_features_df.groupby('ACCIDENT_HOTSPOT')['lag_1_month'].transform(lambda x: x.rolling(3, 1).mean())
            
            nm = next_month + pd.DateOffset(months=1)
            current_features_df['month_of_year'] = nm.month
            current_features_df['quarter_of_year'] = nm.quarter
            
        future_forecast_df = pd.concat(preds_accum, ignore_index=True) if preds_accum else pd.DataFrame()

    if not hist_in_range.empty: hist_summary = (hist_in_range.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum().to_frame('Total_Actual_Accidents').reset_index())
    else: hist_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Actual_Accidents'])
    if not future_forecast_df.empty: future_summary = (future_forecast_df.groupby('ACCIDENT_HOTSPOT')['accident_count'].sum().to_frame('Total_Forecasted_Accidents').reset_index())
    else: future_summary = pd.DataFrame(columns=['ACCIDENT_HOTSPOT','Total_Forecasted_Accidents'])
    
    barangay_counts = (df_filtered.groupby(['ACCIDENT_HOTSPOT','BARANGAY']).size().to_frame('count').reset_index())
    
    # --- START OF MODIFICATION ---
    # 1. Create a formatted HTML list for ALL barangays in each hotspot
    def format_barangay_list(group):
        # Get unique barangay names and sort them alphabetically
        unique_barangays = sorted(group['BARANGAY'].unique())
        items = [f"<li>{name}</li>" for name in unique_barangays]
        # Return a single HTML string, adding a scrollbar if the list is long
        return '<ul style="margin: 5px 0 0 15px; padding: 0; max-height: 150px; overflow-y: auto;">' + "".join(items) + "</ul>"

    barangay_html_lists = (barangay_counts.groupby('ACCIDENT_HOTSPOT')
                                        .apply(format_barangay_list)
                                        .to_frame(name='Barangay_HTML')
                                        .reset_index())

    centroids = (df_filtered.groupby('ACCIDENT_HOTSPOT').agg(Center_Lat=('LATITUDE','mean'), Center_Lon=('LONGITUDE','mean')).reset_index())

    # 2. Merge this new DataFrame instead of the old 'top_barangays' one
    final_map_data = (pd.DataFrame({'ACCIDENT_HOTSPOT': df_filtered['ACCIDENT_HOTSPOT'].unique()})
        .merge(hist_summary, on='ACCIDENT_HOTSPOT', how='left')
        .merge(future_summary, on='ACCIDENT_HOTSPOT', how='left')
        .merge(centroids, on='ACCIDENT_HOTSPOT', how='left')
        .merge(barangay_html_lists, on='ACCIDENT_HOTSPOT', how='left')) # <-- This merge is changed
    # --- END OF MODIFICATION ---

    final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']] = final_map_data[['Total_Actual_Accidents','Total_Forecasted_Accidents']].fillna(0).astype(float)
    final_map_data['Total_Events'] = final_map_data['Total_Actual_Accidents'] + final_map_data['Total_Forecasted_Accidents']
    
    final_map_data = final_map_data[final_map_data['ACCIDENT_HOTSPOT'] != -1].copy()
    
    nz = final_map_data.loc[final_map_data['Total_Events'] > 0, 'Total_Events']
    median_th, high_th = (nz.quantile(0.50), nz.quantile(0.75)) if not nz.empty else (0.0, 0.0)
    def color_for(v):
        if v <= 0: return 'grey'
        if v <= median_th: return 'green'
        if v <= high_th: return '#ffb200'
        return 'red'
     
    map_center_lat = df_filtered["LATITUDE"].astype(float).mean()
    map_center_lon = df_filtered["LONGITUDE"].astype(float).mean()
    if pd.isna(map_center_lat) or pd.isna(map_center_lon):
        map_center_lat, map_center_lon = DEFAULT_LOCATION

    font_css = """
    <style>
        @font-face {
        font-family: "Chillax";
        src: url("/static/fonts/Chillax-Medium.ttf") format("truetype");
        font-weight: 400; font-style: normal;
        }
        @font-face {
        font-family: "Chillax";
        src: url("/static/fonts/Chillax-Semibold.woff2") format("woff2");
        font-weight: 700; font-style: normal;
        }
    </style>"""
    m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=13)
    m.get_root().header.add_child(folium.Element(font_css))
        
    for _, row in final_map_data.iterrows():
        if pd.isna(row['Center_Lat']) or pd.isna(row['Center_Lon']): 
            continue
        lat, lng = float(row['Center_Lat']), float(row['Center_Lon'])

        # --- START OF MODIFICATION ---
        # 3. Use the pre-formatted HTML string directly in the popup
        barangay_html = row.get('Barangay_HTML', '<p style="margin: 5px 0;">N/A</p>') # Get the HTML, with a fallback
        streetview_url = f"https://www.google.com/maps?q=&layer=c&cbll={lat},{lng}&cbp=12,90,0,0,5"
        popup_html = f"""
        <div style="font-family: 'Chillax', sans-serif; font-weight: 400; max-width: 250px; color: #1e1e1e;">
            <h4 style="margin: 0 0 8px; padding-bottom: 5px; border-bottom: 1px solid #eee; font-weight: 700; color: #1e1e1e;">
                Hotspot #{int(row['ACCIDENT_HOTSPOT'])}
            </h4>
            <p style="margin: 5px 0;"><strong>Time:</strong> {display_hour_str}</p>
            <p style="margin: 5px 0;"><strong>Barangays in Hotspot:</strong></p>
            {barangay_html}
            <hr style="border: 0; border-top: 1px solid #eee; margin: 10px 0;">
            {f"<p style='margin: 5px 0;'><strong>Actual (Hist.):</strong> {int(row['Total_Actual_Accidents'])}</p>" if row['Total_Actual_Accidents'] > 0 else ""}
            {f"<p style='margin: 5px 0;'><strong>Forecasted:</strong> {row['Total_Forecasted_Accidents']:.2f}</p>" if row['Total_Forecasted_Accidents'] > 0 else ""}
            <a href="{streetview_url}" target="_blank" style="display: inline-block; width: 100%; box-sizing: border-box; text-align: center; margin-top: 10px; padding: 8px 12px; background-color: #0437F2; color: white; text-decoration: none; border-radius: 5px; font-weight: 700; font-family: 'Chillax', sans-serif;">
                Open Street View
            </a>
        </div>"""
        # --- END OF MODIFICATION ---

        color = color_for(float(row['Total_Events']))
        radius = 5 + (np.log1p(float(row['Total_Events'])) * 5)
        folium.CircleMarker(
            location=[lat, lng], radius=radius, popup=folium.Popup(popup_html, max_width=300), 
            color=color, fill=True, fill_color=color, fill_opacity=0.8
        ).add_to(m)
        
    return m.get_root().render()