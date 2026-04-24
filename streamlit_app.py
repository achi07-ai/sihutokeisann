import streamlit as st
import pandas as pd
from pulp import *
import random

st.set_page_config(page_title="塾シフト管理システム", layout="wide")

st.title("📅 塾シフト自動割り振りアプリ")

# --- 設定セクション ---
with st.sidebar:
    st.header("基本設定")
    num_days = st.number_input("開校日数 (例: 20日分)", min_value=1, value=5)
    slots_per_day = st.number_input("1日の必要コマ数", min_value=1, value=3)
    teachers = st.text_area("講師名（カンマ区切り）", "田中, 佐藤, 鈴木, 高橋").split(",")
    teachers = [t.strip() for t in teachers]

# --- 1. 出勤可能日の入力 ---
st.subheader("1. 出勤可能日の入力")
st.write("各講師の出勤可能日にチェックを入れてください。")

# 入力用のデータフレーム作成
availability_df = pd.DataFrame(False, index=teachers, columns=[f"{i+1}日" for i in range(num_days)])
edited_df = st.data_editor(availability_df, key="availability_editor")

# --- 2. シフト割り振りロジック ---
if st.button("シフトを自動生成する"):
    
    # 最適化問題の定義（出勤数の最大最小差を小さくする）
    prob = LpProblem("Shift_Scheduling", LpMinimize)
    
    # 変数: 各講師が各日に出勤するかどうか (0 or 1)
    x = LpVariable.dicts("shift", (teachers, range(num_days)), cat=LpBinary)
    
    # 各講師の合計出勤コマ数
    total_shifts = {t: lpSum([x[t][d] for d in range(num_days)]) for t in teachers}
    
    # 補助変数: 最大出勤数と最小出勤数（均等化のため）
    max_s = LpVariable("max_shifts", lowBound=0)
    min_s = LpVariable("min_shifts", lowBound=0)
    
    # 目的関数: 最大と最小の差を最小化する
    prob += max_s - min_s
    
    # 制約条件
    for d in range(num_days):
        # 1. 各日の必要コマ数を満たす
        prob += lpSum([x[t][d] for t in teachers]) == slots_per_day
        
        for t in teachers:
            # 2. 出勤可能日以外は割り振らない
            if not edited_df.loc[t, f"{d+1}日"]:
                prob += x[t][d] == 0
                
    for t in teachers:
        # 3. 均等化のための制約
        prob += total_shifts[t] <= max_s
        prob += total_shifts[t] >= min_s

    # 解く
    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] == 'Optimal':
        st.success("最適化されたシフトを生成しました！")
        
        # 結果の表示
        results = []
        for d in range(num_days):
            day_teachers = [t for t in teachers if value(x[t][d]) == 1]
            results.append(", ".join(day_teachers))
        
        result_df = pd.DataFrame({
            "日付": [f"{i+1}日" for i in range(num_days)],
            "担当講師": results
        })
        
        st.subheader("生成されたシフト表")
        st.table(result_df)
        
        # 均等性の確認
        st.subheader("講師ごとの出勤数")
        count_data = {t: sum(value(x[t][d]) for d in range(num_days)) for t in teachers}
        st.bar_chart(pd.Series(count_data))
        
    else:
        st.error("条件に合うシフトが見つかりませんでした。出勤可能日を増やしてください。")
