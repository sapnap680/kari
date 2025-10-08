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
            'Accept-Language': 'ja,en;q=0.9',
            'Accept-Encoding': 'gzip,deflate,br',
            'Connection': 'keep-alive',
            'Origin': 'https://team-jba.jp',
            'Referer': 'https://team-jba.jp/organization/15250600/team/search',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'X-Requested-With': 'XMLHttpRequest'
        })
        self.logged_in = False

    def get_current_fiscal_year(self) -> str:
        now = datetime.now()
        return str(now.year)

    def login(self, email: str, password: str) -> bool:
        try:
            st.info("JBAサイトにログイン中...")
            login_page = self.session.get("https://team-jba.jp/login")
            soup = BeautifulSoup(login_page.content, 'html.parser')
            csrf_input = soup.find('input', {'name': '_token'})
            csrf_token = csrf_input.get('value', '') if csrf_input else ''

            login_data = {
                '_token': csrf_token,
                'login_id': email,
                'password': password
            }
            login_url = "https://team-jba.jp/login/done"
            res = self.session.post(login_url, data=login_data, allow_redirects=True)
            if "ログアウト" in res.text:
                st.success("ログイン成功")
                self.logged_in = True
                return True
            st.error("ログインに失敗しました")
            return False
        except Exception as e:
            st.error(f"ログインエラー: {e}")
            return False

    def search_teams_by_university(self, university_name: str):
        try:
            if not self.logged_in:
                st.error("ログインが必要です")
                return []

            current_year = self.get_current_fiscal_year()
            st.info(f"{university_name} の男子チームを検索中...({current_year}年度)")

            search_url = "https://team-jba.jp/organization/15250600/team/search"
            page = self.session.get(search_url)
            if page.status_code != 200:
                st.error("検索ページにアクセスできません")
                return []
            soup = BeautifulSoup(page.content, 'html.parser')
            csrf_input = soup.find('input', {'name': '_token'})
            csrf_token = csrf_input.get('value', '') if csrf_input else ''

            payload = {
                "limit": 100,
                "offset": 0,
                "searchLogic": "AND",
                "search": [
                    {"field": "fiscal_year", "type": "text", "operator": "is", "value": current_year},
                    {"field": "team_name", "type": "text", "operator": "contains", "value": university_name},
                    {"field": "competition_division_id", "type": "int", "operator": "is", "value": 1},
                    {"field": "team_search_out_of_range", "type": "int", "operator": "is", "value": 1}
                ]
            }
            form_data = {'request': json.dumps(payload, ensure_ascii=False)}
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'X-CSRF-Token': csrf_token,
                'X-Requested-With': 'XMLHttpRequest'
            }
            res = self.session.post(search_url, data=form_data, headers=headers)
            if res.status_code != 200:
                st.error("検索リクエストが失敗しました")
                return []
            data = res.json()
            teams = []
            if data.get('status') == 'success' and 'records' in data:
                for row in data['records']:
                    if row.get('team_gender_id') == '男子':
                        teams.append({
                            'id': row.get('id', ''),
                            'name': row.get('team_name', ''),
                            'url': f"https://team-jba.jp/organization/15250600/team/{row.get('id','')}/detail"
                        })
            st.success(f"{university_name} の男子チーム: {len(teams)}件 見つかりました")
            return teams
        except Exception as e:
            st.error(f"チーム検索エラー: {e}")
            return []

    def get_team_members(self, team_url: str):
        try:
            st.info("チームメンバー情報を取得中...")
            page = self.session.get(team_url)
            if page.status_code != 200:
                st.error(f"チームページにアクセスできません(Status: {page.status_code})")
                return {"team_name": "Error", "members": []}
            soup = BeautifulSoup(page.content, 'html.parser')
            title_el = soup.find('title')
            team_name = title_el.get_text(strip=True) if title_el else "UnknownTeam"
            members = []
            tables = soup.find_all('table')
            target = None
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 10:
                    cells = rows[0].find_all(['td', 'th'])
                    if len(cells) >= 3:
                        a, b, c = [t.get_text(strip=True) for t in cells[:3]]
                        if "メンバーID" in a and "氏名" in b and "生年月日" in c:
                            target = table
                            break
            if target:
                rows = target.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:
                        member_id = cells[0].get_text(strip=True)
                        name = cells[1].get_text(strip=True)
                        birth = cells[2].get_text(strip=True)
                        if member_id.isdigit() and name and name != "氏名":
                            members.append({"member_id": member_id, "name": name, "birth_date": birth})
            return {"team_name": team_name, "members": members}
        except Exception as e:
            st.error(f"メンバー取得エラー: {e}")
            return {"team_name": "Error", "team_url": team_url, "members": []}

    @staticmethod
    def normalize_date_format(date_str: str) -> str:
        try:
            if not date_str:
                return ""
            if "年" in date_str and "月" in date_str and "日" in date_str:
                import re as _re
                m = _re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
                if m:
                    y, mth, d = m.groups()
                    return f"{y}/{int(mth)}/{int(d)}"
            if "/" in date_str and len(date_str.split("/")) == 3:
                y, mth, d = date_str.split("/")
                return f"{y}/{int(mth)}/{int(d)}"
            return date_str
        except Exception:
            return date_str

    def verify_player_info(self, player_name: str, birth_date: str, university: str):
        try:
            teams = self.search_teams_by_university(university)
            if not teams:
                return {"status": "not_found", "message": f"{university} の男子チームが見つかりませんでした"}
            normalized_input = self.normalize_date_format(birth_date)
            for team in teams:
                data = self.get_team_members(team['url'])
                for m in data.get("members", []):
                    sim = SequenceMatcher(None, player_name, m["name"]).ratio()
                    jba_date = self.normalize_date_format(m["birth_date"])
                    if sim > 0.8 and normalized_input == jba_date:
                        return {"status": "match", "jba_data": m, "similarity": sim}
                    if sim > 0.8:
                        return {
                            "status": "name_match_birth_mismatch",
                            "jba_data": m,
                            "similarity": sim,
                            "message": f"名前は一致しますが生年月日が異なります（JBA: {m['birth_date']}）"
                        }
            return {"status": "not_found", "message": "JBAに該当なし"}
        except Exception as e:
            return {"status": "error", "message": f"照合エラー: {e}"}


class DatabaseManager:
    def __init__(self, db_path: str = "player_verification.db") -> None:
        self.db_path = db_path
        self.init_database()

    def init_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tournaments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tournament_name TEXT NOT NULL,
              tournament_year TEXT NOT NULL,
              is_active BOOLEAN DEFAULT 0,
              response_accepting BOOLEAN DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS player_applications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tournament_id INTEGER NOT NULL,
              player_name TEXT NOT NULL,
              birth_date TEXT NOT NULL,
              university TEXT NOT NULL,
              division TEXT,
              role TEXT NOT NULL,
              email TEXT,
              phone TEXT,
              remarks TEXT,
              photo_path TEXT,
              jba_file_path TEXT,
              staff_file_path TEXT,
              application_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              status TEXT DEFAULT 'pending',
              verification_result TEXT,
              jba_match_data TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (tournament_id) REFERENCES tournaments (id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_results (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              application_id INTEGER NOT NULL,
              match_status TEXT,
              jba_name TEXT,
              jba_birth_date TEXT,
              similarity_score REAL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (application_id) REFERENCES player_applications (id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_settings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              jba_email TEXT,
              jba_password TEXT,
              notification_email TEXT,
              auto_verification_enabled BOOLEAN DEFAULT 1,
              verification_threshold REAL DEFAULT 1.0,
              current_tournament_id INTEGER,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (current_tournament_id) REFERENCES tournaments (id)
            )
            """
        )
        conn.commit()
        conn.close()


class TournamentManagement:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def create_tournament(self, tournament_name: str, tournament_year: str) -> int:
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tournaments (tournament_name, tournament_year, is_active, response_accepting)
            VALUES (?, ?, 1, 1)
            """,
            (tournament_name, tournament_year),
        )
        tid = cur.lastrowid
        cur.execute("UPDATE tournaments SET is_active = 0 WHERE id != ?", (tid,))
        conn.commit()
        conn.close()
        return tid

    def get_active_tournament(self):
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments WHERE is_active = 1")
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                'id': row[0],
                'tournament_name': row[1],
                'tournament_year': row[2],
                'is_active': bool(row[3]),
                'response_accepting': bool(row[4])
            }
        return None

    def get_all_tournaments(self):
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM tournaments ORDER BY created_at DESC")
        rows = cur.fetchall()
        conn.close()
        return [
            {
                'id': r[0],
                'tournament_name': r[1],
                'tournament_year': r[2],
                'is_active': bool(r[3]),
                'response_accepting': bool(r[4])
            }
            for r in rows
        ]

    def switch_tournament(self, tournament_id: int) -> None:
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE tournaments SET is_active = 0")
        cur.execute("UPDATE tournaments SET is_active = 1 WHERE id = ?", (tournament_id,))
        conn.commit()
        conn.close()

    def set_tournament_response_accepting(self, tournament_id: int, accepting: bool) -> None:
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE tournaments
            SET response_accepting = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (accepting, tournament_id),
        )
        conn.commit()
        conn.close()


class PrintSystem:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        for path in [
            "C:/Windows/Fonts/meiryo.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def generate_card_png(self, application_id: int) -> str:
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pa.player_name, pa.birth_date, pa.university, pa.division, pa.role,
                   pa.photo_path, t.tournament_name
            FROM player_applications pa
            LEFT JOIN tournaments t ON pa.tournament_id = t.id
            WHERE pa.id = ?
            """,
            (application_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            raise RuntimeError("申請が見つかりません")
        player_name, birth_date, university, division, role, photo_path, tournament_name = row

        # 300dpi ≒ 11.81 px/mm、枠分は描画時で吸収
        mm = 11.81
        width = int((110 * mm) - 8)
        height = int((70 * mm) - 8)

        # 背景色（大会種別）: 選手権=緑, 新人=ピンク, リーグ=黄土
        bg = (0xC2, 0xE8, 0xC2)
        if tournament_name and "新人" in tournament_name:
            bg = (0xFF, 0xD1, 0xE6)
        elif tournament_name and "リーグ" in tournament_name:
            bg = (0xD9, 0xB9, 0x6E)

        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # 外枠
        draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(34, 34, 34), width=4)

        f_title = self._load_font(40)
        f_sub = self._load_font(40)
        f_label = self._load_font(36)
        f_text = self._load_font(34)
        f_small = self._load_font(18)

        photo_w = int(40 * mm)
        photo_h = int(50 * mm)
        text_pad_x = 24
        text_w = width - photo_w

        # タイトル
        draw.text((text_pad_x, 12), f"{tournament_name}", fill=(34, 34, 34), font=f_title)
        draw.text((text_pad_x + 120, 60), "新人戦", fill=(34, 34, 34), font=f_sub)
        draw.text((text_pad_x, 112), "仮選手証・スタッフ証", fill=(34, 34, 34), font=f_sub)

        # 氏名行
        y = 160
        draw.text((text_pad_x, y), "氏名", fill=(34, 34, 34), font=f_label)
        y += 40
        draw.line([(text_pad_x, y), (text_w - 12, y)], fill=(34, 34, 34), width=2)

        # 大学行
        y += 28
        draw.text((text_pad_x + 260, y), "大学", fill=(34, 34, 34), font=f_label)
        y += 40
        draw.line([(text_pad_x, y), (text_w - 12, y)], fill=(34, 34, 34), width=2)

        # 生年月日
        y += 18
        draw.text((text_pad_x, y + 12), "生年月日　　　年　　　月　　　日", fill=(34, 34, 34), font=f_text)
        # 有効
        draw.text((text_pad_x + 90, y + 60), "※今大会のみ有効", fill=(34, 34, 34), font=self._load_font(44))
        # 連盟名
        draw.text((text_pad_x + 300, y + 110), "一般社団法人関東大学バスケットボール連盟", fill=(34, 34, 34), font=f_small)

        # 写真フレーム
        photo_x = width - photo_w
        photo_y = int(25 * mm)
        draw.rectangle([(photo_x, photo_y), (width - 1, photo_y + photo_h)], outline=(0, 0, 0), width=2)
        if photo_path and os.path.exists(photo_path):
            try:
                ph = Image.open(photo_path).convert("RGB")
                ph = ph.resize((photo_w - 6, photo_h - 6), Image.LANCZOS)
                img.paste(ph, (photo_x + 3, photo_y + 3))
            except Exception:
                pass

        # 実データ（氏名/大学/生年月日）
        draw.text((text_pad_x + 90, 160), player_name or "", fill=(34, 34, 34), font=self._load_font(44))
        draw.text((text_pad_x + 340, 228), university or "", fill=(34, 34, 34), font=self._load_font(44))
        draw.text((text_pad_x + 160, 298), birth_date or "", fill=(34, 34, 34), font=f_text)

        out_dir = os.path.join("outputs", "cards")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"card_{application_id}.png")
        img.save(out_path, format="PNG")
        return out_path


class AdminDashboard:
    def __init__(self, db_manager: DatabaseManager, tournament_management: TournamentManagement) -> None:
        self.db_manager = db_manager
        self.tournament_management = tournament_management

    def get_system_settings(self):
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM admin_settings ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                'jba_email': row[1],
                'jba_password': row[2],
                'notification_email': row[3],
                'auto_verification_enabled': bool(row[4]),
                'verification_threshold': row[5],
                'current_tournament_id': row[6]
            }
        return None

    def save_system_settings(self, settings: dict) -> None:
        conn = sqlite3.connect(self.db_manager.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO admin_settings
            (jba_email, jba_password, notification_email, auto_verification_enabled,
             verification_threshold, current_tournament_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                settings.get('jba_email', ''),
                settings.get('jba_password', ''),
                settings.get('notification_email', ''),
                settings.get('auto_verification_enabled', True),
                settings.get('verification_threshold', 1.0),
                settings.get('current_tournament_id', None),
            ),
        )
        conn.commit()
        conn.close()


def render_header_logo() -> None:
    logo_path = "kcbf_logo.png"
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
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_styles()
    render_header_logo()

    # セッションオブジェクト
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = DatabaseManager()
    if 'tournament_management' not in st.session_state:
        st.session_state.tournament_management = TournamentManagement(st.session_state.db_manager)
    if 'print_system' not in st.session_state:
        st.session_state.print_system = PrintSystem(st.session_state.db_manager)
    if 'admin_dashboard' not in st.session_state:
        st.session_state.admin_dashboard = AdminDashboard(st.session_state.db_manager, st.session_state.tournament_management)
    if 'jba_system' not in st.session_state:
        st.session_state.jba_system = JBAVerificationSystem()

    # URLクエリで管理者モード切り替え
    try:
        q = st.query_params
    except Exception:
        q = st.experimental_get_query_params()
    # robust admin detection: accept role/mode/page and values admin/true/1/yes
    admin_mode = False
    if isinstance(q, dict):
        for key in ('role', 'mode', 'page'):
            if key in q:
                v = q.get(key)
                val = (v[0] if isinstance(v, list) else v or '').strip().lower()
                if val in ('admin', 'true', '1', 'yes'):
                    admin_mode = True
                    break
    st.session_state.is_admin = bool(admin_mode)

    if admin_mode:
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["申請フォーム", "照合結果", "カード発行", "統計", "管理者"])
    else:
        tab1 = st.tabs(["申請フォーム"])[0]

    # 申請フォーム
    with tab1:
        st.header("仮選手証・仮スタッフ証申請フォーム")
        active = st.session_state.tournament_management.get_active_tournament()
        if active:
            st.info(f"**大会名**: {active['tournament_name']} ({active['tournament_year']}年度)")
            if active['response_accepting']:
                st.success("回答受付中")
            else:
                st.error("回答受付停止中")
        else:
            st.warning("アクティブな大会が設定されていません（管理者は「管理者」タブから大会を作成してください）")

        if active and active.get('response_accepting'):
            st.subheader("基本情報")
            with st.form("basic_info_form"):
                c1, c2 = st.columns(2)
                with c1:
                    division = st.selectbox("部（2025年度）", ["1部", "2部", "3部", "4部", "5部"])
                    university = st.text_input("大学名", placeholder="例: 白鴎大学")
                with c2:
                    is_new = st.radio("新入生ですか？", ["はい", "いいえ"], horizontal=True)
                    ok = st.form_submit_button("基本情報を設定", type="primary")
            if ok and university:
                st.session_state.basic_info = {
                    'division': division,
                    'university': university,
                    'is_newcomer': is_new == "はい"
                }
                st.success("基本情報を設定しました")

            if 'basic_info' in st.session_state:
                st.subheader("一括入力（複数人）")
                st.info(f"**{st.session_state.basic_info['university']}** - {st.session_state.basic_info['division']} - **{active['tournament_name']}**")
                if 'section_count' not in st.session_state:
                    st.session_state.section_count = 1
                b1, b2, b3 = st.columns([1, 1, 3])
                with b1:
                    if st.button("セクション追加"):
                        st.session_state.section_count = min(st.session_state.section_count + 1, 20)
                with b2:
                    if st.button("セクション削除"):
                        st.session_state.section_count = max(st.session_state.section_count - 1, 1)
                with b3:
                    st.write(f"現在のセクション数: {st.session_state.section_count}")

                with st.form("bulk_applicants_form", clear_on_submit=False):
                    total = st.session_state.section_count
                    for i in range(total):
                        st.markdown(f"#### セクション {i+1}")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.selectbox("役職", ["選手", "スタッフ"], key=f"role_{i}")
                            st.text_input("氏名（漢字）", key=f"name_{i}")
                            st.date_input("生年月日（年・月・日）", value=datetime(2000, 1, 1), key=f"birth_{i}")
                        with c2:
                            st.file_uploader("顔写真アップロード", type=["jpg", "jpeg", "png"], key=f"photo_{i}")
                            if st.session_state.get(f"role_{i}") == "選手":
                                st.file_uploader("JBA登録用紙（PDF）", type=["pdf"], key=f"jba_{i}")
                                st.session_state[f"staff_{i}"] = None
                            else:
                                st.session_state[f"jba_{i}"] = None
                                st.file_uploader("スタッフ登録用紙", type=["pdf"], key=f"staff_{i}")
                            st.text_area("備考欄", height=80, key=f"remarks_{i}")
                        st.divider()
                    submit_all = st.form_submit_button("一括申請送信", type="primary")

                if submit_all:
                    conn = sqlite3.connect(st.session_state.db_manager.db_path)
                    cur = conn.cursor()
                    os.makedirs("uploads/photos", exist_ok=True)
                    os.makedirs("uploads/docs", exist_ok=True)
                    ids, added, skipped = [], 0, 0
                    for i in range(st.session_state.section_count):
                        name_val = st.session_state.get(f"name_{i}")
                        birth_val = st.session_state.get(f"birth_{i}")
                        role_val = st.session_state.get(f"role_{i}")
                        remarks_val = st.session_state.get(f"remarks_{i}") or ""
                        photo_file = st.session_state.get(f"photo_{i}")
                        jba_file = st.session_state.get(f"jba_{i}")
                        staff_file = st.session_state.get(f"staff_{i}")
                        if not name_val or not birth_val:
                            skipped += 1
                            continue
                        photo_path = None
                        if photo_file is not None:
                            photo_bytes = photo_file.getvalue()
                            photo_path = os.path.join("uploads/photos", f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{i}.png")
                            Image.open(io.BytesIO(photo_bytes)).convert("RGB").save(photo_path, format="PNG")
                        jba_path = None
                        if jba_file is not None:
                            jba_path = os.path.join("uploads/docs", f"jba_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{i}.pdf")
                            with open(jba_path, "wb") as f:
                                f.write(jba_file.getvalue())
                        staff_path = None
                        if staff_file is not None:
                            staff_path = os.path.join("uploads/docs", f"staff_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{i}.pdf")
                            with open(staff_path, "wb") as f:
                                f.write(staff_file.getvalue())
                        cur.execute(
                            """
                            INSERT INTO player_applications
                            (tournament_id, player_name, birth_date, university, division, role, remarks, photo_path, jba_file_path, staff_file_path, verification_result, jba_match_data)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                active['id'],
                                name_val,
                                birth_val.strftime('%Y/%m/%d'),
                                st.session_state.basic_info['university'],
                                st.session_state.basic_info['division'],
                                role_val,
                                remarks_val,
                                photo_path,
                                jba_path,
                                staff_path,
                                "pending",
                                "",
                            ),
                        )
                        ids.append(cur.lastrowid)
                        added += 1
                    conn.commit()
                    conn.close()
                    if added:
                        st.success(f"{added}名の申請が送信されました")
                        st.info(f"申請ID: {','.join(map(str, ids))}")
                    if skipped:
                        st.warning(f"入力不足のため {skipped} 件をスキップしました（氏名と生年月日が必須）")
        else:
            if active is None:
                st.info("管理者が大会を作成すると申請フォームが表示されます。")
            elif not active.get('response_accepting'):
                st.info("現在、この大会の回答受付は停止中です。")

    # 照合結果
    if admin_mode:
        with tab2:
            st.header("申請照合・管理")
            with st.expander("JBAログイン設定"):
                jba_email = st.text_input("JBAメールアドレス")
                jba_password = st.text_input("JBAパスワード", type="password")
                if st.button("JBAにログイン"):
                    if jba_email and jba_password:
                        if st.session_state.jba_system.login(jba_email, jba_password):
                            st.success("ログイン成功")
                        else:
                            st.error("ログイン失敗")
                    else:
                        st.error("ログイン情報を入力してください")

            st.subheader("申請一覧と照合")
            active = st.session_state.tournament_management.get_active_tournament()
            if active:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, player_name, birth_date, university, division, role, application_date, verification_result
                    FROM player_applications
                    WHERE tournament_id = ?
                    ORDER BY application_date DESC
                    """,
                    (active['id'],),
                )
                apps = cur.fetchall()
                conn.close()
                if apps:
                    st.write(f"**{active['tournament_name']}** の申請一覧")
                    for app in apps:
                        app_id, player_name, birth_date, university, division, role, app_date, vres = app
                        with st.expander(f"申請ID: {app_id} - {player_name} ({university})"):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown('<div class="card">', unsafe_allow_html=True)
                                st.write(f"**氏名**: {player_name}")
                                st.write(f"**生年月日**: {birth_date}")
                                st.write(f"**大学**: {university}")
                                st.write(f"**部**: {division}")
                                st.write(f"**役職**: {role}")
                                st.write(f"**申請日**: {app_date}")
                                st.markdown('</div>', unsafe_allow_html=True)
                            with c2:
                                if st.button("照合実行", key=f"verify_{app_id}", type="primary"):
                                    if not st.session_state.jba_system.logged_in:
                                        st.error("先にJBAにログインしてください")
                                    else:
                                        st.info("JBAデータベースと照合中...")
                                        res = st.session_state.jba_system.verify_player_info(player_name, birth_date, university)
                                        conn = sqlite3.connect(st.session_state.db_manager.db_path)
                                        cur = conn.cursor()
                                        cur.execute(
                                            """
                                            UPDATE player_applications
                                            SET verification_result = ?, jba_match_data = ?
                                            WHERE id = ?
                                            """,
                                            (res["status"], json.dumps(res.get("jba_data", {}), ensure_ascii=False), app_id),
                                        )
                                        cur.execute(
                                            """
                                            INSERT OR REPLACE INTO verification_results
                                            (application_id, match_status, jba_name, jba_birth_date, similarity_score)
                                            VALUES (?, ?, ?, ?, ?)
                                            """,
                                            (
                                                app_id,
                                                res["status"],
                                                (res.get("jba_data") or {}).get("name", ""),
                                                (res.get("jba_data") or {}).get("birth_date", ""),
                                                res.get("similarity", 0.0),
                                            ),
                                        )
                                        conn.commit()
                                        conn.close()
                                        st.rerun()
                            if vres and vres != "pending":
                                st.info(f"照合結果: {vres}")
                else:
                    st.info("申請がありません")
            else:
                st.info("アクティブな大会が設定されていません")

        # カード発行（PNG/ZIP）
        with tab3:
            st.header("カード発行（PNG・ZIP）")
            active = st.session_state.tournament_management.get_active_tournament()
            if active:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, player_name, university, role, application_date
                    FROM player_applications
                    WHERE tournament_id = ?
                    ORDER BY application_date DESC
                    """,
                    (active['id'],),
                )
                apps = cur.fetchall()
                conn.close()
                if apps:
                    st.write(f"**申請一覧** ({len(apps)}件)")
                    for app in apps:
                        a_id, a_name, a_univ, a_role, a_date = app
                        c1, c2, c3 = st.columns([3, 1, 1])
                        with c1:
                            st.write(f"**{a_name}** ({a_univ}) - {a_role}")
                            st.write(f"申請日: {a_date}")
                        with c2:
                            if st.button("カードPNG発行", key=f"png_{a_id}"):
                                try:
                                    png_path = st.session_state.print_system.generate_card_png(a_id)
                                    with open(png_path, "rb") as f:
                                        st.download_button(
                                            label="ダウンロード",
                                            data=f.read(),
                                            file_name=os.path.basename(png_path),
                                            mime="image/png",
                                            key=f"dl_{a_id}"
                                        )
                                    st.success("PNGを生成しました")
                                except Exception as e:
                                    st.error(f"発行エラー: {e}")
                        with c3:
                            if st.button("詳細", key=f"detail_{a_id}"):
                                st.session_state.selected_application = a_id
                                st.rerun()
                        st.divider()

                    st.subheader("大学ごとにZIP発行")
                    universities = sorted(list({a[2] for a in apps}))
                    target = st.selectbox("大学選択", ["選択"] + universities)
                    if target != "選択":
                        if st.button("ZIPを生成"):
                            try:
                                mem = io.BytesIO()
                                with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                                    for a in apps:
                                        a_id, a_name, a_univ, a_role, a_date = a
                                        if a_univ != target:
                                            continue
                                        png_path = st.session_state.print_system.generate_card_png(a_id)
                                        zf.write(png_path, arcname=os.path.join(target, os.path.basename(png_path)))
                                mem.seek(0)
                                st.download_button(
                                    label=f"{target}_cards.zip をダウンロード",
                                    data=mem.getvalue(),
                                    file_name=f"{target}_cards.zip",
                                    mime="application/zip",
                                )
                            except Exception as e:
                                st.error(f"ZIP生成エラー: {e}")
                else:
                    st.info("申請がありません")
            else:
                st.warning("アクティブな大会が設定されていません")

        # 統計
        with tab4:
            st.header("統計情報")
            active = st.session_state.tournament_management.get_active_tournament()
            if active:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM player_applications WHERE tournament_id = ?", (active['id'],))
                total = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT
                        COUNT(CASE WHEN vr.match_status = 'マッチ' THEN 1 END) AS matched,
                        COUNT(CASE WHEN vr.match_status = '未マッチ' THEN 1 END) AS unmatched,
                        COUNT(CASE WHEN vr.match_status = '複数候補' THEN 1 END) AS multiple
                    FROM player_applications pa
                    LEFT JOIN verification_results vr ON pa.id = vr.application_id
                    WHERE pa.tournament_id = ?
                    """,
                    (active['id'],),
                )
                r = cur.fetchone() or (0, 0, 0)
                matched, unmatched, multiple = (r[0] or 0), (r[1] or 0), (r[2] or 0)
                conn.close()
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("総申請数", total)
                with c2:
                    st.metric("マッチ", matched)
                with c3:
                    st.metric("未マッチ", unmatched)
                with c4:
                    st.metric("複数候補", multiple)
            else:
                st.warning("アクティブな大会が設定されていません")

        # 管理者
        with tab5:
            st.header("管理者ダッシュボード")
            active = st.session_state.tournament_management.get_active_tournament()
            if active:
                st.info(f"**現在のアクティブな大会**: {active['tournament_name']} ({active['tournament_year']}年度)")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("回答受付制御"):
                        new_status = not active['response_accepting']
                        st.session_state.tournament_management.set_tournament_response_accepting(active['id'], new_status)
                        st.success(f"回答受付を{'有効' if new_status else '無効'}にしました")
                        st.rerun()
                with c2:
                    st.write(f"**回答受付**: {'有効' if active['response_accepting'] else '無効'}")
            else:
                st.warning("アクティブな大会が設定されていません")

            st.subheader("新しい大会を作成")
            with st.form("create_tournament_form"):
                c1, c2 = st.columns(2)
                with c1:
                    tournament_type = st.selectbox("大会種別", ["選手権大会", "新人戦", "リーグ戦"])
                    number = st.number_input("第○回", min_value=1, max_value=999, value=76)
                with c2:
                    year = st.text_input("年度", placeholder="例:2025")
                if tournament_type and number:
                    auto_name = f"第{number}回関東大学バスケットボール{tournament_type}"
                    st.info(f"**生成される大会名**: {auto_name}")
                if st.form_submit_button("大会を作成"):
                    if tournament_type and number and year:
                        name = f"第{number}回関東大学バスケットボール{tournament_type}"
                        tid = st.session_state.tournament_management.create_tournament(name, year)
                        st.success(f"大会を作成しました（ID: {tid}）")
                        st.success(f"**大会名**: {name}")
                        st.rerun()
                    else:
                        st.error("大会種別、回数、年度を入力してください")

            st.subheader("大会を切り替え")
            tournaments = st.session_state.tournament_management.get_all_tournaments()
            if tournaments:
                options = {f"{t['tournament_name']} ({t['tournament_year']}年度)": t['id'] for t in tournaments}
                selected = st.selectbox("大会を選択", list(options.keys()))
                if st.button("大会を切り替え"):
                    st.session_state.tournament_management.switch_tournament(options[selected])
                    st.success("大会を切り替えました")
                    st.rerun()
            else:
                st.info("大会がありません")

            st.subheader("システム設定")
            settings = st.session_state.admin_dashboard.get_system_settings()
            if settings:
                with st.form("system_settings_form"):
                    st.text_input("JBAメールアドレス", value=settings.get('jba_email', ''), key="admin_jba_email")
                    st.text_input("JBAパスワード", value=settings.get('jba_password', ''), type="password", key="admin_jba_password")
                    st.text_input("通知メールアドレス", value=settings.get('notification_email', ''), key="admin_notification_email")
                    auto = st.checkbox("自動照合を有効にする", value=settings.get('auto_verification_enabled', True))
                    thr = st.slider("照合閾値", 0.1, 1.0, settings.get('verification_threshold', 1.0), 0.05)
                    if st.form_submit_button("設定を保存"):
                        new_settings = {
                            'jba_email': st.session_state.admin_jba_email,
                            'jba_password': st.session_state.admin_jba_password,
                            'notification_email': st.session_state.admin_notification_email,
                            'auto_verification_enabled': auto,
                            'verification_threshold': thr,
                            'current_tournament_id': active['id'] if active else None,
                        }
                        st.session_state.admin_dashboard.save_system_settings(new_settings)
                        st.success("設定を保存しました")


if __name__ == "__main__":
    main()