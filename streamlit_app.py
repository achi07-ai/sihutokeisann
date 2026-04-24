import streamlit as st
import pandas as pd
from pulp import *
import datetime

st.set_page_config(page_title="塾シフト管理V4 (コマ単位)", layout="wide")

st.title("📅 塾シフト管理システム (コマ単位・柔軟対応版)")

# --- サイドバー：講師設定 ---
with st.sidebar:
    st.header("1. 講師設定")
    teachers_input = st.text_area("講師名（カンマ区切り）", "田中, 佐藤, 鈴木, 高橋, 伊藤")
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]

# --- 2. スケジュールの定義 ---
st.subheader("2. 開校スケジュールとコマ数の設定")

col_date1, col_date2 = st.columns(2)
with col_date1:
    start_date = st.date_input("開始日", datetime.date.today())
with col_date2:
    end_date = st.date_input("終了日", datetime.date.today() + datetime.timedelta(days=30))

if start_date > end_date:
    st.error("終了日は開始日より後の日付にしてください。")
    st.stop()

# 自動生成ロジック
if st.button("期間内の基本コマを自動生成"):
    date_range = pd.date_range(start=start_date, end=end_date)
    default_slots = []
    
    for d in date_range:
        day_name = d.strftime("%a")
        # 水(Wed), 木(Thu), 金(Fri) は2コマ、土(Sat) は3コマ
        num_slots = 0
        if day_name in ["Wed", "Thu", "Fri"]:
            num_slots = 2
        elif day_name == "Sat":
            num_slots = 3
        
        for i in range(num_slots):
            default_slots.append({
                "日付": d.strftime("%Y-%m-%d"),
                "曜日": day_name,
                "コマ名": f"第{i+1}コマ",
                "必要人数": 1
            })
    
    st.session_state.slot_definition = pd.DataFrame(default_slots)

# コマの編集・手動追加
if 'slot_definition' in st.session_state:
    st.write("生成されたコマのリストです。行の追加や削除、必要人数の変更が可能です。")
    edited_slots = st.data_editor(
        st.session_state.slot_definition, 
        num_rows="dynamic",
        use_container_width=True,
        key="slot_editor"
    )
    
    # スロットの一意識別子を作成
    unique_slots = []
    for _, row in edited_slots.iterrows():
        unique_slots.append(f"{row['日付']}({row['曜日']})_{row['コマ名']}")
    edited_slots['slot_id'] = unique_slots
else:
    st.info("上のボタンを押してコマを生成するか、手動で設定を開始してください。")
    st.stop()

# --- 3. 出勤可能入力 ---
st.subheader("3. 講師の出勤可能チェック")
st.write("各コマに出勤できる講師を選択してください（行：コマ、列：講師）。")

# 入力用データフレーム（縦：コマ、横：講師）
# コマ数が多いため、縦にコマを並べる方が入力しやすくなります
if 'availability_v4' not in st.session_state or st.session_state.get('prev_slots') != unique_slots:
    avail_df = pd.DataFrame(False, index=unique_slots, columns=teachers)
    st.session_state.availability_v4 = avail_df
    st.session_state.prev_slots = unique_slots

# データエディタで入力
check_df = st.data_editor(st.session_state.availability_v4, use_container_width=True)

# --- 4. シフト割り振り実行 ---
if st.button("シフトを自動生成する"):
    num_slots = len(unique_slots)
    
    prob = LpProblem("Slot_Based_Balancing", LpMinimize)
    
    # 変数: x[講師][コマID]
    x = LpVariable.dicts("slot_assign", (teachers, unique_slots), cat=LpBinary)
    
    # 各講師の合計コマ数
    total_assign = {t: lpSum([x[t][s] for s in unique_slots]) for t in teachers}
    
    # 均等化用
    max_s = LpVariable("max_s", lowBound=0)
    min_s = LpVariable("min_s", lowBound=0)
    prob += max_s - min_s
    
    # 制約
    for idx, s_id in enumerate(unique_slots):
        # 各コマの必要人数（slot_editorから取得）
        req_people = edited_slots.iloc[idx]['必要人数']
        prob += lpSum([x[t][s_id] for t in teachers]) == req_people
        
        for t in teachers:
            # 出勤不可のコマには割り当てない
            if not check_df.loc[s_id, t]:
                prob += x[t][s_id] == 0
                
    for t in teachers:
        prob += total_assign[t] <= max_s
        prob += total_assign[t] >= min_s

    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] == 'Optimal':
        st.success("最適化が完了しました。")
        
        # 結果表示
        res_list = []
        for s_id in unique_slots:
            assigned = [t for t in teachers if value(x[t][s_id]) == 1]
            res_list.append({"コマ": s_id, "担当": ", ".join(assigned)})
        
        res_df = pd.DataFrame(res_list)
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader("確定シフト表")
            st.table(res_df)
        with c2:
            st.subheader("講師別コマ数合計")
            final_counts = {t: int(sum(value(x[t][s]) for s in unique_slots)) for t in teachers}
            st.bar_chart(pd.Series(final_counts))
            for t, v in final_counts.items():
                st.write(f"**{t}**: {v}コマ")
    else:
        st.error("解が見つかりませんでした。講師の出勤可能日を増やすか、必要人数を調整してください。")
