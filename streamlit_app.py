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
    # 1. 講師リストの更新（既に同じ名前があれば上書き）
    for t in teachers:
        supabase.table("instructors").upsert(
            {"name": t}, 
            on_conflict="name"  # ← ここを追加！
        ).execute()
    
    # 2. スロット定義の保存（既に同じコマIDがあれば上書き）
    for _, row in slots_df.iterrows():
        supabase.table("slots").upsert({
            "slot_id": row['slot_id'],
            "date": str(row['日付']), 
            "day": row['曜日'],
            "slot_name": row['コマ名'],
            "req_people": int(row['必要人数'])
        }, on_conflict="slot_id").execute()  # ← ここを追加！
    
    # 3. 出勤可能状況の保存（先生とコマの組み合わせが同じなら上書き）
    for slot_id, row in check_df.iterrows():
        for t in teachers:
            supabase.table("availability").upsert({
                "instructor_name": t,
                "slot_id": slot_id,
                "is_available": bool(row[t])
            }, on_conflict="instructor_name,slot_id").execute()  # ← ここを追加！
            
    st.success("データをSupabaseに保存しました！")

# --- メイン UI ---
st.title("📅 塾シフト管理 (Supabase永続化版)")

# データのロード
loaded_teachers, loaded_slots, loaded_avail = load_data()

with st.sidebar:
    st.header("1. 講師設定")
    default_t = ", ".join(loaded_teachers) if loaded_teachers else "田中, 佐藤, 鈴木, 高橋, 伊藤"
    teachers_input = st.text_area("講師名（カンマ区切り）", default_t)
    teachers = [t.strip() for t in teachers_input.split(",") if t.strip()]

# --- 2. コマの設定 ---
st.subheader("2. コマの設定")

# 初回ロード時のみ、Supabaseのデータをセッションに入れる
if not loaded_slots.empty and 'slot_definition' not in st.session_state:
    st.info("データベースから前回のスケジュールを読み込みました。")
    st.session_state.slot_definition = loaded_slots.rename(columns={
        "date": "日付", "day": "曜日", "slot_name": "コマ名", "req_people": "必要人数"
    })

# 期間と「必要人数」の選択UI
col_date1, col_date2 = st.columns(2)
with col_date1:
    start_date = st.date_input("開始日", datetime.date.today())
    # 👇 平日のデフォルト人数を設定できるように追加
    req_weekday = st.number_input("平日の必要人数（水・木・金）", min_value=1, value=2)
with col_date2:
    end_date = st.date_input("終了日", datetime.date.today() + datetime.timedelta(days=30))
    # 👇 土曜のデフォルト人数を設定できるように追加
    req_sat = st.number_input("土曜の必要人数", min_value=1, value=3)

# 自動生成ボタン
if st.button("期間内の基本コマを自動生成（※現在の表は上書きされます）"):
    date_range = pd.date_range(start=start_date, end=end_date)
    default_slots = []
    
    for d in date_range:
        day_name = d.strftime("%a")
        num_slots = 0
        current_req = 1
        
        # 曜日ごとにコマ数と、設定した必要人数を割り当てる
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

# コマ編集表の表示
if 'slot_definition' in st.session_state:
    edited_slots = st.data_editor(st.session_state.slot_definition, num_rows="dynamic", key="slot_editor")
    
    # スロット識別子の作成
    unique_slots = [f"{r['日付']}({r['曜日']})_{r['コマ名']}" for _, r in edited_slots.iterrows()]
    edited_slots['slot_id'] = unique_slots
else:
    st.info("上のボタンを押してコマを生成するか、手動で設定を開始してください。")
    st.stop()

# --- 3. 出勤可能チェック ---
st.subheader("3. 出勤可能チェック")

if 'availability_df' not in st.session_state or st.session_state.get('prev_slots') != unique_slots:
    df = pd.DataFrame(False, index=unique_slots, columns=teachers)
    # Supabaseのデータを反映
    for item in loaded_avail:
        if item['slot_id'] in df.index and item['instructor_name'] in df.columns:
            df.at[item['slot_id'], item['instructor_name']] = item['is_available']
            
    st.session_state.availability_df = df
    st.session_state.prev_slots = unique_slots

check_df = st.data_editor(st.session_state.availability_df, use_container_width=True)

# 保存ボタン
if st.button("現在の入力内容をデータベースに保存する"):
    save_to_supabase(teachers, edited_slots, check_df)

# --- 4. シフト割り振り実行 ---
st.subheader("4. シフト自動割り振り")
if st.button("シフトを自動生成する"):
    num_slots = len(unique_slots)
    
    prob = LpProblem("Slot_Based_Balancing", LpMinimize)
    x = LpVariable.dicts("slot_assign", (teachers, unique_slots), cat=LpBinary)
    
    # 👇 追加：各コマの「不足人数」を表す変数（0以上の整数）
    shortage = LpVariable.dicts("shortage", unique_slots, lowBound=0, cat=LpInteger)
    
    total_assign = {t: lpSum([x[t][s] for s in unique_slots]) for t in teachers}
    
    max_s = LpVariable("max_s", lowBound=0)
    min_s = LpVariable("min_s", lowBound=0)
    
    # 👇 変更：「最大と最小の差」に加えて、「不足人数」に超巨大なペナルティ(10000)を与えて最小化する
    prob += (max_s - min_s) + 10000 * lpSum([shortage[s] for s in unique_slots])
    
    for idx, s_id in enumerate(unique_slots):
        req_people = int(edited_slots.iloc[idx]['必要人数'])
        
        # 👇 変更：出勤する人 ＋ 不足人数 ＝ 必要人数 になるようにする
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
            
            problem_list = []
            for s in unique_slots:
                short_val = int(value(shortage[s]))
                if short_val > 0:
                    problem_list.append({"不足しているコマ": s, "足りない人数": short_val})
            
            st.warning("以下のコマの出勤可能者を増やすか、必要人数を減らして再度実行してください。")
            st.table(pd.DataFrame(problem_list))
            
        else:
            st.success("✨ 最適化が完了しました。全てのコマが埋まりました！")
        
        # --- 🌟ここから追加（色分け＆並び替え）🌟 ---
        
        # 1. 講師ごとのテーマカラーを設定（グラフや表で使います）
        color_palette = ["#FF4B4B", "#0068C9", "#00C250", "#FF8700", "#6D3FC0", "#D45B90", "#29B09D"]
        teacher_colors = {t: color_palette[i % len(color_palette)] for i, t in enumerate(teachers)}

        res_list = []
        for s_id in unique_slots:
            assigned = [t for t in teachers if value(x[t][s_id]) == 1]
            short_val = int(value(shortage[s_id]))
            
            # HTMLタグを使って先生の名前に色をつける
            colored_assigned = []
            for t in assigned:
                colored_assigned.append(f'<span style="color:{teacher_colors[t]}; font-weight:bold;">{t}</span>')
            
            if short_val > 0:
                assigned_str = " / ".join(colored_assigned) + f' <span style="color:red;">🚨(あと{short_val}人不足)</span>'
            else:
                assigned_str = " / ".join(colored_assigned) if colored_assigned else "なし"
                
            res_list.append({"コマ": s_id, "担当": assigned_str})
        
        res_df = pd.DataFrame(res_list)
        
        # 2. コマの名前で並び替え（ソート）
        # 文字列が「年-月-日_第〇コマ」なので、アルファベット順に並べるだけで綺麗に時系列になります
        res_df = res_df.sort_values(by="コマ").reset_index(drop=True)
        
        c1, c2 = st.columns([2, 1])
        with c1:
            # HTMLを解釈して色付きの表を表示する
            st.markdown(res_df.to_html(escape=False, index=False), unsafe_allow_html=True)
        with c2:
            final_counts = {t: int(sum(value(x[t][s]) for s in unique_slots)) for t in teachers}
            
            chart_df = pd.DataFrame({
                "講師": list(final_counts.keys()),
                "出勤コマ数": list(final_counts.values())
            })
            
            # 👇 修正：Altairを使って、表の文字色(teacher_colors)と完全に一致させる
            chart = alt.Chart(chart_df).mark_bar().encode(
                x=alt.X('講師:N', title='', axis=alt.Axis(labelAngle=0)), # X軸の設定
                y=alt.Y('出勤コマ数:Q', title='出勤コマ数', axis=alt.Axis(tickMinStep=1)), # 小数点が出ないように調整
                color=alt.Color('講師:N', scale=alt.Scale(
                    domain=list(teacher_colors.keys()),
                    range=list(teacher_colors.values())  # ここで色を強制的に一致させています
                ), legend=None) # X軸に名前があるので、余分な凡例は隠す
            ).properties(
                height=350
            )
            
            st.altair_chart(chart, use_container_width=True)
            
            # グラフの下のテキスト
            for t, v in final_counts.items():
                st.markdown(f'<span style="color:{teacher_colors[t]}; font-weight:bold;">{t}</span>: {v}コマ', unsafe_allow_html=True)     
       
    else:
        st.error("計算中に予期せぬエラーが発生しました。")
