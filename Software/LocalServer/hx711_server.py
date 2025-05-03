from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np
import h5py

from cat_detect import CatLoadCell

app = Flask(__name__)
catLoadCell = CatLoadCell()

def write_to_hdf5(timestamp, sensors):
    """
    センサー生値を記録する
    """
    # 1行分のデータを作成
    new_data = {
        "timestamp": [timestamp],
        "sensor1": [sensors[0]["value"]],
        "sensor2": [sensors[1]["value"]],
        "sensor3": [sensors[2]["value"]],
        "sensor4": [sensors[3]["value"]],
    }

    new_df = pd.DataFrame(new_data)

    hdf5_file = "sensor_data.h5"

    new_df.to_hdf(hdf5_file, key="sensor_data", mode="a", format="table", append=True)


def write_to_hdf5_result_h5py(result_dict, hdf5_file="result_data.h5"):
    # グループ名を "2025-04-29_13_41_11_000" 形式に変換
    timestamp0 = result_dict["timestamp"][0]
    group_name = timestamp0.replace("/", "-").replace(" ", "_").replace(":", "_").replace(".", "_")

    with h5py.File(hdf5_file, "a") as f:
        if group_name in f:
            print(f"Group {group_name} already exists. Overwriting.")

        grp = f.require_group(group_name)

        # 可変長文字列型
        str_dtype = h5py.string_dtype(encoding='utf-8')
        grp.create_dataset("timestamp", data=result_dict["timestamp"], dtype=str_dtype)

        grp.create_dataset("loadcell_values", data=np.array(result_dict["loadcell_values"]))
        grp.create_dataset("tare_offset", data=np.array(result_dict["tare_offset"]))

        # スカラー値を属性として保存
        grp.attrs["event_start_index"] = result_dict["event_start_index"]
        grp.attrs["event_end_index"] = result_dict["event_end_index"]
        grp.attrs["diff_load"] = result_dict["diff_load"]
        grp.attrs["cat_weight"] = result_dict["cat_weight"]


@app.route("/post_data", methods=["POST"])
def post_data():
    try:
        # リクエストからJSONデータを取得
        json_data = request.get_json()
        print(json_data)
        timestamp = json_data["timestamp"]
        sensors = json_data["sensors"]

        datetime_obj = datetime.fromisoformat(timestamp)
        datetime_str = datetime_obj.strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]

        # データベースにデータを書き込む
        write_to_hdf5(datetime_str, sensors) # センサー生値の記録

        loadcell_values = np.array([sensors[0]["value"],sensors[1]["value"],sensors[2]["value"],sensors[3]["value"]])
        event_buff = catLoadCell.add_sample_and_check_event(datetime_str, loadcell_values)
        if event_buff is not None:
            write_to_hdf5_result_h5py(event_buff)


        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == "__main__":
    app.run(host="192.168.2.204", port=5000, debug=True)