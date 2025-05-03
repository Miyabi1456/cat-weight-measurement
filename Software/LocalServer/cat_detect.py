import numpy as np
from datetime import datetime


class CatLoadCell:
    """
    猫トイレのロードセルから送信されてくる値を格納し、
    ・バッファに保存
    ・指定区間で静止状態を判定し、静止状態であれば風袋引きのためのオフセット値を更新する
    ・重量がしきい値を超える、下回るイベントを記録
    ・重量増加イベントがあったとき、
    　・猫がトイレの場合、継続時間が5分未満に荷重が下がるイベントを起こす
    　・猫砂補充の場合、継続時間が5分以上経っても荷重が下がらない
    ・イベントの前後のバッファも含めて返す。後でデータが溜まってきたらアルゴリズムを再考するため
    ・重心計算
    
    tare_threshold : float 指定区間の標準偏差がこの値を下回れば静止しているとみなす
    trigger_threshold : float 重量がこの値を超えれば猫が載っていると判断
    

    """
    def __init__(self, buffer_length=3600): # 1時間×3600秒/h / 1Hz
        
        # タイムスタンプ
        self.prev_unix_timestamp = None
        self.unix_timestamp_buffer = np.zeros(buffer_length) # UNIX時間で保持 [-1]側が最新
        # ロードセル
        self.loadcell_buffer = np.zeros((buffer_length, 4))  # 4つのロードセル
        self.tare_offset = np.zeros(4,)
        self.tare_offset_buffer = np.zeros((buffer_length, 4))  # 風袋引きのためのオフセット値
        
        self.tare_threshold = 3.0 # 単位:g 指定区間の荷重のばらつき（標準偏差）がこの値以下であれば静止とみなす
        self.success_tare = False # 風袋引き完了
        self.ave_num = 3 # 重量変化をみるときに平滑化する点数
        self.last_tare_time = 0.0 # 最後に風袋引きしたUNIX時間
        self.max_last_tare_time = 60.0 * 10.0 # この時間に一度は風袋引きする
        
        # イベント関連
        self.trigger_loadup_threshold = 1000.0 # 単位:g 重量がこの値を超えたら猫が乗ったか猫砂補充と判断
        self.trigger_loaddown_threshold = 500.0 # 単位:g 重量がこの値を下回ったら猫が降りたと判断
        self.start_load = np.zeros(4) # 単位:g 猫が乗る前の荷重
        self.end_load = np.zeros(4) # 単位:g 猫が乗ったあとの荷重
        
        self.event_start_unix_timestamp = 0.0 # イベントスタートUNIX時刻
        self.event_end_unix_timestamp = 0.0 # イベントエンドUNIX時刻
        self.event_active_time = 0.0 # 単位:sec イベント継続時間
        self.max_event_length = 5*60 # 単位:sec 猫がトイレに乗っていると考えられる最大時間 これ以上イベントが継続したら、猫砂補充と考える
        self.settling_time = 30.0 # 単位:sec イベント終了からの静定時間
        self.event_active = False # イベントフラグ
        self.settling_active = False # イベント終了後の静定フラグ
        
        self.sent_ranges = [0.0,0.0]  # (start_time, end_time) のリスト
        
        self.pre_buffer_time = 30.0 # 単位:sec イベント開始フラグの何秒前までcurrent_event_buffに追加するか
        self.current_event_buff = {"timestamp":[], "loadcell_values":[],"tare_offset":[], "event_start_index":0, "event_end_index":0, "diff_load":0.0, "cat_weight":0.0, "toilet_time":0.0} # イベントフラグがONになっている間のデータ

        # ロードセルの幾何配置 (単位 mm) センサー番号と実際の配置で調整
        self.sensor_positions = {
            1: (0, 0),     # 左上
            0: (600, 0),   # 右上
            2: (0, 400),    # 左下
            3: (600, 400),  # 右下
        }
        
        self.current_unix = 1746098044.512 # 今のUNIX時刻


    def add_sample_and_check_event(self, timestamp, loadcell_values):
        """
        1サンプル追加と重量変化の監視
        timestamp : str %Y/%m/%d %H:%M:%S.%f
        loadcell_values : numpy array (4,)
        
        event_buff : None or list[()]
        """
        #self.current_unix += 1.0 # デバッグ時用
        self.current_unix = self.__str_to_unix(timestamp)
        
        self.unix_timestamp_buffer[:-1] = self.unix_timestamp_buffer[1:]
        self.unix_timestamp_buffer[-1] = self.current_unix

        self.loadcell_buffer[:-1] = self.loadcell_buffer[1:]
        self.loadcell_buffer[-1] = loadcell_values
        
        self.tare_offset_buffer[:-1] = self.tare_offset_buffer[1:]
        self.tare_offset_buffer[-1] = self.tare_offset
        
        event_buff = self.__check_for_event()
        return event_buff

    def __str_to_unix(self, t_str: str) -> float:
        """2025/04/28 22:08:25.730のようなフォーマットからUNIX時間へ変換"""
        fmt = "%Y/%m/%d %H:%M:%S.%f"
        dt = datetime.strptime(t_str, fmt)
        unix_time = dt.timestamp()
        return unix_time
    
    def __unix_to_str(self, unix_time: float) -> str:
        """UNIX時間（float）を 'YYYY/MM/DD HH:MM:SS.sss' フォーマットに変換"""
        dt = datetime.fromtimestamp(unix_time)
        t_str = dt.strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]  # 小数点以下3桁にする
        return t_str
    

    def __find_timestamp_indices_in_range(self, start_time, end_time):
        """
        タイムスタンプ配列から、指定時間の範囲を切り出す。
        最新の時刻を基準に指定
        """
        latest_time = self.unix_timestamp_buffer[-1]
        if latest_time == 0.0: # バッファがまだ初期値のままのとき
            return None, None
        
        t1 = latest_time + start_time
        t2 = latest_time + end_time

        # 指定範囲のインデックスリスト
        indices = np.where((t1 <= self.unix_timestamp_buffer) & (self.unix_timestamp_buffer <= t2))[0]

        if len(indices) == 0: # 指定範囲のタイムスタンプがないとき
            return None, None

        start_idx = indices[0]
        end_idx = indices[-1]

        return start_idx, end_idx + 1 # Numpy array[start_idx:end_idx]で指定範囲が得られるように+1


    def __perform_tare(self, start_time=-15.0, end_time=-10.0):
        """指定区間の標準偏差を確認し、静止していたらオフセット設定"""
        start_idx, end_idx = self.__find_timestamp_indices_in_range(start_time, end_time)
        
        if start_idx is None or end_idx is None: # 指定範囲のデータがないとき
            return False
        
        samples_array = self.loadcell_buffer[start_idx:end_idx]
        if np.all(np.std(samples_array, axis=0) < self.tare_threshold): # 全部静止していたら更新
            self.tare_offset = np.mean(samples_array, axis=0)
            self.last_tare_time = self.unix_timestamp_buffer[-1] # 風袋引きした時刻を記録しておき、self.max_length_tare_timeを超えて風袋引きされてなかったらする
            return True
        return False # 更新以外はFalse


    def get_corrected_value(self):
        """最新データをオフセット補正して取得"""
        str_timestamp = self.__unix_to_str(self.unix_timestamp_buffer[-1])
        corrected_loadcell_values = self.loadcell_buffer[-1] - self.tare_offset
        return str_timestamp, corrected_loadcell_values


    def calculate_centroid(self, values):
        """ロードセル値から重心位置を計算"""
        total_weight = np.sum(values)
        if total_weight == 0.0: # 合計重量が0.0のとき、重心は幾何中心にあるものとする
            values = [1,1,1,1]
            total_weight = 4

        x = np.sum(values[i] * self.sensor_positions[i][0] for i in range(4)) / total_weight
        y = np.sum(values[i] * self.sensor_positions[i][1] for i in range(4)) / total_weight
        return x, y


    def __check_for_event(self):
        """変化検出＋イベントデータ記録"""
        return_event_buff = None # 猫が乗ったイベントがあったとき、タイムスタンプやロードセルの値を入れた辞書を返す　それ以外はNone
        # 現在のロードセル値
        current_load = np.sum(np.mean(self.loadcell_buffer[-self.ave_num:], axis=0)) # ロードセル生値
        corrected_current_load = np.sum(np.mean(self.loadcell_buffer[-self.ave_num:] - self.tare_offset, axis=0)) # 風袋引き後のロードセル値
        current_loadcell_values = self.loadcell_buffer[-1]
        unix_timestamp = self.unix_timestamp_buffer[-1]
        
        # 静定が失敗した場合はもう1ループ
        if not self.success_tare:
            self.success_tare = self.__perform_tare(start_time=-15.0,end_time=-5.0) # 風袋引き
            return None
        
        # 前回の風袋引きからself.max_last_tare_time経っていたら実行
        if unix_timestamp - self.last_tare_time > self.max_last_tare_time:
            self.success_tare = self.__perform_tare(start_time=-15.0,end_time=-5.0) # 風袋引き



        # イベント未発生時の処理
        if not self.event_active:
    
            if self.settling_active: # 静定中
                self.__append_event_buff(unix_timestamp, current_loadcell_values, self.tare_offset) # イベントバッファにイベント中のタイムスタンプ、風袋引き後のロードセル値、風袋引きオフセット値を追加
                # 静定完了
                if unix_timestamp - self.event_end_unix_timestamp > self.settling_time:
                    self.settling_active = False
                    self.end_load = np.mean(self.loadcell_buffer[-5:], axis=0) # 5サンプル前から最新までの5点平均とする
                    return_event_buff = self.__handle_event() # イベント種別判定
                    return return_event_buff

            # イベント発生
            if corrected_current_load > self.trigger_loadup_threshold: # イベント発生 重量がしきい値を超えている状態
                self.settling_active = False # 静定中にイベント発生してしまったら、そのイベントは諦める
                # バッファのクリア
                self.__reset_event_buff()
                self.event_active_time = 0.0

                self.start_load = np.mean(self.loadcell_buffer[-15:-10], axis=0) # 15サンプル前から5点平均とする
                self.event_active = True # イベント開始
                self.event_start_unix_timestamp = unix_timestamp


        # イベント発生中の処理
        if self.event_active:
            if corrected_current_load < self.trigger_loaddown_threshold: # イベント終了 イベント発生中かつ重量がしきい値を下回るとき
                self.event_active = False
                self.settling_active = True # 静定開始
                self.event_active_time = 0.0
                self.event_end_unix_timestamp = unix_timestamp
                self.__append_event_buff(unix_timestamp, current_loadcell_values, self.tare_offset)
            else: # イベント継続
                self.__append_event_buff(unix_timestamp, current_loadcell_values, self.tare_offset)
                self.event_active_time = unix_timestamp - self.event_start_unix_timestamp #イベント継続時間を計算
                
            # イベント終了 継続時間が最大値を超えたとき 猫砂補充など
            if self.event_active_time > self.max_event_length:
                self.success_tare = self.__perform_tare(start_time=-10.0,end_time=-0.0) # 風袋引き
                self.event_active = False
                self.settling_active = False
                self.event_active_time = 0.0
                self.__reset_event_buff()

        return return_event_buff

    def __handle_event(self):
        """イベント完了後、未送信なら返す"""
        if len(self.current_event_buff["timestamp"]) == 0: # イベントバッファが空
            return None

        start_time = self.__str_to_unix(self.current_event_buff["timestamp"][0])
        end_time = self.__str_to_unix(self.current_event_buff["timestamp"][-1])

        sent_s, send_e = self.sent_ranges
        if sent_s <= start_time and end_time <= send_e:
            # すでに送信済み
            self.__reset_event_buff()
            return None

        # 新しい未送信イベント
        self.sent_ranges = [start_time, end_time]
        self.__post_process() # イベント開始前の一定期間をバッファに追加する。猫が乗っている最中のインデックスを記録する。乗る前と乗った後の重量差を記録する。乗っている最中の重量を記録する。
        event_copy = self.current_event_buff.copy()
        self.__reset_event_buff()
        return event_copy
    
    def __reset_event_buff(self):
        self.current_event_buff["timestamp"] = []
        self.current_event_buff["loadcell_values"] = []
        self.current_event_buff["tare_offset"] = []
        self.current_event_buff["event_start_index"] = 0
        self.current_event_buff["event_end_index"] = 0
        
        self.current_event_buff["diff_load"] = 0.0
        self.current_event_buff["cat_weight"] = 0.0
        self.current_event_buff["toilet_time"] = 0.0
        
        
    def __append_event_buff(self, unix_timestamp, loadcell_values, tare_offset):
        self.current_event_buff["timestamp"].append(self.__unix_to_str(unix_timestamp))
        self.current_event_buff["loadcell_values"].append(np.copy(loadcell_values))
        self.current_event_buff["tare_offset"].append(np.copy(tare_offset))


    def __post_process(self):
        """呼び出し時点からself.pre_buffer_time分だけ前の値をバッファに格納する 最後に一回だけ呼び出す"""
        
        # イベント開始-pre_buffer_timeからイベント開始までの期間のデータを格納する
        mask = np.where((self.event_start_unix_timestamp - self.pre_buffer_time < self.unix_timestamp_buffer) & (self.unix_timestamp_buffer < self.event_start_unix_timestamp))
        prev_unix_timestamps = self.unix_timestamp_buffer[mask]
        prev_loadcellValues = self.loadcell_buffer[mask]
        prev_tareOffset_buffer = self.tare_offset_buffer[mask]
        prev_str_timestamps = list(map(self.__unix_to_str, prev_unix_timestamps)) # UNIX→str

        # イベント開始前の一定期間のデータを追加する
        self.current_event_buff["timestamp"] = prev_str_timestamps + self.current_event_buff["timestamp"]
        self.current_event_buff["loadcell_values"] = list(prev_loadcellValues) + self.current_event_buff["loadcell_values"]
        self.current_event_buff["tare_offset"] = list(prev_tareOffset_buffer) + self.current_event_buff["tare_offset"]
        
        # 猫が乗っている最中のインデックスを記録する
        current_event_str_timestamps = np.array(list(map(self.__str_to_unix, self.current_event_buff["timestamp"])))
        in_event_idx = np.where((self.event_start_unix_timestamp <= current_event_str_timestamps)&(current_event_str_timestamps<=self.event_end_unix_timestamp))
        event_start_idx = np.min(in_event_idx)
        event_end_idx = np.max(in_event_idx) - self.ave_num
        self.current_event_buff["event_start_index"] = event_start_idx
        self.current_event_buff["event_end_index"] = event_end_idx
        
        # 猫がトイレしてる時間を記録する
        self.current_event_buff["toilet_time"] = self.event_end_unix_timestamp - self.event_start_unix_timestamp
        
        # 猫が乗る前と乗った後の荷重の差を記録する
        self.current_event_buff["diff_load"] = np.sum( np.mean(self.current_event_buff["loadcell_values"][-2:-1],axis=0) - np.mean(self.current_event_buff["loadcell_values"][0:2],axis=0) )
        
        # 猫の体重を記録する
        corrected_load = np.array(self.current_event_buff["loadcell_values"][event_start_idx:event_end_idx]) - np.array(self.current_event_buff["tare_offset"][event_start_idx:event_end_idx])
        self.current_event_buff["cat_weight"] = np.sum(np.mean(corrected_load,axis=0))

if __name__ == "__main__":
    pass