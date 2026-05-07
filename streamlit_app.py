import streamlit as st
import pandas as pd
from pulp import *
import datetime
from supabase import create_client, Client

# --- Supabase初期化 ---
url: str = st.secrets["URL"]
key: str = st.secrets["KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="塾シフト管理 + Supabase", layout="wide")

# --- データ操作用関数 ---
def load_data():
    # 講師リストの読み込み
    ins_res = supabase.table("instructors").select("name").execute()
    teachers = [row['name'] for row in ins_res.data]
    
    # スロット定義の読み込み
    slot_res = supabase.table("slots").select("*").order("date").execute()
    slots_df = pd.DataFrame(slot_res.data)
    
    # 出勤可能状況の読み込み
    avail_res = supabase.table("availability").select("*").execute()
    
    return teachers, slots_df, avail_res.data

def save_to_supabase(teachers, slots_df, check_df):
    # 1. 講師リストの更新 (一旦消して入れるか、upsert)
    # 簡略化のため、現在のリストで上書き（必要に応じてロジック調整）
    for t in teachers:
        supabase.table("instructors").upsert({"name": t}).execute()
    
    # 2. スロット定義の保存
    for _, row in slots_df.iterrows():
        supabase.table("slots").upsert({
            "slot_id": row['slot_id'],
            "date": row['日付'],
            "day": row['曜日'],
            "slot_name": row['コマ名'],
            "req_people": row['必要人数']
        }).execute()
    
    # 3. 出勤可能状況の保存
    for slot_id, row in check_df.iterrows():
        for t in teachers:
            supabase.table("availability").upsert({
                "instructor_name": t,
                "slot_id": slot_id,
                "is_available": bool(row[t])
            }).execute()
    st.success("データをSupabaseに保存しました！")

# --- メイン UI ---
st.title("📅 塾シフト管理 (Supabase永続化版)")

# データのロード
loaded_teachers, loaded_slots, loaded_avail = load_data()

with st.sidebar:
    st.header("1. 講師設定")
    default_t = ", ".join(loaded_teachers) if loaded_teachers else "田中, 佐藤, 鈴木"
    teachers_input = st.text_area("講師名（カンマ区切り）", default_t)
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]

# スケジュール設定
st.subheader("2. コマの設定")
if not loaded_slots.empty:
    st.info("前回のデータがロードされました。")
    st.session_state.slot_definition = loaded_slots.rename(columns={
        "date": "日付", "day": "曜日", "slot_name": "コマ名", "req_people": "必要人数"
    })

# (中略：前回の自動生成ロジックをここに配置)

if 'slot_definition' in st.session_state:
    edited_slots = st.data_editor(st.session_state.slot_definition, num_rows="dynamic", key="slot_editor")
    unique_slots = [f"{r['日付']}({r['曜日']})_{r['コマ名']}" for _, r in edited_slots.iterrows()]
    edited_slots['slot_id'] = unique_slots

    # 出勤可能チェックの初期値にロードしたデータを反映
    if 'availability_df' not in st.session_state:
        df = pd.DataFrame(False, index=unique_slots, columns=teachers)
        # ロードデータの反映
        for item in loaded_avail:
            if item['slot_id'] in df.index and item['instructor_name'] in df.columns:
                df.at[item['slot_id'], item['instructor_name']] = item['is_available']
        st.session_state.availability_df = df

    st.subheader("3. 出勤可能チェック")
    check_df = st.data_editor(st.session_state.availability_df, use_container_width=True)

    # 保存ボタン
    if st.button("現在の入力内容を保存する"):
        save_to_supabase(teachers, edited_slots, check_df)

    # シフト生成ボタン (前回のロジックと同様)
    if st.button("シフトを自動生成する"):
        # (前回の PuLP 最適化ロジックを実行)
        pass
