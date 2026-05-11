import streamlit as st
import pandas as pd
from pulp import *
import datetime
import altair as alt
from supabase import create_client, Client

# --- Supabase初期化 ---
url: str = st.secrets["URL"]
key: str = st.secrets["KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="塾シフト管理 + Supabase", layout="wide")

# --- データ操作用関数 ---
def load_data():
    ins_res = supabase.table("instructors").select("name").execute()
    teachers = [row['name'] for row in ins_res.data]
    
    slot_res = supabase.table("slots").select("*").order("date").execute()
    slots_df = pd.DataFrame(slot_res.data)
    
    avail_res = supabase.table("availability").select("*").execute()
    
    return teachers, slots_df, avail_res.data

def save_to_supabase(teachers, slots_df, check_df):
    try:
        # 1. 講師リストの更新
        for t in teachers:
            supabase.table("instructors").upsert({"name": t}, on_conflict="name").execute()
        
        # 2. スロット定義の保存
        for _, row in slots_df.iterrows():
            supabase.table("slots").upsert({
                "slot_id": row['slot_id'],
                "date": str(row['日付']), 
                "day": row['曜日'],
                "slot_name": row['コマ名'],
                "req_people": int(row['必要人数'])
            }, on_conflict="slot_id").execute()
        
        # 3. 出勤可能状況の保存
        for slot_id, row in check_df.iterrows():
            for t in teachers:
                supabase.table("availability").upsert({
                    "instructor_name": t,
                    "slot_id": slot_id,
                    "is_available": bool(row[t])
                }, on_conflict="instructor_name,slot_id").execute()
        
        # セッションをクリアして強制的にリロードさせる
        for key in ["slot_definition", "availability_df", "prev_slots"]:
            if key in st.session_state:
                del st.session_state[key]
        
        st.success("✅ データをSupabaseに保存しました！画面を更新します...")
        st.rerun() # 画面を再起動

    except Exception as e:
        st.error(f"保存中にエラーが発生しました: {e}")

# --- メイン UI ---
st.title("📅 塾シフト管理 (完全版)")

# 最新データのロード
loaded_teachers, loaded_slots, loaded_avail = load_data()

with st.sidebar:
    st.header("1. 講師設定")
    default_t = ", ".join(loaded_teachers) if loaded_teachers else "田中, 佐藤, 鈴木, 高橋, 伊藤"
    teachers_input = st.text_area("講師名（カンマ区切り）", default_t)
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]

# --- 2. コマの設定 ---
st.subheader("2. コマの設定")

# カレンダーに key を設定し、リロードされても日付を記憶させる！
col_date1, col_date2 = st.columns(2)
with col_date1:
    start_date = st.date_input("開始日", value=datetime.date.today(), key="start_date")
    req_weekday = st.number_input("平日の必要人数", min_value=1, value=2)
with col_date2:
    end_date = st.date_input("終了日", value=datetime.date.today() + datetime.timedelta(days=30), key="end_date")
    req_sat = st.number_input("土曜の必要人数", min_value=1, value=3)

# 🌟 DBから読み込んだ全データから、カレンダーで選んだ期間だけを絞り込む
if not loaded_slots.empty:
    loaded_slots['date'] = pd.to_datetime(loaded_slots['date']).dt.date
    filtered_slots = loaded_slots[(loaded_slots['date'] >= start_date) & (loaded_slots['date'] <= end_date)]
else:
    filtered_slots = pd.DataFrame()

# 初回ロード時や保存直後に、絞り込んだデータを表にセットする
if 'slot_definition' not in st.session_state:
    if not filtered_slots.empty:
        st.session_state.slot_definition = filtered_slots.rename(columns={
            "date": "日付", "day": "曜日", "slot_name": "コマ名", "req_people": "必要人数"
        }).drop(columns=["id", "slot_id"], errors="ignore") # DB特有のidなどは隠して綺麗にする

# 自動生成ボタン
if st.button("期間内の基本コマを自動生成（※現在の表は上書きされます）"):
    date_range = pd.date_range(start=start_date, end=end_date)
    default_slots = []
    for d in date_range:
        day_name = d.strftime("%a")
        num_slots = 0
        current_req = 1
        if day_name in ["Wed", "Thu", "Fri"]:
            num_slots = 2
            current_req = req_weekday
        elif day_name == "Sat":
            num_slots = 3
            current_req = req_sat
            
        for i in range(num_slots):
            default_slots.append({
                "日付": d.strftime("%Y-%m-%d"),
                "曜日": day_name,
                "コマ名": f"第{i+1}コマ",
                "必要人数": current_req
            })
    st.session_state.slot_definition = pd.DataFrame(default_slots)

if 'slot_definition' in st.session_state:
    edited_slots = st.data_editor(st.session_state.slot_definition, num_rows="dynamic", key="slot_editor")
    unique_slots = [f"{r['日付']}({r['曜日']})_{r['コマ名']}" for _, r in edited_slots.iterrows()]
    edited_slots['slot_id'] = unique_slots
else:
    st.info("上のボタンを押してコマを生成するか、手動で設定を開始してください。")
    st.stop()

# --- 3. 出勤可能チェック ---
st.subheader("3. 出勤可能チェック")

if 'availability_df' not in st.session_state or st.session_state.get('prev_slots') != unique_slots:
    df = pd.DataFrame(False, index=unique_slots, columns=teachers)
    for item in loaded_avail:
        if item['slot_id'] in df.index and item['instructor_name'] in df.columns:
            df.at[item['slot_id'], item['instructor_name']] = item['is_available']
    st.session_state.availability_df = df
    st.session_state.prev_slots = unique_slots

check_df = st.data_editor(st.session_state.availability_df, use_container_width=True)

# 保存ボタン
if st.button("現在の入力内容をデータベースに保存する"):
    save_to_supabase(teachers, edited_slots, check_df)

# （この下には `# --- 4. シフト割り振り実行` が続きます）
# --- 4. シフト割り振り実行（最適化ロジック） ---
st.subheader("4. シフト自動割り振り")
if st.button("シフトを自動生成する"):
    num_slots = len(unique_slots)
    
    prob = LpProblem("Slot_Based_Balancing", LpMinimize)
    x = LpVariable.dicts("slot_assign", (teachers, unique_slots), cat=LpBinary)
    shortage = LpVariable.dicts("shortage", unique_slots, lowBound=0, cat=LpInteger)
    total_assign = {t: lpSum([x[t][s] for s in unique_slots]) for t in teachers}
    
    max_s = LpVariable("max_s", lowBound=0)
    min_s = LpVariable("min_s", lowBound=0)
    
    # 目的関数: 均等化 + 不足ペナルティ
    prob += (max_s - min_s) + 10000 * lpSum([shortage[s] for s in unique_slots])
    
    for idx, s_id in enumerate(unique_slots):
        req_people = int(edited_slots.iloc[idx]['必要人数'])
        prob += lpSum([x[t][s_id] for t in teachers]) + shortage[s_id] == req_people
        
        for t in teachers:
            if not check_df.loc[s_id, t]:
                prob += x[t][s_id] == 0
                
    for t in teachers:
        prob += total_assign[t] <= max_s
        prob += total_assign[t] >= min_s

    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] == 'Optimal':
        total_short_count = sum(value(shortage[s]) for s in unique_slots)

        if total_short_count > 0:
            st.error(f"⚠️ 人が足りず、完璧なシフトが組めませんでした。（全体で {int(total_short_count)} 人分不足）")
            problem_list = [{"不足しているコマ": s, "足りない人数": int(value(shortage[s]))} for s in unique_slots if value(shortage[s]) > 0]
            st.warning("以下のコマの出勤可能者を増やすか、必要人数を減らして再度実行してください。")
            st.table(pd.DataFrame(problem_list))
        else:
            st.success("✨ 最適化が完了しました。全てのコマが埋まりました！")
        
        # 色分け設定
        color_palette = ["#FF4B4B", "#0068C9", "#00C250", "#FF8700", "#6D3FC0", "#D45B90", "#29B09D"]
        teacher_colors = {t: color_palette[i % len(color_palette)] for i, t in enumerate(teachers)}

        res_list = []
        for s_id in unique_slots:
            assigned = [t for t in teachers if value(x[t][s_id]) == 1]
            short_val = int(value(shortage[s_id]))
            
            colored_assigned = [f'<span style="color:{teacher_colors[t]}; font-weight:bold;">{t}</span>' for t in assigned]
            
            if short_val > 0:
                assigned_str = " / ".join(colored_assigned) + f' <span style="color:red;">🚨(あと{short_val}人不足)</span>'
            else:
                assigned_str = " / ".join(colored_assigned) if colored_assigned else "なし"
                
            res_list.append({"コマ": s_id, "担当": assigned_str})
        
        res_df = pd.DataFrame(res_list)
        res_df = res_df.sort_values(by="コマ").reset_index(drop=True)
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(res_df.to_html(escape=False, index=False), unsafe_allow_html=True)
            
        with c2:
            final_counts = {t: int(sum(value(x[t][s]) for s in unique_slots)) for t in teachers}
            chart_df = pd.DataFrame({"講師": list(final_counts.keys()), "出勤コマ数": list(final_counts.values())})
            
            # Altairグラフ描画
            chart = alt.Chart(chart_df).mark_bar().encode(
                x=alt.X('講師:N', title='', axis=alt.Axis(labelAngle=0)),
                y=alt.Y('出勤コマ数:Q', title='出勤コマ数', axis=alt.Axis(tickMinStep=1)),
                color=alt.Color('講師:N', scale=alt.Scale(domain=list(teacher_colors.keys()), range=list(teacher_colors.values())), legend=None)
            ).properties(height=350)
            
            st.altair_chart(chart, use_container_width=True)
            
            for t, v in final_counts.items():
                st.markdown(f'<span style="color:{teacher_colors[t]}; font-weight:bold;">{t}</span>: {v}コマ', unsafe_allow_html=True)
    else:
        st.error("計算中に予期せぬエラーが発生しました。")
