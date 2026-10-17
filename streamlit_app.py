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
# 👇 消えてしまった load_data 関数です！
def load_data():
    ins_res = supabase.table("instructors").select("name").execute()
    teachers = [row['name'] for row in ins_res.data]
    
    slot_res = supabase.table("slots").select("*").order("date").execute()
    slots_df = pd.DataFrame(slot_res.data)
    
    avail_res = supabase.table("availability").select("*").execute()
    
    return teachers, slots_df, avail_res.data

def save_to_supabase(teachers, slots_df, check_df, start_date, end_date):
    try:
        # 1. 講師リストの更新
        for t in teachers:
            supabase.table("instructors").upsert({"name": t}, on_conflict="name").execute()
            
        # 🌟【追加】画面から消された講師をDBからも削除する
        res_ins = supabase.table("instructors").select("name").execute()
        db_teachers = [row['name'] for row in res_ins.data]
        teachers_to_delete = [t for t in db_teachers if t not in teachers]
        
        for t in teachers_to_delete:
            # 講師を消す前に、その講師の出勤可能データ（シフト希望）も一緒に消してあげる
            supabase.table("availability").delete().eq("instructor_name", t).execute()
            supabase.table("instructors").delete().eq("name", t).execute()

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

        # 4. 画面上で削除されたコマをDBからも削除する
        current_slot_ids = slots_df['slot_id'].tolist()
        res = supabase.table("slots").select("slot_id").gte("date", str(start_date)).lte("date", str(end_date)).execute()
        db_slot_ids = [row['slot_id'] for row in res.data]
        slots_to_delete = [s_id for s_id in db_slot_ids if s_id not in current_slot_ids]
        
        for s_id in slots_to_delete:
            supabase.table("availability").delete().eq("slot_id", s_id).execute()
            supabase.table("slots").delete().eq("slot_id", s_id).execute()
        
        # セッションをクリアして強制的にリロードさせる
        for key in ["slot_definition", "availability_df", "prev_slots", "prev_teachers"]:
            if key in st.session_state:
                del st.session_state[key]
        
        st.success("✅ データをSupabaseに保存しました！画面を更新します...")
        st.rerun()

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

col_date1, col_date2 = st.columns(2)
with col_date1:
    start_date = st.date_input("開始日", value=datetime.date.today(), key="start_date")
    req_weekday = st.number_input("平日の必要人数", min_value=1, value=2)
with col_date2:
    end_date = st.date_input("終了日", value=datetime.date.today() + datetime.timedelta(days=30), key="end_date")
    req_sat = st.number_input("土曜の必要人数", min_value=1, value=3)

if not loaded_slots.empty:
    loaded_slots['date'] = pd.to_datetime(loaded_slots['date']).dt.date
    filtered_slots = loaded_slots[(loaded_slots['date'] >= start_date) & (loaded_slots['date'] <= end_date)]
else:
    filtered_slots = pd.DataFrame()

dates_changed = False
if st.session_state.get('view_start') != start_date or st.session_state.get('view_end') != end_date:
    dates_changed = True
    st.session_state['view_start'] = start_date
    st.session_state['view_end'] = end_date

if dates_changed or 'slot_definition' not in st.session_state:
    if not filtered_slots.empty:
        st.session_state.slot_definition = filtered_slots.rename(columns={
            "date": "日付", "day": "曜日", "slot_name": "コマ名", "req_people": "必要人数"
        }).drop(columns=["id", "slot_id"], errors="ignore")
    else:
        if 'slot_definition' in st.session_state:
            del st.session_state['slot_definition']

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
    st.session_state.slot_definition = st.session_state.slot_definition.sort_values(by=["日付", "コマ名"]).reset_index(drop=True)
    edited_slots = st.data_editor(st.session_state.slot_definition, num_rows="dynamic", key="slot_editor")
    unique_slots = [f"{r['日付']}({r['曜日']})_{r['コマ名']}" for _, r in edited_slots.iterrows()]
    edited_slots['slot_id'] = unique_slots
else:
    st.info("上のボタンを押してコマを生成するか、手動で設定を開始してください。")
    st.stop()

# --- 3. 出勤可能チェック ---
st.subheader("3. 出勤可能チェック")

# 🌟【変更】先生のリスト（teachers）が変更された時も、表を新しく作り直すように条件を追加！
if 'availability_df' not in st.session_state or st.session_state.get('prev_slots') != unique_slots or st.session_state.get('prev_teachers') != teachers:
    df = pd.DataFrame(False, index=unique_slots, columns=teachers)
    for item in loaded_avail:
        if item['slot_id'] in df.index and item['instructor_name'] in df.columns:
            df.at[item['slot_id'], item['instructor_name']] = item['is_available']
    st.session_state.availability_df = df
    st.session_state.prev_slots = unique_slots
    st.session_state.prev_teachers = teachers # ← これも追加

check_df = st.data_editor(st.session_state.availability_df, use_container_width=True)
if st.button("現在の入力内容をデータベースに保存する"):
    save_to_supabase(teachers, edited_slots, check_df, start_date, end_date)

# --- 4. シフト割り振り実行（最適化ロジック） ---
st.subheader("4. シフト自動割り振り")
if st.button("シフトを自動生成する"):
    try:
        import pulp
        
        num_slots = len(unique_slots)
        
        prob = pulp.LpProblem("Slot_Based_Balancing", pulp.LpMinimize)
        
        # 🌟【修正】dictsを使わず、内包表記で確実に変数を生成
        x = {t: {s: pulp.LpVariable(f"x_{t}_{s}", cat=pulp.LpBinary) for s in unique_slots} for t in teachers}
        shortage = {s: pulp.LpVariable(f"shortage_{s}", lowBound=0, cat=pulp.LpInteger) for s in unique_slots}
        
        total_assign = {t: pulp.lpSum([x[t][s] for s in unique_slots]) for t in teachers}
        
        max_s = pulp.LpVariable("max_s", lowBound=0)
        min_s = pulp.LpVariable("min_s", lowBound=0)
        
        # 1. 同じ日のコマをグループ化する（連続勤務の評価用）
        slots_by_date = {}
        for s in unique_slots:
            date_part = s.split("_")[0]
            if date_part not in slots_by_date:
                slots_by_date[date_part] = []
            slots_by_date[date_part].append(s)

        switch_vars = []
        for date, slots in slots_by_date.items():
            sorted_slots = sorted(slots)
            for i in range(len(sorted_slots) - 1):
                s1 = sorted_slots[i]
                s2 = sorted_slots[i+1]
                for t in teachers:
                    # 変数名に記号が含まれるとエラーになるのを防ぐため置換
                    safe_s1 = s1.replace("-", "_").replace("(", "_").replace(")", "_")
                    safe_s2 = s2.replace("-", "_").replace("(", "_").replace(")", "_")
                    w = pulp.LpVariable(f"switch_{t}_{safe_s1}_{safe_s2}", lowBound=0, cat=pulp.LpContinuous)
                    prob += w >= x[t][s1] - x[t][s2]
                    prob += w >= x[t][s2] - x[t][s1]
                    switch_vars.append(w)

        # 2. 曜日ごとのコマをグループ化する（曜日の偏り防止用）
        slots_by_dow = {}
        for s in unique_slots:
            dow = s.split("(")[1].split(")")[0]
            if dow not in slots_by_dow:
                slots_by_dow[dow] = []
            slots_by_dow[dow].append(s)

        max_dow_vars = []
        for t in teachers:
            max_dow_t = pulp.LpVariable(f"max_dow_{t}", lowBound=0)
            max_dow_vars.append(max_dow_t)
            for dow, slots_in_dow in slots_by_dow.items():
                prob += max_dow_t >= pulp.lpSum([x[t][s] for s in slots_in_dow])

        fairness_violation = pulp.LpVariable("fairness_violation", lowBound=0)
        prob += fairness_violation >= (max_s - min_s) - 2
        
        prob += 100000 * pulp.lpSum([shortage[s] for s in unique_slots]) + \
                10000 * fairness_violation + \
                100 * pulp.lpSum(switch_vars) + \
                10 * pulp.lpSum(max_dow_vars) + \
                1 * (max_s - min_s)
        
        for idx, s_id in enumerate(unique_slots):
            req_people = int(edited_slots.iloc[idx]['必要人数'])
            prob += pulp.lpSum([x[t][s_id] for t in teachers]) + shortage[s_id] == req_people
            
            for t in teachers:
                if not check_df.loc[s_id, t]:
                    prob += x[t][s_id] == 0
                    
        for t in teachers:
            prob += total_assign[t] <= max_s
            prob += total_assign[t] >= min_s

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        # （これ以降の Optimal 判定・カレンダー描画・グラフ描画・一覧表描画は既存のままで動作します）
