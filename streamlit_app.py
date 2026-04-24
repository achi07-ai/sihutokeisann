import streamlit as st
import pandas as pd
from pulp import *
import datetime

st.set_page_config(page_title="塾シフト管理V2", layout="wide")

st.title("📅 塾シフト管理システム (カレンダー対応版)")

# --- サイドバー設定 ---
with st.sidebar:
    st.header("1. 基本設定")
    teachers_input = st.text_area("講師名（カンマ区切り）", "田中, 佐藤, 鈴木, 高橋, 伊藤")
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]
    
    slots_per_day = st.number_input("1日の必要講師数", min_value=1, value=2)

# --- 2. 開校日の選択 ---
st.subheader("2. 開校日の選択")
selected_dates = st.date_input(
    "カレンダーから授業がある日を選択してください（複数選択可）",
    value=[],
    help="Ctrl（Cmd）を押しながらクリック、またはドラッグで複数選択できます"
)

if not selected_dates:
    st.info("カレンダーから日付を選択してください。")
    st.stop()

# 日付を昇順にソートして文字列化
dates_str = [d.strftime("%m/%d(%a)") for d in sorted(selected_dates)]

# --- 3. 出勤可能日の入力 ---
st.subheader("3. 各講師の出勤可能チェック")
st.write("選択された開校日に対して、出勤できる日にチェックを入れてください。")

# 入力用データフレームの初期化
if 'availability' not in st.session_state or st.session_state.get('prev_dates') != dates_str:
    init_df = pd.DataFrame(False, index=teachers, columns=dates_str)
    st.session_state.availability = init_df
    st.session_state.prev_dates = dates_str

edited_df = st.data_editor(st.session_state.availability, use_container_width=True)

# --- 4. シフト割り振り実行 ---
if st.button("シフトを自動生成する"):
    num_days = len(dates_str)
    
    # 最適化問題の定義
    prob = LpProblem("Shift_Balancing", LpMinimize)
    
    # 変数: x[講師][日] = 1 (出勤), 0 (休み)
    x = LpVariable.dicts("shift", (teachers, range(num_days)), cat=LpBinary)
    
    # 各講師の合計出勤数
    total_shifts = {t: lpSum([x[t][d] for d in range(num_days)]) for t in teachers}
    
    # 均等化のための補助変数
    max_s = LpVariable("max_shifts", lowBound=0)
    min_s = LpVariable("min_shifts", lowBound=0)
    
    # 目的関数: 最大と最小の差を最小化（これが「最も均等」を作るロジック）
    prob += max_s - min_s
    
    # 制約条件
    for d in range(num_days):
        # 各日の必要人数を満たす
        prob += lpSum([x[t][d] for t in teachers]) == slots_per_day
        
        for t in teachers:
            # 入力された「出勤可能日」以外は割り振らない
            if not edited_df.loc[t, dates_str[d]]:
                prob += x[t][d] == 0
                
    for t in teachers:
        # 均等化のための範囲制約
        prob += total_shifts[t] <= max_s
        prob += total_shifts[t] >= min_s

    # ソルバー実行
    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] == 'Optimal':
        st.success("計算完了！最もバランスの良いシフトを作成しました。")
        
        # 結果表示用データ作成
        result_data = []
        for d in range(num_days):
            day_teachers = [t for t in teachers if value(x[t][d]) == 1]
            result_data.append({"日付": dates_str[d], "担当講師": " / ".join(day_teachers)})
        
        res_df = pd.DataFrame(result_data)
        
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("生成されたシフト表")
            st.dataframe(res_df, use_container_width=True)
        
        with col2:
            st.subheader("講師ごとの出勤回数")
            counts = {t: int(sum(value(x[t][d]) for d in range(num_days))) for t in teachers}
            st.bar_chart(pd.Series(counts))
            for t, c in counts.items():
                st.write(f"{t}: {c}回")
                
    else:
        st.error("条件に合うシフトが見つかりませんでした。出勤可能日のチェックを増やすか、必要人数を調整してください。")
