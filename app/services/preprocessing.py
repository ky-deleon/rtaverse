from datetime import time, timedelta, datetime
import io
from ..extensions import get_db_connection
from typing import Optional
import re
import datetime
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
import io, re
from datetime import time, timedelta
from .database import ensure_indexes

# === lifted from your app.py and kept functionally identical ===

def make_display_copy(df: pd.DataFrame) -> pd.DataFrame:
    # ... (same logic as your current make_display_copy)
    import numpy as np, pandas as pd
    out = df.copy()
    def _safe_num(s): return pd.to_numeric(s, errors="coerce")
    def _safe_arctan2(sin_s, cos_s):
        sin_v = _safe_num(sin_s); cos_v = _safe_num(cos_s)
        ok = sin_v.notna() & cos_v.notna()
        ang = pd.Series(np.nan, index=sin_v.index, dtype="float64")
        ang.loc[ok] = np.arctan2(sin_v.loc[ok].astype(float), cos_v.loc[ok].astype(float))
        return ang
    if {"MONTH_SIN","MONTH_COS"}.issubset(out.columns):
        angle = _safe_arctan2(out["MONTH_SIN"], out["MONTH_COS"])
        angle = np.mod(angle, 2*np.pi); month_float = angle/(2*np.pi)*12
        month_int = np.rint(month_float).astype("Int64"); month_int = month_int.where(month_int!=0, 12).clip(1,12)
        out["MONTH"] = month_int
    if {"DAYOWEEK_SIN","DAYOWEEK_COS"}.issubset(out.columns):
        angle = _safe_arctan2(out["DAYOWEEK_SIN"], out["DAYOWEEK_COS"])
        angle = np.mod(angle, 2*np.pi)
        dow_num = ((angle/(2*np.pi)*7).round().astype("Int64")) % 7
        out["DAY_OF_WEEK"] = dow_num.map({0:"Monday",1:"Tuesday",2:"Wednesday",3:"Thursday",4:"Friday",5:"Saturday",6:"Sunday"})
    if "HOUR_COMMITTED" in out.columns:
        hr = pd.to_numeric(out["HOUR_COMMITTED"], errors="coerce").round().astype("Int64")
        out["TIME"] = hr.astype(str) + ":00"
    if "TIME_COMMITTED" in out.columns:
        try:
            tdelta = pd.to_timedelta(out["TIME_COMMITTED"], errors="coerce")
            out["TIME_COMMITTED"] = tdelta.dt.components["hours"].astype(str).str.zfill(2)+":"+tdelta.dt.components["minutes"].astype(str).str.zfill(2)
        except Exception: pass
    if "HOUR_COMMITTED" in out.columns or "TIME_COMMITTED" in out.columns:
        if "HOUR_COMMITTED" in out.columns:
            hrs = pd.to_numeric(out["HOUR_COMMITTED"], errors="coerce")
        else:
            hrs = pd.Series(pd.NA, index=out.index, dtype="float")
        if hrs.isna().any() and "TIME_COMMITTED" in out.columns:
            tdelta = pd.to_timedelta(out["TIME_COMMITTED"], errors="coerce")
            hrs = hrs.fillna((tdelta.dt.seconds // 3600).astype("float"))
        conds = [(hrs>=6)&(hrs<=9),(hrs>=10)&(hrs<=15),(hrs>=16)&(hrs<=19)]
        out["TIME_CLUSTER"] = np.select(conds, ["Morning","Midday","Evening"], default="Midnight").astype("object")
    g_ohe = [c for c in ["GENDER_Male","GENDER_Unknown"] if c in out.columns]
    if g_ohe:
        g = pd.Series(pd.NA, index=out.index, dtype="object")
        if "GENDER_Male" in out.columns: g.loc[pd.to_numeric(out["GENDER_Male"], errors="coerce").fillna(0).astype(int).eq(1)] = "Male"
        if "GENDER_Unknown" in out.columns: g.loc[pd.to_numeric(out["GENDER_Unknown"], errors="coerce").fillna(0).astype(int).eq(1)] = "Unknown"
        out["GENDER_CLUSTER"] = g.fillna("Female")
    a_ohe = [c for c in ["ALCOHOL_USED_Yes","ALCOHOL_USED_Unknown"] if c in out.columns]
    if a_ohe:
        a = pd.Series(pd.NA, index=out.index, dtype="object")
        if "ALCOHOL_USED_Yes" in out.columns: a.loc[pd.to_numeric(out["ALCOHOL_USED_Yes"], errors="coerce").fillna(0).astype(int).eq(1)] = "Yes"
        if "ALCOHOL_USED_Unknown" in out.columns: a.loc[pd.to_numeric(out["ALCOHOL_USED_Unknown"], errors="coerce").fillna(0).astype(int).eq(1)] = "Unknown"
        out["ALCOHOL_USED_CLUSTER"] = a.fillna("No")
    if any(c.startswith("Season_") for c in out.columns):
        s = pd.Series(pd.NA, index=out.index, dtype="object")
        if "Season_Rainy" in out.columns:
            s.loc[pd.to_numeric(out["Season_Rainy"], errors="coerce").fillna(0).astype(int).eq(1)] = "Rainy"
        if "Season_Dry" in out.columns:
            s.loc[pd.to_numeric(out["Season_Dry"], errors="coerce").fillna(0).astype(int).eq(1)] = "Dry"
        out["Season"] = s.fillna("Unknown") # <--- ADDED SEASON CLUSTER RECONSTRUCTION
    return out

def apply_additional_preprocessing(merged: pd.DataFrame) -> pd.DataFrame:
    """
    Clean + engineer features consistently with your Colab notebook:
      - DATE_COMMITTED sin/cos (month & day-of-week)
      - HOUR_COMMITTED from TIME_COMMITTED (robust for multiple types)
      - OFFENSE collapsed to 4 buckets with de-dup by spatiotemporal keys
      - DBSCAN hotspots with eps = 0.04 km (haversine)
      - TIME_CLUSTER bins (Midnight/Morning/Midday/Evening)
      - One-hot encode GENDER, ALCOHOL_USED, TIME_CLUSTER (NO drop_first)
      - Reconstruct readable cluster labels from dummies
    """

    df = merged.copy()

    # --- Dates → month/day-of-week sin/cos -----------------------------------
    # Accept either DATE_COMMITTED or legacy "DATE COMMITTED"
    if "DATE_COMMITTED" not in df.columns and "DATE COMMITTED" in df.columns:
        df = df.rename(columns={"DATE COMMITTED": "DATE_COMMITTED"})
    if "DATE_COMMITTED" in df.columns:
        dt = pd.to_datetime(df["DATE_COMMITTED"], errors="coerce")
        df["MONTH_SIN"]    = np.sin(2*np.pi*dt.dt.month/12.0)
        df["MONTH_COS"]    = np.cos(2*np.pi*dt.dt.month/12.0)
        df["DAYOWEEK_SIN"] = np.sin(2*np.pi*dt.dt.dayofweek/7.0)
        df["DAYOWEEK_COS"] = np.cos(2*np.pi*dt.dt.dayofweek/7.0)

    # --- NEW: Add SEASON_CLUSTER based on PAGASA definition ---
        month = dt.dt.month
        conditions = [
            (month >= 6) & (month <= 11),  # Rainy: June to November
            (month == 12) | (month <= 5)   # Dry: December to May
        ]
        choices = ["Rainy", "Dry"]
        df["SEASON_CLUSTER"] = np.select(conditions, choices, default="Unknown").astype("object")

    # --- Time → hour committed (robust) --------------------------------------
    # Accept TIME_COMMITTED or legacy "TIME COMMITTED"
    if "TIME_COMMITTED" not in df.columns and "TIME COMMITTED" in df.columns:
        df = df.rename(columns={"TIME COMMITTED": "TIME_COMMITTED"})

    if "TIME_COMMITTED" in df.columns and "HOUR_COMMITTED" not in df.columns:
        def _extract_hour(val):
            # Missing
            if pd.isna(val):
                return np.nan
            # Already datetime.time
            if isinstance(val, datetime.time):
                return val.hour
            # Pandas/py datetime
            if isinstance(val, (pd.Timestamp, datetime.datetime)):
                return val.hour
            # Numeric hour (e.g., 13 or 13.0)
            if isinstance(val, (int, float, np.integer, np.floating)):
                try:
                    if np.isnan(val):  # type: ignore[arg-type]
                        return np.nan
                except Exception:
                    pass
                return int(val) if 0 <= int(val) <= 23 else np.nan
            # String like "13:45:00" / "13:45"
            if isinstance(val, str):
                # Try strict HH:MM:SS then fallback
                ts = pd.to_datetime(val, errors="coerce", format="%H:%M:%S")
                if pd.isna(ts):
                    ts = pd.to_datetime(val, errors="coerce")  # let pandas guess
                return ts.hour if not pd.isna(ts) else np.nan
            # Fallback
            return np.nan

        df["HOUR_COMMITTED"] = df["TIME_COMMITTED"].apply(_extract_hour)

    # --- START OF FIX ---
    if "HOUR_COMMITTED" in df.columns:
        df["HOUR_COMMITTED"] = pd.to_numeric(df["HOUR_COMMITTED"], errors="coerce")
        # MODIFIED: Use nullable Int64 to handle missing hours instead of dropping rows.
        df["HOUR_COMMITTED"] = df["HOUR_COMMITTED"].astype("Int64").clip(lower=0, upper=23)
    # --- END OF FIX ---

    # --- Clean up legacy raw columns if still present -------------------------
    df.drop(columns=["DATE COMMITTED", "TIME COMMITTED"], inplace=True, errors="ignore")

    # --- Numeric hygiene ------------------------------------------------------
    if "AGE" in df.columns:
        df["AGE"] = pd.to_numeric(df["AGE"], errors="coerce")
        df["AGE"] = df["AGE"].fillna(df["AGE"].median()).astype(int)

    if "VICTIM COUNT" in df.columns:
        df["VICTIM COUNT"] = pd.to_numeric(df["VICTIM COUNT"], errors="coerce")
        df["VICTIM COUNT"] = df["VICTIM COUNT"].fillna(df["VICTIM COUNT"].median()).astype(int)

    # --- Collapse OFFENSE and deduplicate by spatiotemporal keys -------------
    target_col = "OFFENSE"
    if target_col in df.columns:
        homicide_pattern = "HOMICIDE"
        physical_injury_pattern = "PHYSICAL INJURY"
        property_damage_pattern = "DAMAGE TO PROPERTY"

        df["IS_PERSON"] = df[target_col].astype(str).str.contains(
            f"{homicide_pattern}|{physical_injury_pattern}", regex=True, na=False
        )
        df["IS_PROPERTY"] = df[target_col].astype(str).str.contains(
            property_damage_pattern, regex=False, na=False
        )

        grouping_keys = [
            "MONTH_SIN", "MONTH_COS", "DAYOWEEK_SIN", "DAYOWEEK_COS",
            "HOUR_COMMITTED", "LATITUDE", "LONGITUDE"
        ]
        agg_funcs = {"IS_PERSON": "any", "IS_PROPERTY": "any"}

        other_cols = [c for c in df.columns
                      if c not in grouping_keys + [target_col, "IS_PERSON", "IS_PROPERTY"]]
        for c in other_cols:
            agg_funcs[c] = "first"

        df = df.groupby(grouping_keys, as_index=False).agg(agg_funcs)

        def _assign_offense(row):
            if row["IS_PROPERTY"] and row["IS_PERSON"]:
                return "Property_and_Person"
            if row["IS_PERSON"]:
                return "Person_Injury_Only"
            if row["IS_PROPERTY"]:
                return "Property_Damage_Only"
            return "Other"

        df[target_col] = df.apply(_assign_offense, axis=1)
        df.drop(columns=["IS_PERSON", "IS_PROPERTY"], inplace=True)

    # --- Ensure coords, then DBSCAN hotspots (ε = 0.04 km) -------------------
    for req in ("LATITUDE", "LONGITUDE"):
        if req not in df.columns:
            df[req] = pd.NA

    df = df.dropna(subset=["LATITUDE", "LONGITUDE"]).copy()
    if not df.empty:
        kms_per_radian = 6371.0088
        epsilon = 0.04 / kms_per_radian  # match Colab exactly
        dbscan = DBSCAN(eps=epsilon, min_samples=5, algorithm="ball_tree", metric="haversine")
        coords_rad = np.radians(df[["LATITUDE", "LONGITUDE"]])
        df["ACCIDENT_HOTSPOT"] = dbscan.fit_predict(coords_rad)

    # --- TIME_CLUSTER bins ----------------------------------------------------
    def _time_cluster(h):
        try:
            h = int(h)
        except Exception:
            return "Midnight"
        if 6 <= h <= 11:
            return "Morning"
        if 12 <= h <= 17:
            return "Midday"
        if 18 <= h <= 23:
            return "Evening"
        return "Midnight"

    if "HOUR_COMMITTED" in df.columns:
        df["TIME_CLUSTER"] = df["HOUR_COMMITTED"].apply(_time_cluster).astype("object")


    # --- One-hot encode (NO drop_first to match Colab/your visuals) ----------
    for cat_col in ["GENDER", "ALCOHOL_USED", "TIME_CLUSTER", "SEASON_CLUSTER"]: # <-- ADDED
        if cat_col in df.columns:
            dummies = pd.get_dummies(df[cat_col], prefix=cat_col, dtype="int64")  # keep all categories
            # ensure stable set of expected columns
            expected = {
                "GENDER": ["GENDER_Female", "GENDER_Male", "GENDER_Unknown"],
                "ALCOHOL_USED": ["ALCOHOL_USED_No", "ALCOHOL_USED_Yes", "ALCOHOL_USED_Unknown"],
                "TIME_CLUSTER": ["TIME_CLUSTER_Midnight", "TIME_CLUSTER_Morning",
                                 "TIME_CLUSTER_Midday", "TIME_CLUSTER_Evening"],
                # --- NEW ---
                "SEASON_CLUSTER": ["SEASON_CLUSTER_Dry", "SEASON_CLUSTER_Rainy", "SEASON_CLUSTER_Unknown"],
                # --- END NEW ---
            }[cat_col]
            for col in expected:
                if col not in dummies.columns:
                    dummies[col] = 0
            dummies = dummies[sorted(dummies.columns)]
            df = pd.concat([df.drop(columns=[cat_col]), dummies], axis=1)

    # --- Reconstruct readable labels (for display/filters) --------------------
    if any(c.startswith("GENDER_") for c in df.columns):
        g = pd.Series(pd.NA, index=df.index, dtype="object")
        if "GENDER_Male" in df.columns:
            g.loc[pd.to_numeric(df["GENDER_Male"], errors="coerce").fillna(0).astype(int).eq(1)] = "Male"
        if "GENDER_Unknown" in df.columns:
            g.loc[pd.to_numeric(df["GENDER_Unknown"], errors="coerce").fillna(0).astype(int).eq(1)] = "Unknown"
        df["GENDER_CLUSTER"] = g.fillna("Female")

    if any(c.startswith("ALCOHOL_USED_") for c in df.columns):
        a = pd.Series(pd.NA, index=df.index, dtype="object")
        if "ALCOHOL_USED_Yes" in df.columns:
            a.loc[pd.to_numeric(df["ALCOHOL_USED_Yes"], errors="coerce").fillna(0).astype(int).eq(1)] = "Yes"
        if "ALCOHOL_USED_Unknown" in df.columns:
            a.loc[pd.to_numeric(df["ALCOHOL_USED_Unknown"], errors="coerce").fillna(0).astype(int).eq(1)] = "Unknown"
        df["ALCOHOL_USED_CLUSTER"] = a.fillna("No")

    # --- NEW: Reconstruct SEASON_CLUSTER from dummies ---
    if any(c.startswith("SEASON_CLUSTER_") for c in df.columns):
        s = pd.Series(pd.NA, index=df.index, dtype="object")
        if "SEASON_CLUSTER_Rainy" in df.columns:
            s.loc[pd.to_numeric(df["SEASON_CLUSTER_Rainy"], errors="coerce").fillna(0).astype(int).eq(1)] = "Rainy"
        if "SEASON_CLUSTER_Dry" in df.columns:
            s.loc[pd.to_numeric(df["SEASON_CLUSTER_Dry"], errors="coerce").fillna(0).astype(int).eq(1)] = "Dry"
        
        # Anything not explicitly 'Rainy' or 'Dry' will default to 'Unknown'.
        df["SEASON_CLUSTER"] = s.fillna("Unknown") 

    return df

def process_merge_and_save_to_db(
    file1_storage,
    file2_storage,
    table_name: str = "accidents",
    append: bool = False,
) -> tuple[int, int]:
    """
    Reads two uploaded files (main + vehicle), canonicalizes columns, merges on
    (DATE COMMITTED, STATION, BARANGAY, OFFENSE, row_num), normalizes
    DATE/TIME, performs light cleaning, runs apply_additional_preprocessing(),
    and writes to MySQL.

    If append=True and the table already exists, the function:
      1) introspects existing columns
      2) adds any missing columns (ALTER TABLE)
      3) adds missing columns into the incoming DataFrame (as NULLs)
      4) inserts rows in the table's exact column order

    Returns:
        rows_processed, rows_saved
    """
    # ---------------------------
    # Helpers (same)
    # ---------------------------

    def _read_any(fstorage) -> pd.DataFrame:
        filename = (fstorage.filename or "").lower()
        data = fstorage.read()
        bio = io.BytesIO(data)
        if filename.endswith(".xlsx"):
            sheets = pd.read_excel(bio, sheet_name=None)
            return pd.concat(sheets.values(), ignore_index=True)
        elif filename.endswith(".csv"):
            return pd.read_csv(bio)
        raise ValueError("Only .csv or .xlsx are supported")

    def _norm_key(raw: str) -> str:
        s = str(raw).replace("\u00A0", " ").strip()
        s = s.replace("_", " ")
        s = re.sub(r"\s+", " ", s)
        return s.upper()

    def _canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        CANON = {
            "DATE COMMITTED": "DATE COMMITTED",
            "TIME COMMITTED": "TIME COMMITTED",
            "STATION": "STATION",
            "BARANGAY": "BARANGAY",
            "OFFENSE": "OFFENSE",
            "AGE": "AGE",
            "GENDER": "GENDER",
            "ALCOHOL_USED": "ALCOHOL_USED",
            "VEHICLE KIND": "VEHICLE KIND",
            "LATITUDE": "LATITUDE",
            "LONGITUDE": "LONGITUDE",
            "VICTIM COUNT": "VICTIM COUNT",
            "SUSPECT COUNT": "SUSPECT COUNT",
            "SEASON": "SEASON"
        }
        canon_lookup = {_norm_key(k): v for k, v in CANON.items()}
        new_cols = {}
        for c in df.columns:
            token = _norm_key(c)
            new_cols[c] = canon_lookup.get(token, token)
        out = df.rename(columns=new_cols)

        # drop post-rename dupes case-insensitively
        seen, to_drop = set(), []
        for col in list(out.columns):
            key = col.lower()
            if key in seen:
                to_drop.append(col)
            else:
                seen.add(key)
        if to_drop:
            out = out.drop(columns=to_drop)
        return out

    def _to_pytime(x) -> Optional[time]:
        if pd.isna(x):
            return None
        if isinstance(x, time):
            return x
        if isinstance(x, timedelta):
            total = int(x.total_seconds())
            hh = (total // 3600) % 24
            mm = (total % 3600) // 60
            ss = total % 60
            return time(hh, mm, ss)
        td = pd.to_timedelta(x, errors="coerce")
        if not pd.isna(td):
            total = int(td.total_seconds())
            hh = (total // 3600) % 24
            mm = (total % 3600) // 60
            ss = total % 60
            return time(hh, mm, ss)
        ts = pd.to_datetime(x, format="%H:%M:%S", errors="coerce")
        if not pd.isna(ts):
            return ts.time()
        ts2 = pd.to_datetime(x, errors="coerce")
        if not pd.isna(ts2):
            return ts2.time()
        return None

    TYPE_MAP = {
        "DATE_COMMITTED": "DATE",
        "TIME_COMMITTED": "TIME",
        "YEAR": "INT",
        "MONTH": "INT",
        "DAY": "INT",
        "WEEKDAY": "VARCHAR(20)",
        "LATITUDE": "DOUBLE",
        "LONGITUDE": "DOUBLE",
        "AGE": "VARCHAR(16)",
        "VEHICLE KIND": "VARCHAR(128)",
        "STATION": "VARCHAR(128)",
        "BARANGAY": "VARCHAR(128)",
        "OFFENSE": "VARCHAR(255)",
        "GENDER": "VARCHAR(32)",
        "ALCOHOL_USED": "VARCHAR(32)",
        "VICTIM COUNT": "INT",
        "SUSPECT COUNT": "INT",
        "SEASON_CLUSTER": "VARCHAR(32)", # <--- ADDED
    }
    def _sql_type(col: str) -> str:
        return TYPE_MAP.get(col, "TEXT")

    # ---------------------------
    # Read & basic cleaning
    # ---------------------------
    main_df = _read_any(file1_storage)
    veh_df  = _read_any(file2_storage)

    # Drop 'Unnamed' columns
    main_df = main_df.loc[:, ~main_df.columns.astype(str).str.contains(r"^Unnamed", regex=True)]
    veh_df  =  veh_df.loc[:, ~veh_df.columns.astype(str).str.contains(r"^Unnamed", regex=True)]

    main_df = _canonicalize_columns(main_df)
    veh_df  = _canonicalize_columns(veh_df)

    # NA normalization (keep Unknown as missing now; we'll standardize later)
    NA_VALS = ["Unknown", "unknown", "N/A", "NaN", "", " ", "<NA>", "nan"]
    main_df.replace(NA_VALS, pd.NA, inplace=True)  # 
    veh_df.replace(NA_VALS, pd.NA, inplace=True)

    # Local specific fix
    if "BARANGAY" in veh_df.columns:
        veh_df["BARANGAY"] = veh_df["BARANGAY"].replace("SAPALIBUTA", "SAPALIBUTAD")  # 

    # Trim text columns
    for col in ["STATION", "BARANGAY", "OFFENSE", "VEHICLE KIND"]:
        if col in main_df.columns:
            main_df[col] = main_df[col].astype(str).str.strip()
        if col in veh_df.columns:
            veh_df[col] = veh_df[col].astype(str).str.strip()

    # Ensure merge keys exist & types normalized
    for df in (main_df, veh_df):
        if "DATE COMMITTED" not in df.columns:
            df["DATE COMMITTED"] = pd.NaT
        df["DATE COMMITTED"] = pd.to_datetime(df["DATE COMMITTED"], errors="coerce").dt.normalize()
        for k in ["STATION", "BARANGAY", "OFFENSE"]:
            if k not in df.columns:
                df[k] = pd.NA
            df[k] = df[k].astype("string").str.strip()

    main_df = main_df.dropna(how="all")
    veh_df  = veh_df.dropna(how="all")

    # ---------------------------
    # Merge on keys + row_num
    # ---------------------------
    merge_keys = ["DATE COMMITTED", "STATION", "BARANGAY", "OFFENSE"]
    main_df = main_df.sort_values(by=merge_keys).reset_index(drop=True)
    veh_df  =  veh_df.sort_values(by=merge_keys).reset_index(drop=True)

    main_df["row_num"] = main_df.groupby(merge_keys).cumcount()
    veh_df["row_num"]  =  veh_df.groupby(merge_keys).cumcount()

    merged = main_df.merge(
        veh_df,
        on=merge_keys + ["row_num"],
        how="left",
        suffixes=("", "_V"),
    ).drop(columns=["row_num"], errors="ignore")  # 

    # Normalizations post-merge
    if "BARANGAY" in merged.columns:
        merged["BARANGAY"] = merged["BARANGAY"].replace("CAPAY", "CAPAYA")  # 

    if "DATE COMMITTED" in merged.columns:
        merged["DATE COMMITTED"] = pd.to_datetime(merged["DATE COMMITTED"], errors="coerce")
        merged["DATE_COMMITTED"] = merged["DATE COMMITTED"].dt.date
        merged.drop(columns=["DATE COMMITTED"], inplace=True, errors="ignore")  # 

    if "DATE_COMMITTED" in merged.columns:
        dt = pd.to_datetime(merged["DATE_COMMITTED"], errors="coerce")
        merged["YEAR"] = dt.dt.year
        merged["MONTH"] = dt.dt.month
        merged["DAY"] = dt.dt.day
        merged["WEEKDAY"] = dt.dt.day_name()  # 

    if "TIME COMMITTED" in merged.columns:
        merged["TIME_COMMITTED"] = merged["TIME COMMITTED"].apply(_to_pytime)
        merged.drop(columns=["TIME COMMITTED"], inplace=True, errors="ignore")  # 

    if "VEHICLE KIND" in merged.columns:
        merged["VEHICLE KIND"] = merged["VEHICLE KIND"].fillna("Unknown")

    if "AGE" in merged.columns:
        merged["AGE"] = pd.to_numeric(merged["AGE"], errors="coerce")
        merged["AGE"] = merged["AGE"].apply(lambda x: str(int(x)) if pd.notnull(x) else "Unknown")  # 

    # ---------------------------
    # NEW: Strong standardization for GENDER & ALCOHOL_USED
    # This prevents literal "<NA>" / "nan" strings from becoming categories
    # ---------------------------
    def _norm_str(x):
        if x is pd.NA or x is None:
            return None
        s = str(x).strip()
        if s in {"", "nan", "NaN", "<NA>", "None"}:
            return None
        return s

    def _normalize_gender(x):
        s = _norm_str(x)
        if not s:
            return "Unknown"
        low = s.lower()
        if low in {"m", "male"}:
            return "Male"
        if low in {"f", "female"}:
            return "Female"
        return "Unknown"

    def _normalize_alcohol(x):
        s = _norm_str(x)
        if not s:
            return "Unknown"
        low = s.lower()
        if low in {"yes", "y", "1", "true"}:
            return "Yes"
        if low in {"no", "n", "0", "false"}:
            return "No"
        return "Unknown"

    if "GENDER" in merged.columns:
        merged["GENDER"] = merged["GENDER"].apply(_normalize_gender)

    if "ALCOHOL_USED" in merged.columns:
        merged["ALCOHOL_USED"] = merged["ALCOHOL_USED"].apply(_normalize_alcohol)

    # Ensure coordinate columns exist
    for req in ["LATITUDE", "LONGITUDE"]:
        if req not in merged.columns:
            merged[req] = pd.NA

    # Optional: drop rows without coordinates (kept from your code)
    merged = merged.dropna(subset=["LATITUDE", "LONGITUDE"])

    rows_processed = int(len(merged))

    # ---------------------------
    # Extra preprocessing (unchanged)
    # ---------------------------
    merged = apply_additional_preprocessing(merged)  # one-hot happens here; now safe from <NA> dummies 

    # Final sort by datetime if available
    if "DATE_COMMITTED" in merged.columns:
        merged["__DT_SORT"] = pd.to_datetime(
            merged["DATE_COMMITTED"].astype(str) + " " + merged.get("TIME_COMMITTED", "").astype(str),
            errors="coerce",
        )
        merged = merged.sort_values(["__DT_SORT", "DATE_COMMITTED"]).drop(columns="__DT_SORT")

    # ---------------------------
    # Persist to MySQL (same schema-aware create/append)
    # ---------------------------
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        exists = cur.fetchone() is not None

        if append and exists:
            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            existing_cols = [r[0] for r in cur.fetchall()]

            to_add = [c for c in merged.columns if c not in existing_cols]
            for c in to_add:
                cur.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{c}` {_sql_type(c)} NULL")

            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            final_cols = [r[0] for r in cur.fetchall()]
            for c in final_cols:
                if c not in merged.columns:
                    merged[c] = pd.NA
            merged = merged.reindex(columns=final_cols)

        else:
            cols = list(merged.columns)
            # MODIFICATION: Add an auto-incrementing primary key 'id' column on table creation.
            col_decls = "`id` INT AUTO_INCREMENT PRIMARY KEY, " + ", ".join(f"`{c}` {_sql_type(c)}" for c in cols)
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS `{table_name}` ({col_decls}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            final_cols = [r[0] for r in cur.fetchall()]
            merged = merged.reindex(columns=final_cols, fill_value=pd.NA)

        cols = list(merged.columns)
        # We don't insert into 'id', so we filter it out for the INSERT statement
        cols_to_insert = [c for c in cols if c.lower() != 'id']
        placeholders = ", ".join(["%s"] * len(cols_to_insert))
        insert_sql = f"INSERT INTO `{table_name}` ({', '.join(f'`{c}`' for c in cols_to_insert)}) VALUES ({placeholders})"

        # Batch insert logic to prevent timeouts on large files
        chunk_size = 1000  # Insert 1000 rows at a time
        values_chunk = []
        total_rows_saved = 0

        for _, r in merged.iterrows():
            # Create a tuple of values for the columns we are inserting into
            row = tuple(None if pd.isna(r[c]) else r[c] for c in cols_to_insert)
            values_chunk.append(row)

            # When the chunk is full, execute the query and reset the list
            if len(values_chunk) >= chunk_size:
                cur.executemany(insert_sql, values_chunk)
                total_rows_saved += cur.rowcount
                values_chunk = []

        # Insert any remaining rows that didn't make a full chunk
        if values_chunk:
            cur.executemany(insert_sql, values_chunk)
            total_rows_saved += cur.rowcount

        conn.commit()
        
        # After successfully saving all data, create the performance indexes
        print(f"Data saved to '{table_name}'. Now creating database indexes...")
        ensure_indexes(table_name)
        print("Indexes created successfully.")
        
        # Return the correct total from the batching process
        return rows_processed, total_rows_saved
        
        # --- END OF FULL REPLACEMENT ---
    finally:
        try: cur.close()
        except: pass
        try: conn.close()
        except: pass

