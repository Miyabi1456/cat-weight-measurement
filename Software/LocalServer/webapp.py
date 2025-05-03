from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import sqlite3
import pandas as pd
import h5py
from datetime import datetime, timedelta
import math

app = FastAPI(debug=True)

templates = Jinja2Templates(directory="templates")

def safe_float(value):
    return 0.0 if isinstance(value, float) and math.isnan(value) else float(value)

# --- 時系列データJSONエンドポイント ---
@app.get("/api/graph_data", response_class=JSONResponse)
async def graph_data_api():
    df = pd.read_hdf("sensor_data.h5", key="sensor_data",start=-100)

    # タイムスタンプをDatetime型に変換
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # データを返却
    return df.to_dict(orient="records")

# --- 解析結果JSONエンドポイント ---
@app.get("/api/event_data", response_class=JSONResponse)
async def get_event_data(start_idx: int = 0, end_idx: int = None):
    """
    最新順で start_idx ～ end_idx の範囲のイベントを読み出す。
    例: start_idx=0, end_idx=5 → 最新5件
    """
    hdf5_file = "result_data.h5"

    with h5py.File(hdf5_file, "r") as f:
        group_names = sorted(f.keys(), reverse=False)

        if end_idx is None:
            end_idx = len(group_names)

        selected_groups = group_names[start_idx:end_idx]

        results = []
        for group_name in selected_groups:
            grp = f[group_name]

            result = {
                "group_name": group_name,
                "timestamp": [str(t.decode()) if isinstance(t, bytes) else str(t) for t in grp["timestamp"][()]],
                "loadcell_values": grp["loadcell_values"][()].tolist(),
                "tare_offset": grp["tare_offset"][()].tolist(),
                "event_start_index": int(grp.attrs["event_start_index"]),
                "event_end_index": int(grp.attrs["event_end_index"]),
                "diff_load": safe_float(grp.attrs["diff_load"]),
                "cat_weight": safe_float(grp.attrs["cat_weight"])
            }
            results.append(result)

        return results


# --- 重心位置JSONエンドポイント ---
@app.get("/api/centroid_data", response_class=JSONResponse)
async def centroid_data_api():
    df = pd.read_hdf("sensor_data.h5", key="sensor_data")

    # 重心計算用定数: センサーの座標配置 (単位: cm)
    coordinates = {
        "sensor1": {"x": 0, "y": 0},  # 左上
        "sensor2": {"x": 100, "y": 0},  # 右上
        "sensor3": {"x": 0, "y": 50},  # 左下
        "sensor4": {"x": 100, "y": 50},  # 右下
    }

    centroid_data = []  # 重心位置を保存するリスト

    row = df.iloc[-1]

    total_weight = row["sensor1"] + row["sensor2"] + row["sensor3"] + row["sensor4"]

    x_center = (
        row["sensor1"] * coordinates["sensor1"]["x"]
        + row["sensor2"] * coordinates["sensor2"]["x"]
        + row["sensor3"] * coordinates["sensor3"]["x"]
        + row["sensor4"] * coordinates["sensor4"]["x"]
    ) / total_weight

    y_center = (
        row["sensor1"] * coordinates["sensor1"]["y"]
        + row["sensor2"] * coordinates["sensor2"]["y"]
        + row["sensor3"] * coordinates["sensor3"]["y"]
        + row["sensor4"] * coordinates["sensor4"]["y"]
    ) / total_weight

    centroid_data.append({
        "timestamp": row["timestamp"],
        "x_center": x_center,
        "y_center": y_center
    })

    return centroid_data





############################### ページ ######################################################

# --- 解析結果ページ ---
@app.get("/result", response_class=HTMLResponse)
async def result_page(request: Request):
    return templates.TemplateResponse("result.html", {"request": request})

# --- 時系列グラフページ ---
@app.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    return templates.TemplateResponse("graph.html", {"request": request})

# --- ホームページ ---
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webapp:app", host="0.0.0.0", port=8001, reload=True)