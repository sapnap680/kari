#!/usr/bin/env python3

"""
仮選手証システムv2.0

- Playwright依存を排除
- requests+BeautifulSoupベース
- 既存の管理者機能を統合
"""

import streamlit as st
import pandas as pd
import json
import requests
import sys

# 依存関係チェック（bs4不足時に明示して停止）
_BS4_VERSION = None
try:
    from bs4 import BeautifulSoup  # type: ignore
    import bs4 as _bs4  # type: ignore
    _BS4_VERSION = getattr(_bs4, "__version__", "unknown")
except Exception:
st.error(
"依存パッケージ'beautifulsoup4'が見つかりません。requirements.txtがデプロイで読み込まれているか確認してください。"
)
st.stop()

import sqlite3
import os
import io
import zipfile
import base64
from datetime import datetime
import re
import unicodedata
from difflib import SequenceMatcher
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import schedule
import time
import threading
from PIL import Image, ImageDraw, ImageFont

# ページ設定
st.set_page_config(
page_title="仮選手証システムv2.0",
page_icon=None,
 layout="wide"
)


class JBAVerificationSystem:
"""JBA検証システム（requests+BeautifulSoupベース）"""

    def __init__(self):
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

    def get_current_fiscal_year(self):
 """現在の年度を取得"""
        current_year = datetime.now().year
        current_month = datetime.now().month

        if current_month >= 1:
            return str(current_year)
 else:
            return str(current_year - 1)

    def login(self, email, password):
 """JBAサイトにログイン"""
        try:
            st.info("JBAサイトにログイン中...")

            login_page = self.session.get("https://team-jba.jp/login")
            soup = BeautifulSoup(login_page.content, 'html.parser')

            csrf_token = ""
            csrf_input = soup.find('input', {'name': '_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value', '')

            login_data = {
                '_token': csrf_token,
                'login_id': email,
                'password': password
            }

            login_url = "https://team-jba.jp/login/done"
            login_response = self.session.post(login_url, data=login_data, allow_redirects=True)

            if "ログアウト" in login_response.text:
st.success("ログイン成功")
                self.logged_in = True
                return True
 else:
                st.error("ログインに失敗しました")
                return False

        except Exception as e:
            st.error(f"ログインエラー:{str(e)}")
            return False

    def search_teams_by_university(self, university_name):
 """大学名でチームを検索"""
        try:
            if not self.logged_in:
                st.error("ログインが必要です")
                return []

            current_year = self.get_current_fiscal_year()
            st.info(f"{university_name}の男子チームを検索中...({current_year}年度)")

            # 検索ページにアクセスしてCSRFトークンを取得
            search_url = "https://team-jba.jp/organization/15250600/team/search"
            search_page = self.session.get(search_url)

            if search_page.status_code != 200:
                st.error("検索ページにアクセスできません")
                return []

            soup = BeautifulSoup(search_page.content, 'html.parser')

            # CSRFトークンを取得
            csrf_token = ""
            csrf_input = soup.find('input', {'name': '_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value', '')

            # JSON APIを使用した検索
            search_data = {
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

            form_data = {'request': json.dumps(search_data, ensure_ascii=False)}
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'X-CSRF-Token': csrf_token,
                'X-Requested-With': 'XMLHttpRequest'
            }

            # 検索リクエストを送信（JSON APIとして）
            search_response = self.session.post(
 search_url, 
 data=form_data,
headers=headers
)

            if search_response.status_code != 200:
                st.error("検索リクエストが失敗しました")
                return []

            # JSONレスポンスを解析
            try:
                data = search_response.json()
                teams = []

                if data.get('status') == 'success' and 'records' in data:
                    for team_data in data['records']:
                        # 男子チームのみを対象
                        if team_data.get('team_gender_id') == '男子':
 teams.append({
                                'id': team_data.get('id', ''),
                                'name': team_data.get('team_name', ''),
                                'url': f"https://team-jba.jp/organization/15250600/team/{team_data.get('id', '')}/detail"
                            })

                st.success(f"{university_name}の男子チーム:{len(teams)}件見つかりました")
                return teams

            except Exception as e:
                st.error(f"検索結果の解析に失敗しました:{str(e)}")
                return []

        except Exception as e:
            st.error(f"チーム検索エラー:{str(e)}")
            return []

    def get_team_members(self, team_url):
"""チームのメンバー情報を取得（男子チームのみ）"""
try:
            st.info(f"チームメンバー情報を取得中...")

            # チーム詳細ページにアクセス
            team_page = self.session.get(team_url)

            if team_page.status_code != 200:
                st.error(f"チームページにアクセスできません(Status:{team_page.status_code})")
                return {"team_name": "Error", "members": []}

            soup = BeautifulSoup(team_page.content, 'html.parser')

            # チーム名を取得
            team_name = "UnknownTeam"
            title_element = soup.find('title')
            if title_element:
                team_name = title_element.get_text(strip=True)

            # メンバー情報を抽出（男子チームのメンバーテーブルを特定）
            members = []
            tables = soup.find_all('table')

            # 男子チームのメンバーテーブルを探す（3列のテーブルを探す）
            member_table = None
            for i, table in enumerate(tables):
                rows = table.find_all('tr')
                if len(rows) > 10:  # メンバーテーブルは通常10行以上
                    # 最初の行に「メンバーID/氏名/生年月日」があるかチェック
                    first_row_cells = rows[0].find_all(['td', 'th'])
                    if len(first_row_cells) >= 3:
                        first_cell = first_row_cells[0].get_text(strip=True)
                        second_cell = first_row_cells[1].get_text(strip=True)
                        third_cell = first_row_cells[2].get_text(strip=True)
                        if "メンバーID" in first_cell and "氏名" in second_cell and "生年月日" in third_cell:
                            member_table = table
break

            if member_table:
                rows = member_table.find_all('tr')
                for row in rows[1:]:  # ヘッダー行をスキップ
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:
                        member_id = cells[0].get_text(strip=True)
                        name = cells[1].get_text(strip=True)
                        birth_date = cells[2].get_text(strip=True)

                        # メンバーIDが数字で、名前が空でない場合のみ追加
                        if member_id.isdigit() and name and name != "氏名":
 members.append({
                                "member_id": member_id,
                                "name": name,
                                "birth_date": birth_date
                            })

            return {
                "team_name": team_name,
                "members": members
            }

        except Exception as e:
            st.error(f"メンバー取得エラー:{str(e)}")
            import traceback
st.write(f"**エラー詳細**:{traceback.format_exc()}")
            return {"team_name": "Error", "team_url": team_url, "members": []}

    def normalize_date_format(self, date_str):
"""日付フォーマットを統一（JBAの「2004年5月31日」形式に対応）"""
try:
            if not date_str:
                return ""

            # JBAの「2004年5月31日」形式を処理
            if "年" in date_str and "月" in date_str and "日" in date_str:
                # 「2004年5月31日」→「2004/5/31」に変換
                import re
                match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
                if match:
                    year, month, day = match.groups()
                    return f"{year}/{int(month)}/{int(day)}"

            # 既に統一された形式の場合はそのまま返す
            if "/" in date_str and len(date_str.split("/")) == 3:
                parts = date_str.split("/")
                year = parts[0]
                month = str(int(parts[1]))  # 先頭の0を削除
                day = str(int(parts[2]))  # 先頭の0を削除
                return f"{year}/{month}/{day}"

            return date_str
except:
            return date_str

    def verify_player_info(self, player_name, birth_date, university):
"""個別選手情報の照合（男子チームのみ）"""
try:
            # 大学のチームを検索
            teams = self.search_teams_by_university(university)

            if not teams:
                return {"status": "not_found", "message": f"{university}の男子チームが見つかりませんでした"}

            # 入力された生年月日を正規化
            normalized_input_date = self.normalize_date_format(birth_date)

            # 各チームのメンバー情報を取得して照合
            for team in teams:
                team_data = self.get_team_members(team['url'])
                if team_data and team_data["members"]:
                    for member in team_data["members"]:
                        # 名前の類似度チェック
                        name_similarity = SequenceMatcher(None, player_name, member["name"]).ratio()

                        # 生年月日の照合（正規化された形式で比較）
                        jba_date = self.normalize_date_format(member["birth_date"])
                        birth_match = normalized_input_date == jba_date

if name_similarity > 0.8 and birth_match:
                            return {
                                "status": "match",
                                "jba_data": member,
                                "similarity": name_similarity
}
elif name_similarity > 0.8:  # 名前は一致するが生年月日が異なる場合
                            return {
                                "status": "name_match_birth_mismatch",
                                "jba_data": member,
                                "similarity": name_similarity,
                                "message": f"名前は一致しますが、生年月日が異なります。JBA登録:{member['birth_date']}"
                            }

            return {"status": "not_found", "message": "JBAデータベースに該当する選手が見つかりませんでした"}

        except Exception as e:
            return {"status": "error", "message": f"照合エラー:{str(e)}"}

    def get_university_data(self, university_name):
 """大学のデータを取得"""
        st.info(f"{university_name}のチームを検索中...")

        # チームを検索
        teams = self.search_teams_by_university(university_name)

        if not teams:
            st.warning(f"{university_name}のチームが見つかりませんでした")
            return None

        st.info(f"{university_name}の選手・スタッフ情報を取得中...")

        # 各チームのメンバー情報を取得
        all_members = []
        for i, team in enumerate(teams):
            with st.spinner(f"チーム{i+1}/{len(teams)}を処理中..."):
                team_data = self.get_team_members(team['url'])
                if team_data and team_data["members"]:
 all_members.extend(team_data["members"])
 
        return {
            "university_name": university_name,
            "members": all_members
        }


class DatabaseManager:
 """データベース管理"""
 
    def __init__(self, db_path="player_verification.db"):
        self.db_path = db_path
 self.init_database()
 
    def init_database(self):
 """データベースを初期化"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 大会テーブル
 cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_name TEXT NOT NULL,
            tournament_year TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 0,
            response_accepting BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 選手申請テーブル
 cursor.execute('''
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
        ''')

        # 照合結果テーブル
 cursor.execute('''
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
        ''')

        # 管理者設定テーブル
 cursor.execute('''
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
        ''')
 
 conn.commit()
 conn.close()


class TournamentManagement:
 """大会管理"""
 
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def create_tournament(self, tournament_name, tournament_year):
 """新しい大会を作成"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
 
 cursor.execute('''
        INSERT INTO tournaments (tournament_name, tournament_year, is_active, response_accepting)
        VALUES (?, ?, 1, 1)
        ''', (tournament_name, tournament_year))

        tournament_id = cursor.lastrowid

        # 他の大会を非アクティブにする
        cursor.execute('UPDATE tournaments SET is_active = 0 WHERE id != ?', (tournament_id,))
 
 conn.commit()
 conn.close()
 
        return tournament_id

    def get_active_tournament(self):
 """アクティブな大会を取得"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM tournaments WHERE is_active = 1')
        result = cursor.fetchone()
 
 conn.close()
 
        if result:
            return {
                'id': result[0],
                'tournament_name': result[1],
                'tournament_year': result[2],
                'is_active': bool(result[3]),
                'response_accepting': bool(result[4])
            }
        return None

    def get_all_tournaments(self):
 """すべての大会を取得"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM tournaments ORDER BY created_at DESC')
        results = cursor.fetchall()
 
 conn.close()
 
        tournaments = []
        for result in results:
 tournaments.append({
                'id': result[0],
                'tournament_name': result[1],
                'tournament_year': result[2],
                'is_active': bool(result[3]),
                'response_accepting': bool(result[4])
            })

        return tournaments

    def switch_tournament(self, tournament_id):
 """大会を切り替え"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()

        # すべての大会を非アクティブにする
        cursor.execute('UPDATE tournaments SET is_active = 0')

        # 指定された大会をアクティブにする
        cursor.execute('UPDATE tournaments SET is_active = 1 WHERE id = ?', (tournament_id,))
 
 conn.commit()
 conn.close()
 
    def set_tournament_response_accepting(self, tournament_id, accepting):
 """大会の回答受付を設定"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
 
 cursor.execute('''
        UPDATE tournaments
        SET response_accepting = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''', (accepting, tournament_id))
 
 conn.commit()
 conn.close()


class PrintSystem:
 """印刷システム"""
 
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def _load_font(self, size: int):
        # システムに日本語フォントが無い場合はデフォルトフォント
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
        """指定申請のカードPNGを生成し、ファイルパスを返す"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
 cursor.execute('''
        SELECT pa.player_name, pa.birth_date, pa.university, pa.division, pa.role,
               pa.photo_path, t.tournament_name
        FROM player_applications pa
        LEFT JOIN tournaments t ON pa.tournament_id = t.id
        WHERE pa.id = ?
        ''', (application_id,))
        r = cursor.fetchone()
 conn.close()
        if not r:
            raise RuntimeError("申請が見つかりません")

        player_name, birth_date, university, division, role, photo_path, tournament_name = r

        # mm -> px (300dpi ≒ 11.81 px/mm)
        mm = 11.81
        width = int((110 * mm) - 8)   # 外枠分は描画時で吸収
        height = int((70 * mm) - 8)

        # 背景色（大会種別に応じて）
        # 選手権大会: 緑 (#c2e8c2), 新人戦: ピンク (#ffd1e6), リーグ戦: 黄土色 (#d9b96e)
        bg = (0xC2, 0xE8, 0xC2)
        if tournament_name and "新人戦" in tournament_name:
            bg = (0xFF, 0xD1, 0xE6)
        elif tournament_name and "リーグ戦" in tournament_name:
            bg = (0xD9, 0xB9, 0x6E)

        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # 外枠
        draw.rectangle([(0, 0), (width-1, height-1)], outline=(34, 34, 34), width=4)

        # フォント
        f_title = self._load_font(40)
        f_subtitle = self._load_font(40)
        f_label = self._load_font(36)
        f_text = self._load_font(34)
        f_small = self._load_font(18)

        # 左のテキストエリア幅（カードから写真領域を引く）
        photo_w = int(40 * mm)
        photo_h = int(50 * mm)
        text_pad_x = 24
        text_w = width - photo_w

        # タイトル
        draw.text((text_pad_x, 12), f"{tournament_name}", fill=(34,34,34), font=f_title)
        draw.text((text_pad_x+120, 60), "新人戦", fill=(34,34,34), font=f_subtitle)
        draw.text((text_pad_x, 112), "仮選手証・スタッフ証", fill=(34,34,34), font=f_subtitle)

        # 氏名
        y = 160
        draw.text((text_pad_x, y), "氏名", fill=(34,34,34), font=f_label)
        y += 40
        draw.line([(text_pad_x, y), (text_w-12, y)], fill=(34,34,34), width=2)

        # 大学
        y += 28
        draw.text((text_pad_x+260, y), "大学", fill=(34,34,34), font=f_label)
        y += 40
        draw.line([(text_pad_x, y), (text_w-12, y)], fill=(34,34,34), width=2)

        # 生年月日
        y += 18
        draw.text((text_pad_x, y+12), "生年月日　　　年　　　月　　　日", fill=(34,34,34), font=f_text)

        # 有効
        draw.text((text_pad_x+90, y+60), "※今大会のみ有効", fill=(34,34,34), font=self._load_font(44))
        # 連盟名
        draw.text((text_pad_x+300, y+110), "一般社団法人関東大学バスケットボール連盟", fill=(34,34,34), font=f_small)

        # 写真フレーム
        photo_x = width - photo_w
        photo_y = int(25 * mm)
        draw.rectangle([(photo_x, photo_y), (width-1, photo_y+photo_h)], outline=(0,0,0), width=2)
        # 顔写真描画
        if photo_path and os.path.exists(photo_path):
            try:
                ph = Image.open(photo_path).convert("RGB")
                ph = ph.resize((photo_w-6, photo_h-6), Image.LANCZOS)
                img.paste(ph, (photo_x+3, photo_y+3))
            except Exception:
                pass

        # 実データ（氏名・大学・生年月日）
        # 氏名（線の上に重ねる）
        draw.text((text_pad_x+90, 160), player_name or "", fill=(34,34,34), font=self._load_font(44))
        # 大学
        draw.text((text_pad_x+340, 228), university or "", fill=(34,34,34), font=self._load_font(44))
        # 生年月日
        draw.text((text_pad_x+160, 298), birth_date or "", fill=(34,34,34), font=f_text)

        # 出力
        out_dir = os.path.join("outputs", "cards")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"card_{application_id}.png")
        img.save(out_path, format="PNG")
        return out_path


class AdminDashboard:
 """管理者ダッシュボード"""
 
    def __init__(self, db_manager, tournament_management):
        self.db_manager = db_manager
        self.tournament_management = tournament_management

    def get_system_settings(self):
 """システム設定を取得"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM admin_settings ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()
 
 conn.close()
 
        if result:
            return {
                'jba_email': result[1],
                'jba_password': result[2],
                'notification_email': result[3],
                'auto_verification_enabled': bool(result[4]),
                'verification_threshold': result[5],
                'current_tournament_id': result[6]
            }
        return None

    def save_system_settings(self, settings):
 """システム設定を保存"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
 
 cursor.execute('''
        INSERT OR REPLACE INTO admin_settings
        (jba_email, jba_password, notification_email, auto_verification_enabled,
        verification_threshold, current_tournament_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            settings.get('jba_email', ''),
            settings.get('jba_password', ''),
            settings.get('notification_email', ''),
            settings.get('auto_verification_enabled', True),
            settings.get('verification_threshold', 1.0),
            settings.get('current_tournament_id', None)
        ))
 
 conn.commit()
 conn.close()


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
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["申請一覧", "照会", "大会管理", "カード発行（PNG・ZIP）", "設定"])
        
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
            st.subheader("照会")
            
            # JBA照会機能
            st.write("JBAサイトからチーム・メンバー情報を照会")
            
            with st.form("jba_inquiry"):
                team_id = st.text_input("チームID", placeholder="例: 12345")
                jba_username = st.text_input("JBAユーザー名")
                jba_password = st.text_input("JBAパスワード", type="password")
                
                if st.form_submit_button("照会実行"):
                    if all([team_id, jba_username, jba_password]):
                        try:
                            jba_system = JBAVerificationSystem()
                            if jba_system.login(jba_username, jba_password):
                                members = jba_system.get_team_members(team_id)
                                if members:
                                    st.success(f"{len(members)}名のメンバーが見つかりました")
                                    for member in members:
                                        st.write(f"- {member['name']} ({member['position']})")
 else:
                                    st.warning("メンバーが見つかりませんでした")
 else:
                                st.error("JBA認証に失敗しました")
                        except Exception as e:
                            st.error(f"照会エラー: {str(e)}")
 else:
                        st.error("全ての項目を入力してください")
        
        with tab3:
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
        
        with tab5:
            st.subheader("設定")
            
            # 回答受付設定
            st.write("回答受付設定")
            
            with st.expander("回答受付の開始/停止"):
                conn = sqlite3.connect('player_applications.db')
                cursor = conn.cursor()
                
                # 現在の設定を取得
                cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'accepting_applications'")
                result = cursor.fetchone()
                current_status = result[0] if result else 'true'
                
                accepting = st.radio(
                    "申請受付状況",
                    ["受付中", "停止中"],
                    index=0 if current_status == 'true' else 1
                )
                
                if st.button("設定を更新"):
                    new_status = 'true' if accepting == "受付中" else 'false'
                    cursor.execute("""
                        INSERT OR REPLACE INTO admin_settings (setting_key, setting_value) 
                        VALUES ('accepting_applications', ?)
                    """, (new_status,))
                    conn.commit()
                    conn.close()
                    st.success("設定を更新しました")
 st.rerun()
 else:
                    conn.close()
            
            # JBA認証情報保存
            with st.expander("JBA認証情報"):
                jba_username = st.text_input("JBAユーザー名")
                jba_password = st.text_input("JBAパスワード", type="password")
                
                if st.button("認証情報を保存"):
                    if jba_username and jba_password:
                        conn = sqlite3.connect('player_applications.db')
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT OR REPLACE INTO admin_settings (setting_key, setting_value) 
                            VALUES ('jba_username', ?)
                        """, (jba_username,))
                        cursor.execute("""
                            INSERT OR REPLACE INTO admin_settings (setting_key, setting_value) 
                            VALUES ('jba_password', ?)
                        """, (jba_password,))
                        conn.commit()
                        conn.close()
                        st.success("認証情報を保存しました")
                    else:
                        st.error("ユーザー名とパスワードを入力してください")
    
    else:
        # 申請者画面
        # 申請受付状況をチェック
        conn = sqlite3.connect('player_applications.db')
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'accepting_applications'")
        result = cursor.fetchone()
        accepting_applications = result[0] if result else 'true'
        conn.close()
        
        if accepting_applications != 'true':
            st.error("現在申請受付を停止しています。管理者にお問い合わせください。")
            st.stop()
        
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