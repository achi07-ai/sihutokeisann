import streamlit as st
import pandas as pd
from pulp import *
import datetime

st.set_page_config(page_title="塾シフト管理V3", layout="wide")

st.title("📅 塾シフト管理システム (エラー修正版)")

# --- サイドバー設定 ---
with st.sidebar:
    st.header("1. 基本設定")
    teachers_input = st.text_area("講師名（カンマ区切り）", "田中, 佐藤, 鈴木, 高橋, 伊藤")
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]
    
    slots_per_day = st.number_input("1日の必要講師数", min_value=1, value=2)

# --- 2. 開校日の選択 ---
st.subheader("2. 期間と開校日の選択")
st.write("まずカレンダーでシフトの「期間」を選び、その後で実際の「開校日」を絞り込みます。")

# ① カレンダーで期間を選択
date_range = st.date_input(
    "① シフトを作成する期間（開始日と終了日）を選択してください",
    value=[]
)

# 2つの日付（開始と終了）が選ばれるまで待機
if len(date_range) != 2:
    st.info("👆 カレンダー上で日付を2回クリックして、期間（開始〜終了）を指定してください。")
    st.stop()

start_date, end_date = date_range

# 開始日から終了日までの全ての日付リストを作成
all_dates = pd.date_range(start=start_date, end=end_date)
all_dates_str = [d.strftime("%m/%d(%a)") for d in all_dates]

# ② その中から開校日を選ぶ（最初は全て選択された状態）
dates_str = st.multiselect(
    "② 上記の期間内で、実際に授業がある（開校する）日を残してください",
    options=all_dates_str,
    default=all_dates_str
)

if not dates_str:
    st.info("開校日を1日以上選択してください。")
    st.stop()

# --- 3. 出勤可能日の入力 ---
st.subheader("3. 各講師の出勤可能チェック")
st.write("選択された開校日に対して、出勤できる日にチェックを入れてください。")

# 入力用データフレームの初期化（開校日が変更されたらリセット）
if 'availability' not in st.session_state or st.session_state.get('prev_dates') != dates_str:
    init_df = pd.DataFrame(False, index=teachers, columns=dates_str)
    st.session_state.availability = init_df
    st.session_state.prev_dates = dates_str

edited_df = st.data_editor(st.session_state.availability, use_container_width=True)

# --- 4. シフト割り振り実行 ---
if st.button("シフトを自動生成する"):
    num_days = len(dates_str)
    
    prob = LpProblem("Shift_Balancing", LpMinimize)
    x = LpVariable.dicts("shift", (teachers, range(num_days)), cat=LpBinary)
    total_shifts = {t: lpSum([x[t][d] for d in range(num_days)]) for t in teachers}
    
    max_s = LpVariable("max_shifts", lowBound=0)
    min_s = LpVariable("min_shifts", lowBound=0)
    
    prob += max_s - min_s
    
    for d in range(num_days):
        prob += lpSum([x[t][d] for t in teachers]) == slots_per_day
        for t in teachers:
            if not edited_df.loc[t, dates_str[d]]:
                prob += x[t][d] == 0
                
    for t in teachers:
        prob += total_shifts[t] <= max_s
        prob += total_shifts[t] >= min_s

    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] == 'Optimal':
        st.success("計算完了！最もバランスの良いシフトを作成しました。")
        
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
