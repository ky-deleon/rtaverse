# In dashboard_forecasting.py

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor
from ..extensions import get_engine

# --- Replace the entire run_categorical_forecast function ---
def run_categorical_forecast(
    table_name: str,
    grouping_key: str,
    model_type: str = 'random_forest',
    forecast_horizon: int = 12,
    where_sql: str = "",
    params: dict = None
):
    engine = get_engine()
    
    GROUPING_ALIAS = "category"
    is_simple_column = ' ' not in grouping_key and '(' not in grouping_key
    grouping_key_sql = f"`{grouping_key}`" if is_simple_column else grouping_key
    
    query_sql = f"SELECT {grouping_key_sql} AS {GROUPING_ALIAS}, `DATE_COMMITTED` FROM `{table_name}`"
    base_conditions = f"WHERE {grouping_key_sql} IS NOT NULL AND `DATE_COMMITTED` IS NOT NULL"
    final_where_sql = base_conditions + (where_sql.replace("WHERE", "AND") if where_sql else "")
    final_sql = f"{query_sql} {final_where_sql}"

    df = pd.read_sql_query(final_sql, engine, params=params, parse_dates=["DATE_COMMITTED"])

    if df.empty:
        return {"success": False, "message": "No data found for the selected filters."}

    if not pd.api.types.is_numeric_dtype(df[GROUPING_ALIAS]):
        df = df[df[GROUPING_ALIAS].str.strip() != '']
    
    all_categories = sorted(df[GROUPING_ALIAS].unique())

    ts = (df.groupby([pd.Grouper(key="DATE_COMMITTED", freq="ME"), GROUPING_ALIAS])
            .size().to_frame("count").reset_index())
            
    if ts.empty or len(ts) < 2:
        return {"success": False, "message": "Not enough data to create a time-series."}

    date_range = pd.date_range(ts['DATE_COMMITTED'].min(), ts['DATE_COMMITTED'].max(), freq='ME')
    full_grid = pd.MultiIndex.from_product([date_range, all_categories], names=['DATE_COMMITTED', GROUPING_ALIAS])
    
    ts = (ts.set_index(['DATE_COMMITTED', GROUPING_ALIAS])
            .reindex(full_grid, fill_value=0).reset_index()
            .sort_values(['DATE_COMMITTED', GROUPING_ALIAS]))

    ts_sorted = ts.sort_values([GROUPING_ALIAS, 'DATE_COMMITTED'])
    grouped = ts_sorted.groupby(GROUPING_ALIAS)
    
    ts['lag_1_month'] = grouped['count'].shift(1)
    ts['lag_2_month'] = grouped['count'].shift(2)
    ts['lag_3_month'] = grouped['count'].shift(3)
    ts['rolling_mean_3'] = grouped['count'].shift(1).rolling(window=3, min_periods=1).mean()
    ts['month'] = ts['DATE_COMMITTED'].dt.month

    features_with_potential_nans = ['lag_1_month', 'lag_2_month', 'lag_3_month', 'rolling_mean_3']
    ts = ts.dropna(subset=features_with_potential_nans).reset_index(drop=True)

    if ts.empty:
        return {"success": False, "message": "Not enough historical data for features (need at least 3 months)."}

    ts[GROUPING_ALIAS] = pd.Categorical(ts[GROUPING_ALIAS], categories=all_categories, ordered=True)
    category_mapping = dict(enumerate(ts[GROUPING_ALIAS].cat.categories))
    ts[GROUPING_ALIAS + '_code'] = ts[GROUPING_ALIAS].cat.codes

    feature_cols = ['lag_1_month', 'lag_2_month', 'lag_3_month', 'rolling_mean_3', 'month', GROUPING_ALIAS + '_code']
    X_train = ts[feature_cols]
    y_train = ts['count']

    # Determine proper display name for the model
    model_display_name = 'Random Forest'
    if model_type.lower() == 'adaboost':
        model = DecisionTreeRegressor(max_depth=5, random_state=42)
        model_display_name = 'Decision Tree'
    else:
        model = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2, n_jobs=-1)
        model_display_name = 'Random Forest'
    
    model.fit(X_train, y_train)

    last_month = ts['DATE_COMMITTED'].max()
    future_dates = pd.date_range(start=last_month + pd.DateOffset(months=1), periods=forecast_horizon, freq='ME')
    
    last_known_data = ts.loc[ts.groupby(GROUPING_ALIAS + '_code')['DATE_COMMITTED'].idxmax()]
    last_features_df = last_known_data[feature_cols].copy()

    all_predictions = []
    for date in future_dates:
        predictions = model.predict(last_features_df)
        
        preds_df = pd.DataFrame({
            GROUPING_ALIAS + '_code': last_features_df[GROUPING_ALIAS + '_code'],
            'DATE_COMMITTED': date,
            'forecast_count': np.round(predictions).astype(int)
        })
        all_predictions.append(preds_df)

        next_features_df = pd.DataFrame()
        next_features_df[GROUPING_ALIAS + '_code'] = last_features_df[GROUPING_ALIAS + '_code']
        next_features_df['lag_3_month'] = last_features_df['lag_2_month']
        next_features_df['lag_2_month'] = last_features_df['lag_1_month']
        next_features_df['lag_1_month'] = predictions
        next_features_df['month'] = date.month
        next_features_df['rolling_mean_3'] = next_features_df[['lag_1_month', 'lag_2_month', 'lag_3_month']].mean(axis=1)

        last_features_df = next_features_df[feature_cols]
        
    if not all_predictions:
        return {"success": False, "message": "Could not generate future predictions."}
        
    forecast_df = pd.concat(all_predictions, ignore_index=True)
    forecast_df[GROUPING_ALIAS] = forecast_df[GROUPING_ALIAS + '_code'].map(category_mapping)

    historical_summary = ts.groupby(GROUPING_ALIAS)['count'].sum().astype(int)
    forecast_summary = forecast_df.groupby(GROUPING_ALIAS)['forecast_count'].sum().astype(int)
    
    results_df = pd.DataFrame({
        'historical': historical_summary,
        'forecast': forecast_summary
    }).reindex(all_categories).fillna(0).astype(int).reset_index()
    
    results_df = results_df.rename(columns={'index': GROUPING_ALIAS})
    results_df = results_df.sort_values(by=GROUPING_ALIAS).reset_index(drop=True)

    return {
        "success": True,
        "data": {
            "labels": results_df[GROUPING_ALIAS].tolist(),
            "historical": results_df['historical'].tolist(),
            "forecast": results_df['forecast'].tolist(),
            "model_used": model_display_name, # --- FIX: Send display name
            "horizon": forecast_horizon
        }
    }

# Keep run_numerical_forecast as it was in the previous step
# ... (run_numerical_forecast code) ...

# --- Replace the entire run_numerical_forecast function ---
def run_numerical_forecast(
    table_name: str,
    grouping_key: str,
    target_column: str,
    model_type: str = 'random_forest',
    forecast_horizon: int = 12,
    where_sql: str = "",
    params: dict = None
):
    engine = get_engine()
    
    GROUPING_ALIAS = "category"
    TARGET_ALIAS = "target_sum"

    is_simple_column = ' ' not in grouping_key and '(' not in grouping_key
    grouping_key_sql = f"`{grouping_key}`" if is_simple_column else grouping_key
    
    query_sql = f"SELECT {grouping_key_sql} AS {GROUPING_ALIAS}, `DATE_COMMITTED`, `{target_column}` FROM `{table_name}`"
    base_conditions = f"WHERE {grouping_key_sql} IS NOT NULL AND `DATE_COMMITTED` IS NOT NULL AND `{target_column}` IS NOT NULL"
    final_where_sql = base_conditions + (where_sql.replace("WHERE", "AND") if where_sql else "")
    final_sql = f"{query_sql} {final_where_sql}"

    df = pd.read_sql_query(final_sql, engine, params=params, parse_dates=["DATE_COMMITTED"])

    if df.empty:
        return {"success": False, "message": f"No data for target '{target_column}'."}

    ts = (df.groupby([pd.Grouper(key="DATE_COMMITTED", freq="ME"), GROUPING_ALIAS])
            .agg(**{TARGET_ALIAS: (target_column, 'sum')})
            .reset_index())

    all_categories = sorted(df[GROUPING_ALIAS].unique())
    date_range = pd.date_range(ts['DATE_COMMITTED'].min(), ts['DATE_COMMITTED'].max(), freq='ME')
    full_grid = pd.MultiIndex.from_product([date_range, all_categories], names=['DATE_COMMITTED', GROUPING_ALIAS])
    
    ts = (ts.set_index(['DATE_COMMITTED', GROUPING_ALIAS])
            .reindex(full_grid, fill_value=0).reset_index()
            .sort_values(['DATE_COMMITTED', GROUPING_ALIAS]))

    ts_sorted = ts.sort_values([GROUPING_ALIAS, 'DATE_COMMITTED'])
    grouped = ts_sorted.groupby(GROUPING_ALIAS)
    
    ts['lag_1_month'] = grouped[TARGET_ALIAS].shift(1)
    ts['lag_2_month'] = grouped[TARGET_ALIAS].shift(2)
    ts['lag_3_month'] = grouped[TARGET_ALIAS].shift(3)
    ts['rolling_mean_3'] = grouped[TARGET_ALIAS].shift(1).rolling(window=3, min_periods=1).mean()
    ts['month'] = ts['DATE_COMMITTED'].dt.month
    
    features_with_potential_nans = ['lag_1_month', 'lag_2_month', 'lag_3_month', 'rolling_mean_3']
    ts = ts.dropna(subset=features_with_potential_nans).reset_index(drop=True)

    if ts.empty:
        return {"success": False, "message": "Not enough historical data for numerical forecast."}

    ts[GROUPING_ALIAS] = pd.Categorical(ts[GROUPING_ALIAS], categories=all_categories, ordered=True)
    category_mapping = dict(enumerate(ts[GROUPING_ALIAS].cat.categories))
    ts[GROUPING_ALIAS + '_code'] = ts[GROUPING_ALIAS].cat.codes

    feature_cols = ['lag_1_month', 'lag_2_month', 'lag_3_month', 'rolling_mean_3', 'month', GROUPING_ALIAS + '_code']
    X_train = ts[feature_cols]
    y_train = ts[TARGET_ALIAS]

    # --- START OF MODEL CHANGE ---
    if model_type.lower() == 'adaboost':
        # Now uses DecisionTreeRegressor instead of AdaBoost
        model = DecisionTreeRegressor(max_depth=5, random_state=42)
    else:
        # Default remains RandomForest
        model = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2, n_jobs=-1)
    # --- END OF MODEL CHANGE ---
    
    model.fit(X_train, y_train)

    last_month = ts['DATE_COMMITTED'].max()
    future_dates = pd.date_range(start=last_month + pd.DateOffset(months=1), periods=forecast_horizon, freq='ME')
    
    last_known_data = ts.loc[ts.groupby(GROUPING_ALIAS + '_code')['DATE_COMMITTED'].idxmax()]
    last_features_df = last_known_data[feature_cols].copy()

    all_predictions = []
    for date in future_dates:
        predictions = model.predict(last_features_df)
        
        preds_df = pd.DataFrame({
            GROUPING_ALIAS + '_code': last_features_df[GROUPING_ALIAS + '_code'],
            'forecast_sum': np.round(predictions).astype(int)
        })
        all_predictions.append(preds_df)

        next_features_df = pd.DataFrame()
        next_features_df[GROUPING_ALIAS + '_code'] = last_features_df[GROUPING_ALIAS + '_code']
        next_features_df['lag_3_month'] = last_features_df['lag_2_month']
        next_features_df['lag_2_month'] = last_features_df['lag_1_month']
        next_features_df['lag_1_month'] = predictions
        next_features_df['month'] = date.month
        next_features_df['rolling_mean_3'] = next_features_df[['lag_1_month', 'lag_2_month', 'lag_3_month']].mean(axis=1)
        last_features_df = next_features_df[feature_cols]

    forecast_df = pd.concat(all_predictions, ignore_index=True)
    forecast_df[GROUPING_ALIAS] = forecast_df[GROUPING_ALIAS + '_code'].map(category_mapping)

    historical_summary = ts.groupby(GROUPING_ALIAS)[TARGET_ALIAS].sum().astype(int)
    forecast_summary = forecast_df.groupby(GROUPING_ALIAS)['forecast_sum'].sum().astype(int)
    
    results_df = pd.DataFrame({
        'historical': historical_summary,
        'forecast': forecast_summary
    }).reindex(all_categories).fillna(0).astype(int).reset_index()
    
    results_df = results_df.rename(columns={'index': GROUPING_ALIAS})
    
    return {
        "success": True,
        "labels": results_df[GROUPING_ALIAS].tolist(),
        "historical": results_df['historical'].tolist(),
        "forecast": results_df['forecast'].tolist(),
    }
    
# In app/services/dashboard_forecasting.py

# In app/services/dashboard_forecasting.py

def run_overall_timeseries_forecast(
    table_name: str,
    model_type: str = 'random_forest',
    forecast_horizon: int = 12,
    where_sql: str = "",
    params: dict = None
):
    engine = get_engine()
    
    query_sql = f"SELECT `DATE_COMMITTED` FROM `{table_name}`"
    base_conditions = "WHERE `DATE_COMMITTED` IS NOT NULL"
    final_where_sql = base_conditions + (where_sql.replace("WHERE", "AND") if where_sql else "")
    final_sql = f"{query_sql} {final_where_sql}"

    df = pd.read_sql_query(final_sql, engine, params=params, parse_dates=["DATE_COMMITTED"])

    if df.empty:
        return {"success": False, "message": "No data found for the selected filters."}

    # --- START OF FIX ---

    # 1. Create the full time series. We will use this for the historical plot.
    ts_full = df.set_index('DATE_COMMITTED').resample('ME').size().to_frame('count')

    if len(ts_full) < 4:
        return {"success": False, "message": "Not enough historical data (need at least 4 months)."}

    # 2. Engineer features on the full series. This will create NaNs at the start.
    ts_full['lag_1_month'] = ts_full['count'].shift(1)
    ts_full['lag_2_month'] = ts_full['count'].shift(2)
    ts_full['lag_3_month'] = ts_full['count'].shift(3)
    ts_full['rolling_mean_3'] = ts_full['count'].shift(1).rolling(window=3, min_periods=1).mean()
    ts_full['month'] = ts_full.index.month
    
    # 3. Create a separate, clean DataFrame for TRAINING by dropping the NaNs.
    ts_train = ts_full.dropna().reset_index()

    if ts_train.empty:
        return {"success": False, "message": "Not enough data after feature engineering."}

    # 4. Use the 'ts_train' DataFrame for training the model.
    feature_cols = ['lag_1_month', 'lag_2_month', 'lag_3_month', 'rolling_mean_3', 'month']
    X_train = ts_train[feature_cols]
    y_train = ts_train['count']

    model_display_name = 'Random Forest'
    if model_type.lower() == 'decision_tree':
        model = DecisionTreeRegressor(max_depth=5, random_state=42)
        model_display_name = 'Decision Tree'
    else:
        model = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=2, n_jobs=-1)
    
    model.fit(X_train, y_train)

    # 5. The forecasting loop starts from the last known features of the TRAINING data.
    future_predictions = []
    last_known_features = ts_train[feature_cols].iloc[-1].to_dict()
    current_features_df = pd.DataFrame([last_known_features])
    last_known_date = ts_train['DATE_COMMITTED'].iloc[-1]
    future_dates = pd.date_range(start=last_known_date + pd.DateOffset(months=1), periods=forecast_horizon, freq='ME')

    for date in future_dates:
        prediction = model.predict(current_features_df[feature_cols])[0]
        future_predictions.append(int(np.round(prediction)))
        prev_lag_1 = current_features_df['lag_1_month'].iloc[0]
        prev_lag_2 = current_features_df['lag_2_month'].iloc[0]
        new_features = {
            'lag_1_month': prediction,
            'lag_2_month': prev_lag_1,
            'lag_3_month': prev_lag_2,
            'rolling_mean_3': np.mean([prediction, prev_lag_1, prev_lag_2]),
            'month': date.month
        }
        current_features_df = pd.DataFrame([new_features])

    # 6. Prepare the response payload, using the ORIGINAL 'ts_full' for historical data.
    historical_dates = ts_full.index.strftime('%Y-%m-%d').tolist()
    historical_counts = ts_full['count'].astype(int).tolist()
    forecast_dates = [d.strftime('%Y-%m-%d') for d in future_dates]

    return {
        "success": True,
        "data": {
            "historical": {
                "dates": historical_dates,
                "counts": historical_counts
            },
            "forecast": {
                "dates": forecast_dates,
                "counts": future_predictions
            },
            "model_used": model_display_name,
            "horizon": forecast_horizon
        }
    }
    # --- END OF FIX ---