#!/usr/bin/env python3

"""
仮選手証システム v2.0
- requests + BeautifulSoup ベース
- URL クエリ ?role=admin で管理者/申請側を切替
- 申請保存、顔写真保存、カードPNG発行、大学別ZIP発行
- ヘッダーはKCBFロゴ（kcbf_logo.pngがあれば使用）
"""

import io
import os
import sys
import json
import time
import base64
import zipfile
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher

import streamlit as st
import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont

# 依存関係チェック（bs4不足時に明示）
_BS4_VERSION = None
try:
    from bs4 import BeautifulSoup  # type: ignore
    import bs4 as _bs4  # type: ignore
    _BS4_VERSION = getattr(_bs4, "__version__", "unknown")
except Exception:
    st.error(
        "依存パッケージ 'beautifulsoup4' が見つかりません。requirements.txt を確認してください。"
    )
    st.stop()

# ページ設定
st.set_page_config(page_title="仮選手証システム v2.0", page_icon=None, layout="wide")


class JBAVerificationSystem:
    """JBA 検証システム（簡易）"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ja-JP,ja;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def login(self, username: str, password: str) -> bool:
        """JBAサイトにログイン"""
        try:
            # ログインページ取得
            login_url = "https://team-jba.jp/login"
            response = self.session.get(login_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            csrf_token = soup.find('input', {'name': '_token'})
            if not csrf_token:
                return False
            
            # ログイン実行
            login_data = {
                '_token': csrf_token.get('value'),
                'email': username,
                'password': password,
            }
            
            response = self.session.post(login_url, data=login_data)
            return response.status_code == 200 and 'dashboard' in response.url
            
        except Exception:
            return False

    def get_team_members(self, team_id: str) -> list[dict]:
        """チームメンバー情報取得"""
        try:
            url = f"https://team-jba.jp/teams/{team_id}/members"
            response = self.session.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            members = []
            
            for member_row in soup.find_all('tr', class_='member-row'):
                name_elem = member_row.find('td', class_='member-name')
                if name_elem:
                    members.append({
                        'name': name_elem.get_text(strip=True),
                        'position': 'Player'  # 簡易実装
                    })
            
            return members
            
        except Exception:
            return []


class PrintSystem:
    """印刷・カード発行システム"""

    def __init__(self) -> None:
        self.ensure_directories()

    def ensure_directories(self) -> None:
        """必要なディレクトリを作成"""
        dirs = ['uploads/photos', 'uploads/docs', 'outputs/cards']
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)

    def _load_font(self, size: int = 12) -> ImageFont.FreeTypeFont:
        """フォント読み込み"""
        font_paths = [
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        
        # デフォルトフォント
        return ImageFont.load_default()

    def generate_card_png(self, application_id: int) -> str:
        """カードPNG生成"""
        conn = sqlite3.connect('player_applications.db')
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT pa.player_name, pa.birth_date, pa.university, pa.photo_path, t.tournament_name
            FROM player_applications pa
            LEFT JOIN tournaments t ON pa.tournament_id = t.id
            WHERE pa.id = ?
        """, (application_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            raise ValueError("申請データが見つかりません")
        
        player_name, birth_date, university, photo_path, tournament_name = result
        
        # 背景色を大会タイプに応じて設定
        bg = (0xC2, 0xE8, 0xC2)  # 緑（選手権大会）
        if tournament_name and "新人" in tournament_name:
            bg = (0xFF, 0xD1, 0xE6)  # ピンク（新人戦）
        elif tournament_name and "リーグ" in tournament_name:
            bg = (0xD9, 0xB9, 0x6E)  # 黄土色（リーグ戦）
        
        # 画像サイズ（110mm x 70mm、300DPI）
        width, height = int(110 * 300 / 25.4), int(70 * 300 / 25.4)
        img = Image.new('RGB', (width, height), bg)
        draw = ImageDraw.Draw(img)
        
        # フォント読み込み
        title_font = self._load_font(24)
        subtitle_font = self._load_font(20)
        name_font = self._load_font(28)
        univ_font = self._load_font(28)
        birth_font = self._load_font(22)
        valid_font = self._load_font(32)
        note_font = self._load_font(16)
        kyokai_font = self._load_font(12)
        
        # 枠線
        draw.rectangle([0, 0, width-1, height-1], outline=(0, 0, 0), width=8)
        
        # タイトル
        draw.text((20, 20), "第76回関東東大学バスケットボール", fill=(0, 0, 0), font=title_font)
        
        # サブタイトル（大会名）
        tournament_text = tournament_name or "新人戦"
        draw.text((200, 50), tournament_text, fill=(0, 0, 0), font=subtitle_font)
        
        # 仮選手証・スタッフ証
        draw.text((20, 80), "仮選手証・スタッフ証", fill=(0, 0, 0), font=subtitle_font)
        
        # 氏名
        draw.text((20, 120), "氏名", fill=(0, 0, 0), font=name_font)
        draw.line([(20, 150), (400, 150)], fill=(0, 0, 0), width=3)
        if player_name:
            draw.text((30, 160), player_name, fill=(0, 0, 0), font=name_font)
        
        # 大学
        draw.text((20, 200), "大学", fill=(0, 0, 0), font=univ_font)
        draw.line([(20, 230), (400, 230)], fill=(0, 0, 0), width=3)
        if university:
            draw.text((30, 240), university, fill=(0, 0, 0), font=univ_font)
        
        # 生年月日
        birth_text = f"生年月日　　　年　　　月　　　日"
        if birth_date:
            birth_text = f"生年月日　{birth_date}年　　　月　　　日"
        draw.text((20, 280), birth_text, fill=(0, 0, 0), font=birth_font)
        
        # 有効期限
        draw.text((20, 320), "※今大会のみ有効", fill=(0, 0, 0), font=valid_font)
        
        # 協会名
        draw.text((width-200, height-30), "一般社団法人関東大学バスケットボール連盟", fill=(0, 0, 0), font=kyokai_font)
        
        # 顔写真
        if photo_path and os.path.exists(photo_path):
            try:
                photo = Image.open(photo_path)
                photo = photo.resize((int(40*300/25.4), int(50*300/25.4)))
                img.paste(photo, (width-int(40*300/25.4)-20, 20))
            except Exception:
                pass
        
        # 保存
        output_path = f"outputs/cards/card_{application_id}.png"
        img.save(output_path, 'PNG')
        return output_path


def init_database() -> None:
    """データベース初期化"""
    conn = sqlite3.connect('player_applications.db')
    cursor = conn.cursor()
    
    # 申請テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT NOT NULL,
            birth_date TEXT,
            university TEXT NOT NULL,
            tournament_id INTEGER,
            photo_path TEXT,
            jba_document_path TEXT,
            staff_document_path TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tournament_id) REFERENCES tournaments (id)
        )
    ''')
    
    # 大会テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 管理者設定テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,
            setting_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # デフォルト大会データ
    cursor.execute('SELECT COUNT(*) FROM tournaments')
    if cursor.fetchone()[0] == 0:
        tournaments = [
            ('第76回関東大学バスケットボール選手権大会', '2024-01-01', '2024-01-31'),
            ('第76回関東大学バスケットボール新人戦', '2024-02-01', '2024-02-28'),
            ('第76回関東大学バスケットボールリーグ戦', '2024-03-01', '2024-03-31'),
        ]
        cursor.executemany('INSERT INTO tournaments (tournament_name, start_date, end_date) VALUES (?, ?, ?)', tournaments)
    
    conn.commit()
    conn.close()


def render_header_logo() -> None:
    import os, base64
    # 現在のスクリプトと同じ階層にある画像を参照するように変更
    logo_path = os.path.join(os.path.dirname(__file__), "kcbf_logo.png")
    if os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            logo_html = f'<img src="data:image/png;base64,{b64}" alt="KCBF" style="height:96px;" />'
        except Exception:
            logo_html = '<div style="width:96px;height:96px;border-radius:50%;background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;">KCBF</div>'
    else:
        logo_html = '<div style="width:96px;height:96px;border-radius:50%;background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;">KCBF</div>'

    st.markdown(
        f"""
        <div class="main-header">
          <div style="display:flex;align-items:center;justify-content:center;">{logo_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_styles() -> None:
    st.markdown(
        """
<style>
        :root { --navy:#0f172a; --blue:#2563eb; --white:#fff; --dark-gray:#334155; --light-gray:#eef2f7; --border-gray:#d9dee7; }
        .main-header { background: var(--navy); padding: 3rem 2rem; border-radius: 15px; margin-bottom: 2rem; color: var(--white); text-align: center; box-shadow: 0 8px 32px rgba(30,41,59,.3); }
        .card { background: rgba(255,255,255,.75); padding: 2rem; border-radius: 12px; border: 1px solid var(--border-gray); box-shadow: 0 4px 20px rgba(30,41,59,.1); }
        .status-badge { padding: 0.5rem 1rem; border-radius: 20px; font-weight: 600; font-size: 0.9rem; }
        .status-pending { background: #fef3c7; color: #92400e; }
        .status-approved { background: #d1fae5; color: #065f46; }
        .status-rejected { background: #fee2e2; color: #991b1b; }
        .sidebar { background: var(--light-gray); padding: 1.5rem; border-radius: 12px; margin-bottom: 2rem; }
        .form-group { margin-bottom: 1.5rem; }
        .form-label { font-weight: 600; color: var(--dark-gray); margin-bottom: 0.5rem; display: block; }
        .form-input { width: 100%; padding: 0.75rem; border: 2px solid var(--border-gray); border-radius: 8px; font-size: 1rem; transition: border-color 0.3s; }
        .form-input:focus { outline: none; border-color: var(--blue); }
        .btn { background: var(--blue); color: var(--white); border: none; padding: 0.75rem 1.5rem; border-radius: 8px; font-weight: 600; cursor: pointer; transition: background 0.3s; }
        .btn:hover { background: #1d4ed8; }
        .btn-secondary { background: var(--dark-gray); }
        .btn-secondary:hover { background: #1e293b; }
        .tab-container { margin-top: 2rem; }
        .tab-content { padding: 2rem 0; }
        .heading { color: var(--navy); font-weight: 700; margin-bottom: 1.5rem; }
        .subheading { color: var(--dark-gray); font-weight: 600; margin-bottom: 1rem; }
        .alert { padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }
        .alert-info { background: #dbeafe; color: #1e40af; border-left: 4px solid #3b82f6; }
        .alert-success { background: #d1fae5; color: #065f46; border-left: 4px solid #10b981; }
        .alert-error { background: #fee2e2; color: #991b1b; border-left: 4px solid #ef4444; }
        .alert-warning { background: #fef3c7; color: #92400e; border-left: 4px solid #f59e0b; }
        .expander { background: var(--light-gray); border: 1px solid var(--border-gray); border-radius: 8px; margin-bottom: 1rem; }
        .expander-header { padding: 1rem; font-weight: 600; cursor: pointer; }
        .expander-content { padding: 0 1rem 1rem; }
        .dataframe { border: 1px solid var(--border-gray); border-radius: 8px; overflow: hidden; }
        .dataframe th { background: var(--navy); color: var(--white); padding: 0.75rem; font-weight: 600; }
        .dataframe td { padding: 0.75rem; border-bottom: 1px solid var(--border-gray); }
        .dataframe tr:hover { background: var(--light-gray); }
</style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """メイン関数"""
    # スタイル注入
    inject_styles()
    
    # データベース初期化
    init_database()
    
    # ヘッダー表示
    render_header_logo()
    
    # URLクエリパラメータから管理者判定
    query_params = st.query_params
    is_admin = False
    
    # 複数のキーと値のパターンに対応
    admin_keys = ['role', 'mode', 'page']
    admin_values = ['admin', 'true', '1', 'yes']
    
    for key in admin_keys:
        if key in query_params:
            value = query_params[key].lower()
            if value in admin_values:
                is_admin = True
                break
    
    st.session_state.is_admin = is_admin
    
    if is_admin:
        # 管理者画面
        tab1, tab2, tab3, tab4 = st.tabs(["申請一覧", "大会管理", "カード発行（PNG・ZIP）", "設定"])
        
        with tab1:
            st.subheader("申請一覧")
            
            # 申請データ取得
            conn = sqlite3.connect('player_applications.db')
            df = pd.read_sql_query("""
                SELECT pa.*, t.tournament_name 
                FROM player_applications pa
                LEFT JOIN tournaments t ON pa.tournament_id = t.id
                ORDER BY pa.created_at DESC
            """, conn)
            conn.close()
            
            if not df.empty:
                # ステータス更新
                for idx, row in df.iterrows():
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"**{row['player_name']}** ({row['university']})")
                        st.write(f"大会: {row['tournament_name'] or '未選択'}")
                        if row['photo_path']:
                            try:
                                st.image(row['photo_path'], width=100)
                            except Exception:
                                st.write("画像読み込みエラー")
                    
                    with col2:
                        current_status = row['status']
                        new_status = st.selectbox(
                            "ステータス",
                            ["pending", "approved", "rejected"],
                            index=["pending", "approved", "rejected"].index(current_status),
                            key=f"status_{row['id']}"
                        )
                        
                        if new_status != current_status:
                            conn = sqlite3.connect('player_applications.db')
                            cursor = conn.cursor()
                            cursor.execute(
                                "UPDATE player_applications SET status = ? WHERE id = ?",
                                (new_status, row['id'])
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()
                    
                    with col3:
                        if st.button(f"削除", key=f"delete_{row['id']}"):
                            conn = sqlite3.connect('player_applications.db')
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM player_applications WHERE id = ?", (row['id'],))
                            conn.commit()
                            conn.close()
                            st.rerun()
                    
                    st.divider()
            else:
                st.info("申請データがありません")
        
        with tab2:
            st.subheader("大会管理")
            
            # 大会一覧
            conn = sqlite3.connect('player_applications.db')
            tournaments_df = pd.read_sql_query("SELECT * FROM tournaments ORDER BY created_at DESC", conn)
            conn.close()
            
            if not tournaments_df.empty:
                st.dataframe(tournaments_df, use_container_width=True)
            else:
                st.info("大会データがありません")
            
            # 新規大会追加
            with st.expander("新規大会追加"):
                with st.form("new_tournament"):
                    tournament_name = st.text_input("大会名")
                    start_date = st.date_input("開始日")
                    end_date = st.date_input("終了日")
                    
                    if st.form_submit_button("追加"):
                        if tournament_name:
                            conn = sqlite3.connect('player_applications.db')
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO tournaments (tournament_name, start_date, end_date) VALUES (?, ?, ?)",
                                (tournament_name, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                            )
                            conn.commit()
                            conn.close()
                            st.success("大会を追加しました")
                            st.rerun()
                        else:
                            st.error("大会名を入力してください")
        
        with tab3:
            st.subheader("カード発行（PNG・ZIP）")
            
            # 申請データ取得
            conn = sqlite3.connect('player_applications.db')
            df = pd.read_sql_query("""
                SELECT pa.*, t.tournament_name 
                FROM player_applications pa
                LEFT JOIN tournaments t ON pa.tournament_id = t.id
                WHERE pa.status = 'approved'
                ORDER BY pa.created_at DESC
            """, conn)
            conn.close()
            
            if not df.empty:
                st.write("承認済み申請のカード発行")
                
                for idx, row in df.iterrows():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{row['player_name']}** ({row['university']})")
                        st.write(f"大会: {row['tournament_name'] or '未選択'}")
                    
                    with col2:
                        if st.button(f"カードPNG発行", key=f"card_{row['id']}"):
                            try:
                                print_system = PrintSystem()
                                card_path = print_system.generate_card_png(row['id'])
                                
                                with open(card_path, "rb") as f:
                                    st.download_button(
                                        label="PNGダウンロード",
                                        data=f.read(),
                                        file_name=f"card_{row['player_name']}.png",
                                        mime="image/png"
                                    )
                                st.success("カードを生成しました")
                            except Exception as e:
                                st.error(f"カード生成エラー: {str(e)}")
                    
                    st.divider()
                
                # 大学別ZIP発行
                st.subheader("大学ごとにZIP発行")
                
                universities = df['university'].unique().tolist()
                selected_university = st.selectbox("大学を選択", universities)
                
                if st.button("ZIPを生成"):
                    try:
                        print_system = PrintSystem()
                        university_applications = df[df['university'] == selected_university]
                        
                        zip_path = f"outputs/cards/{selected_university}_cards.zip"
                        with zipfile.ZipFile(zip_path, 'w') as zipf:
                            for idx, row in university_applications.iterrows():
                                card_path = print_system.generate_card_png(row['id'])
                                zipf.write(card_path, f"card_{row['player_name']}.png")
                        
                        with open(zip_path, "rb") as f:
                            st.download_button(
                                label="ZIPダウンロード",
                                data=f.read(),
                                file_name=f"{selected_university}_cards.zip",
                                mime="application/zip"
                            )
                        st.success(f"{selected_university}のカードZIPを生成しました")
                    except Exception as e:
                        st.error(f"ZIP生成エラー: {str(e)}")
            else:
                st.info("承認済み申請がありません")
        
        with tab4:
            st.subheader("設定")
            
            # 管理者設定
            conn = sqlite3.connect('player_applications.db')
            cursor = conn.cursor()
            
            # JBA認証情報
            st.write("JBA認証情報")
            jba_username = st.text_input("JBAユーザー名")
            jba_password = st.text_input("JBAパスワード", type="password")
            
            if st.button("JBA認証テスト"):
                if jba_username and jba_password:
                    jba_system = JBAVerificationSystem()
                    if jba_system.login(jba_username, jba_password):
                        st.success("JBA認証成功")
                    else:
                        st.error("JBA認証失敗")
                else:
                    st.error("ユーザー名とパスワードを入力してください")
            
            conn.close()
    
    else:
        # 申請者画面
        st.subheader("仮選手証・仮スタッフ証申請フォーム")
        
        with st.form("application_form"):
            st.write("以下の情報を入力してください")
            
            # 基本情報
            player_name = st.text_input("氏名", placeholder="例: 田中太郎")
            birth_date = st.text_input("生年月日", placeholder="例: 2000年4月1日")
            university = st.text_input("大学名", placeholder="例: 東京大学")
            
            # 大会選択
            conn = sqlite3.connect('player_applications.db')
            tournaments_df = pd.read_sql_query("SELECT * FROM tournaments ORDER BY created_at DESC", conn)
            conn.close()
            
            if not tournaments_df.empty:
                tournament_options = ["選択してください"] + tournaments_df['tournament_name'].tolist()
                selected_tournament = st.selectbox("参加大会", tournament_options)
                tournament_id = None
                if selected_tournament != "選択してください":
                    tournament_id = tournaments_df[tournaments_df['tournament_name'] == selected_tournament]['id'].iloc[0]
            else:
                st.warning("利用可能な大会がありません")
                tournament_id = None
            
            # ファイルアップロード
            st.write("**必要書類**")
            photo_file = st.file_uploader("顔写真", type=['png', 'jpg', 'jpeg'], help="正面を向いた顔写真をアップロードしてください")
            jba_document = st.file_uploader("JBA登録証", type=['png', 'jpg', 'jpeg', 'pdf'], help="JBA登録証の画像またはPDFをアップロードしてください")
            staff_document = st.file_uploader("スタッフ証明書（スタッフの場合）", type=['png', 'jpg', 'jpeg', 'pdf'], help="スタッフの場合は証明書をアップロードしてください")
            
            if st.form_submit_button("申請する"):
                if not all([player_name, university]):
                    st.error("氏名と大学名は必須です")
                else:
                    try:
                        # ファイル保存
                        photo_path = None
                        jba_doc_path = None
                        staff_doc_path = None
                        
                        if photo_file:
                            photo_path = f"uploads/photos/{player_name}_{int(time.time())}.{photo_file.name.split('.')[-1]}"
                            with open(photo_path, "wb") as f:
                                f.write(photo_file.getbuffer())
                        
                        if jba_document:
                            jba_doc_path = f"uploads/docs/jba_{player_name}_{int(time.time())}.{jba_document.name.split('.')[-1]}"
                            with open(jba_doc_path, "wb") as f:
                                f.write(jba_document.getbuffer())
                        
                        if staff_document:
                            staff_doc_path = f"uploads/docs/staff_{player_name}_{int(time.time())}.{staff_document.name.split('.')[-1]}"
                            with open(staff_doc_path, "wb") as f:
                                f.write(staff_document.getbuffer())
                        
                        # データベース保存
                        conn = sqlite3.connect('player_applications.db')
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO player_applications 
                            (player_name, birth_date, university, tournament_id, photo_path, jba_document_path, staff_document_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (player_name, birth_date, university, tournament_id, photo_path, jba_doc_path, staff_doc_path))
                        conn.commit()
                        conn.close()
                        
                        st.success("申請が完了しました。審査結果をお待ちください。")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"申請エラー: {str(e)}")


if __name__ == "__main__":
    main()