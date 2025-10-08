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

    def create_individual_certificate(self, application_id):
        """個別の仮選手証を作成（A4縦サイズ、8枚配置）"""
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()

            cursor.execute('''
            SELECT 
                pa.player_name,
                pa.birth_date,
                pa.university,
                pa.division,
                pa.role,
                pa.application_date,
                vr.match_status,
                vr.jba_name,
                vr.jba_birth_date,
                vr.similarity_score,
                t.tournament_name
            FROM player_applications pa
            LEFT JOIN verification_results vr ON pa.id = vr.application_id
            LEFT JOIN tournaments t ON pa.tournament_id = t.id
            WHERE pa.id = ?
            ''', (application_id,))

            result = cursor.fetchone()
            conn.close()

            if not result:
                st.error("申請情報が見つかりません")
                return None

            # ワード文書を作成
            doc = Document()

            # ページ設定（A4縦）
            section = doc.sections[0]
            section.page_width = Inches(8.27)  # A4幅
            section.page_height = Inches(11.69)  # A4高
            section.left_margin = Inches(0.2)
            section.right_margin = Inches(0.2)
            section.top_margin = Inches(0.2)
            section.bottom_margin = Inches(0.2)

            # 8枚のカードを2列4行で配置（指定された形式）
            tournament_name = result[10] if result[10] else "第65回関東大学バスケットボール新人戦"

            for row in range(4):
                # 2列のカードを作成
                for col in range(2):
                    # カードの枠を作成
                    card_table = doc.add_table(rows=1, cols=1)
                    card_table.style = 'TableGrid'

                    # カードの内容（指定された形式）
                    card_cell = card_table.rows[0].cells[0]
                    card_cell.width = Inches(3.8)

                    # 大会名
                    card_cell.text = f"{tournament_name}\n仮選手証・スタッフ証\n\n"

                    # 大学名
                    card_cell.text += f"大学:{result[2]}\n"

                    # 氏名
                    card_cell.text += f"氏名:{result[0]}\n"

                    # 生年月日
                    card_cell.text += f"生年月日:{result[1]}\n"

                    # 役職
                    card_cell.text += f"役職:{result[4]}\n"

                    # 部
                    card_cell.text += f"部:{result[3]}\n"

                    # 照合結果
                    if result[6]:  # 照合結果がある場合
                        card_cell.text += f"照合結果:{result[6]}\n"
                    else:
                        card_cell.text += "照合結果:未照合\n"

                    # 顔写真エリア
                    card_cell.text += "\n【顔写真】\n"

                    # 有効期限
                    card_cell.text += f"※{tournament_name}のみ有効\n"

                    # 発行機関
                    card_cell.text += "一般社団法人関東大学バスケットボール連盟\n"

                    # 発行日
                    card_cell.text += f"発行日:{datetime.now().strftime('%Y年%m月%d日')}"

            return doc

        except Exception as e:
            st.error(f"個別証明書作成エラー:{str(e)}")
            return None


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


def main():
    """メイン関数"""
    # カスタムCSS（JBAサイト風デザイン）
    st.markdown("""
    <style>
    /* カラーパレット-JBAサイト風 */
    :root {
        --navy: #0f172a; /* 深めのネイビー */
        --blue: #2563eb; /* 主要アクセント */
        --light-blue: #3b82f6;
        --white: #ffffff;
        --dark-gray: #334155;
        --light-gray: #eef2f7;
        --border-gray: #d9dee7;
        --basketball-blue: #2563eb; /* バスケットボールカラー（青） */
    }

    /* グローバル背景 */
    body {
        background: linear-gradient(180deg, #f9fafb 0%, #e2e8f0 100%);
    }

    /* メインコンテナ */
    .main-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 1rem;
    }

    /* ヘッダー */
    .main-header {
        background: var(--navy);
        padding: 3rem 2rem;
        border-radius: 15px;
        margin-bottom: 2rem;
        color: var(--white);
        text-align: center;
        box-shadow: 0 8px 32px rgba(30, 41, 59, 0.3);
    }
    .main-header h1 {
        margin: 0;
        font-size: 3rem;
        font-weight: 800;
        color: var(--white);
    }
    .main-header p {
        margin: 1rem 0 0 0;
        font-size: 1.3rem;
        color: var(--white);
        opacity: 0.9;
    }

    /* カード */
    .card {
        backdrop-filter: blur(6px);
        background: rgba(255, 255, 255, 0.75);
        padding: 2rem;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(30, 41, 59, 0.1);
        margin-bottom: 1.5rem;
        border: 1px solid var(--border-gray);
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
        background: var(--blue);
    }
    .card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(30, 41, 59, 0.15);
    }

    /* ステータスバッジ */
    .status-badge {
        display: inline-block;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .status-pending {
        background: var(--navy);
        color: var(--white);
    }
    .status-match {
        background: var(--blue);
        color: var(--white);
    }
    .status-error {
        background: var(--dark-gray);
        color: var(--white);
    }

    /* サイドバー */
    .sidebar-content {
        background: var(--light-gray);
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        border: 1px solid var(--border-gray);
        box-shadow: 0 2px 8px rgba(30, 41, 59, 0.05);
    }

    /* フォーム */
    .stForm {
        background: var(--white);
        padding: 2rem;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(30, 41, 59, 0.05);
        border: 1px solid var(--border-gray);
    }

    /* ボタン */
    .stButton > button {
        background: var(--blue);
        color: var(--white);
        border: none;
        border-radius: 8px;
        padding: 0.75rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
    }
    .stButton > button:hover {
        background: var(--navy);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
    }

    /* タブ */
    .stTabs[data-baseweb="tab-list"] {
        gap: 0.5rem;
    }
    .stTabs[data-baseweb="tab"] {
        background: rgba(255, 255, 255, 0.7);
        color: var(--dark-gray);
        border-radius: 8px;
        padding: 0.75rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stTabs[aria-selected="true"] {
        background: linear-gradient(90deg, #3b82f6, #2563eb);
        color: var(--white);
    }

    /* 見出しの強調 */
    h1, h2, h3 {
        font-weight: 800;
        color: var(--navy);
        border-left: 6px solid var(--blue);
        padding-left: 10px;
        margin-top: 1rem;
    }

    /* 入力フィールド */
    .stTextInput > div > div > input,
    .stSelectbox > div > div > select,
    .stTextArea > div > div > textarea {
        border-radius: 8px;
        border: 2px solid var(--border-gray);
        color: var(--dark-gray);
        transition: all 0.3s ease;
    }
    .stTextInput > div > div > input:focus,
    .stSelectbox > div > div > select:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--blue);
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
    }

    /* アラート */
    .stAlert {
        border-radius: 10px;
        border: none;
        box-shadow: 0 2px 8px rgba(30, 41, 59, 0.1);
    }

    /* エクスパンダー */
    .streamlit-expanderHeader {
        background: var(--light-gray);
        color: var(--dark-gray);
        border-radius: 8px;
        font-weight: 600;
    }

    /* データフレーム */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(30, 41, 59, 0.05);
    }

    /* テキスト色 */
    .stMarkdown, .stWrite {
        color: var(--dark-gray);
    }

    /* レスポンシブ */
    @media (max-width: 768px) {
        .main-header h1 {
            font-size: 2rem;
        }
        .main-header p {
            font-size: 1rem;
        }
        .card {
            padding: 1.5rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # メインヘッダー
    st.markdown("""
    <div class="main-header">
    <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 1rem;">
    <div style="width: 60px; height: 60px; background: #2563eb; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 1rem;">
    <div style="color: white; font-weight: bold; font-size: 1.2rem;">KCBF</div>
    </div>
    <h1 style="margin: 0;">仮選手証・スタッフ証発行システム</h1>
    </div>
    <p>関東大学バスケットボール連盟公式システム</p>
    </div>
    """, unsafe_allow_html=True)

    # システム初期化
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

    # URLクエリで表示モードを切り替え（?role=admin）
    try:
        query_params = st.query_params  # Streamlit >= 1.31
    except Exception:
        query_params = st.experimental_get_query_params()  # fallback

    role_param = None
    if isinstance(query_params, dict):
        # roleパラメータをチェック
        if "role" in query_params:
            val = query_params.get("role")
            if isinstance(val, list):
                role_param = (val[0] or "").lower()
            else:
                role_param = (val or "").lower()

    admin_mode = (role_param == "admin")

    # 管理者モードの場合は管理者権限を自動付与
    if admin_mode:
        st.session_state.is_admin = True
    else:
        st.session_state.is_admin = False

    if admin_mode:
        # 管理者タブ
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "申請フォーム", "照合結果", "印刷", "統計", "管理者"
        ])
    else:
        # 一般ユーザータブ
        tab1 = st.tabs(["申請フォーム"])[0]

    # 申請フォーム
    with tab1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.header("仮選手証・仮スタッフ証申請フォーム")
        st.markdown("**関東大学バスケットボール連盟**の公式申請システムです。")
        st.markdown('</div>', unsafe_allow_html=True)

        # アクティブな大会情報を表示
        active_tournament = st.session_state.tournament_management.get_active_tournament()

        if active_tournament:
            st.info(f"**大会名**: {active_tournament['tournament_name']} ({active_tournament['tournament_year']}年度)")

            if active_tournament['response_accepting']:
                st.success("回答受付中")
            else:
                st.error("回答受付停止中")
        else:
            st.warning("アクティブな大会が設定されていません（管理者は「管理者」タブから大会を作成してください）")

        # 申請フォーム（アクティブ大会かつ受付中のときのみ表示）
        if active_tournament and active_tournament.get('response_accepting'):
            st.subheader("基本情報")
            with st.form("basic_info_form"):
                col1, col2 = st.columns(2)

                with col1:
                    division = st.selectbox("部（2025年度）", ["1部", "2部", "3部", "4部", "5部"])
                    university = st.text_input("大学名", placeholder="例:白鴎大学")

                with col2:
                    is_newcomer = st.radio("新入生ですか？", ["はい", "いいえ"], horizontal=True)
                    basic_submitted = st.form_submit_button("基本情報を設定", type="primary")

                if basic_submitted and university:
                    st.session_state.basic_info = {
                        'division': division,
                        'university': university,
                        'is_newcomer': is_newcomer == "はい"
                    }
                    st.success("基本情報を設定しました")

            # 一括入力方式に変更（セクション増減＋一括送信）
            if 'basic_info' in st.session_state:
                st.subheader("一括入力（複数人）")
                st.info(f"**{st.session_state.basic_info['university']}** - {st.session_state.basic_info['division']} - **{active_tournament['tournament_name']}**")

                # セクション数の管理
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

                st.markdown("### 申請者情報（まとめて入力）")
                with st.form("bulk_applicants_form", clear_on_submit=False):
                    total_sections = st.session_state.section_count
                    for i in range(total_sections):
                        st.markdown(f"#### セクション{i+1}")
                        c1, c2 = st.columns(2)
                        with c1:
                            role_i = st.selectbox("役職", ["選手", "スタッフ"], key=f"role_{i}")
                            name_i = st.text_input("氏名（漢字）", key=f"name_{i}")
                            birth_i = st.date_input("生年月日（年・月・日）", value=datetime(2000, 1, 1), key=f"birth_{i}")
                        with c2:
                            photo_i = st.file_uploader("顔写真アップロード", type=['jpg', 'jpeg', 'png'], key=f"photo_{i}")
                            if st.session_state.get(f"role_{i}") == "選手":
                                jba_i = st.file_uploader("JBA登録用紙（PDF）", type=['pdf'], key=f"jba_{i}")
                                staff_i = None
                            else:
                                jba_i = None
                                staff_i = st.file_uploader("スタッフ登録用紙", type=['pdf'], key=f"staff_{i}")
                            remarks_i = st.text_area("備考欄", height=80, key=f"remarks_{i}")
                        st.divider()

                    bulk_submit = st.form_submit_button("一括申請送信", type="primary")

                    if bulk_submit:
                        conn = sqlite3.connect(st.session_state.db_manager.db_path)
                        cursor = conn.cursor()
                        application_ids = []
                        added_count = 0
                        skipped = 0
                        for i in range(st.session_state.section_count):
                            name_val = st.session_state.get(f"name_{i}")
                            birth_val = st.session_state.get(f"birth_{i}")
                            role_val = st.session_state.get(f"role_{i}")
                            remarks_val = st.session_state.get(f"remarks_{i}") or ""

                            # 必須チェック（名前＋生年月日）
                            if not name_val or not birth_val:
                                skipped += 1
                                continue

                            cursor.execute('''
                            INSERT INTO player_applications
                            (tournament_id, player_name, birth_date, university, division, role, remarks, photo_path, jba_file_path, staff_file_path, verification_result, jba_match_data)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                active_tournament['id'],
                                name_val,
                                birth_val.strftime('%Y/%m/%d'),
                                st.session_state.basic_info['university'],
                                st.session_state.basic_info['division'],
                                role_val,
                                remarks_val,
                                None,  # photo_path
                                None,  # jba_path
                                None,  # staff_path
                                "pending",
                                ""
                            ))
                            application_ids.append(cursor.lastrowid)
                            added_count += 1

                        conn.commit()
                        conn.close()

                        if added_count:
                            st.success(f"{added_count}名の申請が送信されました")
                            st.info(f"申請ID: {','.join(map(str, application_ids))}")
                        if skipped:
                            st.warning(f"入力不足のため{skipped}件をスキップしました（氏名と生年月日が必須）")
        else:
            # フォーム非表示時の案内
            if active_tournament is None:
                st.info("管理者が大会を作成すると申請フォームが表示されます。")
            elif not active_tournament.get('response_accepting'):
                st.info("現在、この大会の回答受付は停止中です。")

    # 照合結果
    if admin_mode:
        with tab2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.header("申請照合・管理")
            st.markdown("**管理者専用**: 申請された情報をJBAデータベースと照合し、データを管理します。")
            st.markdown('</div>', unsafe_allow_html=True)

            # JBAログイン情報
            with st.expander("JBAログイン設定"):
                jba_email = st.text_input("JBAメールアドレス", type="default")
                jba_password = st.text_input("JBAパスワード", type="password")

                if st.button("JBAにログイン"):
                    if jba_email and jba_password:
                        if st.session_state.jba_system.login(jba_email, jba_password):
                            st.success("ログイン成功")
                        else:
                            st.error("ログイン失敗")
                    else:
                        st.error("ログイン情報を入力してください")

            # チームURL直接テスト
            st.subheader("チームURL直接テスト")
            team_url = st.text_input("チームURL", placeholder="例:https://team-jba.jp/organization/15250600/team/12345")

            if st.button("チーム情報取得テスト") and team_url:
                if not st.session_state.jba_system.logged_in:
                    st.error("先にJBAにログインしてください")
                else:
                    st.info("チーム情報を取得中...")
                    team_data = st.session_state.jba_system.get_team_members(team_url)

                    if team_data and team_data["members"]:
                        st.success(f"チーム情報を取得しました")
                        st.write(f"**チーム名**: {team_data['team_name']}")
                        st.write(f"**メンバー数**: {len(team_data['members'])}人")

                        # メンバー一覧を表示
                        if team_data['members']:
                            df = pd.DataFrame(team_data['members'])
                            st.dataframe(df)
                    else:
                        st.error("チーム情報を取得できませんでした")

            # 申請一覧と照合
            st.subheader("申請一覧と照合")
            active_tournament = st.session_state.tournament_management.get_active_tournament()

            if active_tournament:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cursor = conn.cursor()

                cursor.execute('''
                SELECT id, player_name, birth_date, university, division, role, application_date, verification_result
                FROM player_applications
                WHERE tournament_id = ?
                ORDER BY application_date DESC
                ''', (active_tournament['id'],))

                applications = cursor.fetchall()
                conn.close()

                if applications:
                    st.write(f"**{active_tournament['tournament_name']}**の申請一覧")

                    for app in applications:
                        app_id, player_name, birth_date, university, division, role, app_date, verification_status = app

                        # ステータスバッジの色を決定
                        if verification_status == "pending":
                            status_class = "status-pending"
                            status_text = "待機中"
                        elif verification_status == "match":
                            status_class = "status-match"
                            status_text = "一致"
                        else:
                            status_class = "status-error"
                            status_text = "不一致"

                        with st.expander(f"申請ID: {app_id} - {player_name} ({university}) - {status_text}"):
                            col1, col2 = st.columns(2)

                            with col1:
                                st.markdown('<div class="card">', unsafe_allow_html=True)
                                st.write(f"**氏名**: {player_name}")
                                st.write(f"**生年月日**: {birth_date}")
                                st.write(f"**大学**: {university}")
                                st.write(f"**部**: {division}")
                                st.write(f"**役職**: {role}")
                                st.write(f"**申請日**: {app_date}")
                                st.markdown('</div>', unsafe_allow_html=True)

                            with col2:
                                st.markdown('<div class="card">', unsafe_allow_html=True)
                                # 照合ボタン
                                if st.button(f"照合実行", key=f"verify_{app_id}", type="primary"):
                                    if not st.session_state.jba_system.logged_in:
                                        st.error("先にJBAにログインしてください")
                                    else:
                                        st.info("JBAデータベースと照合中...")
                                        verification_result = st.session_state.jba_system.verify_player_info(
                                            player_name, birth_date, university
                                        )

                                        # 照合結果をデータベースに保存
                                        conn = sqlite3.connect(st.session_state.db_manager.db_path)
                                        cursor = conn.cursor()

                                        # 既存の照合結果を更新
                                        cursor.execute('''
                                        UPDATE player_applications
                                        SET verification_result = ?, jba_match_data = ?
                                        WHERE id = ?
                                        ''', (
                                            verification_result["status"],
                                            str(verification_result.get("jba_data", {})),
                                            app_id
                                        ))

                                        # 照合結果テーブルにも保存
                                        cursor.execute('''
                                        INSERT OR REPLACE INTO verification_results
                                        (application_id, match_status, jba_name, jba_birth_date, similarity_score)
                                        VALUES (?, ?, ?, ?, ?)
                                        ''', (
                                            app_id,
                                            verification_result["status"],
                                            verification_result.get("jba_data", {}).get("name", ""),
                                            verification_result.get("jba_data", {}).get("birth_date", ""),
                                            verification_result.get("similarity", 0.0)
                                        ))

                                        conn.commit()
                                        conn.close()

                                        st.rerun()

                                # 照合結果の表示
                                if verification_status != "pending":
                                    if verification_status == "match":
                                        st.success("JBAデータベースと完全一致")
                                    elif verification_status == "name_match_birth_mismatch":
                                        st.warning("名前は一致、生年月日が異なる")
                                    elif verification_status == "not_found":
                                        st.error("JBAデータベースに該当なし")
                                    else:
                                        st.info(f"照合結果: {verification_status}")

                                st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.info("申請がありません")
            else:
                st.info("アクティブな大会が設定されていません")

        # 印刷
        with tab3:
            st.header("印刷")

            # 申請一覧
            active_tournament = st.session_state.tournament_management.get_active_tournament()

            if active_tournament:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cursor = conn.cursor()

                cursor.execute('''
                SELECT id, player_name, university, role, application_date
                FROM player_applications
                WHERE tournament_id = ?
                ORDER BY application_date DESC
                ''', (active_tournament['id'],))

                applications = cursor.fetchall()
                conn.close()

                if applications:
                    st.write(f"**申請一覧** ({len(applications)}件)")

                    for app in applications:
                        col1, col2, col3 = st.columns([3, 1, 1])

                        with col1:
                            st.write(f"**{app[1]}** ({app[2]}) - {app[3]}")
                            st.write(f"申請日: {app[4]}")

                        with col2:
                            if st.button(f"印刷", key=f"print_{app[0]}"):
                                try:
                                    doc = st.session_state.print_system.create_individual_certificate(app[0])

                                    if doc:
                                        # ファイル名を生成
                                        filename = f"仮選手証_{app[1]}_{app[0]}.docx"
                                        doc.save(filename)
                                        st.success(f"{filename}を作成しました")
                                except Exception as e:
                                    st.error(f"印刷エラー:{str(e)}")

                        with col3:
                            if st.button(f"詳細", key=f"detail_{app[0]}"):
                                st.session_state.selected_application = app[0]
                                st.rerun()

                        st.divider()
                else:
                    st.info("申請がありません")
            else:
                st.warning("アクティブな大会が設定されていません")

        # 統計
        with tab4:
            st.header("統計情報")

            # アクティブな大会の統計
            active_tournament = st.session_state.tournament_management.get_active_tournament()
            if active_tournament:
                conn = sqlite3.connect(st.session_state.db_manager.db_path)
                cursor = conn.cursor()

                # 申請数
                cursor.execute('SELECT COUNT(*) FROM player_applications WHERE tournament_id = ?', (active_tournament['id'],))
                total_applications = cursor.fetchone()[0]

                # 照合結果
                cursor.execute('''
                SELECT
                COUNT(CASE WHEN vr.match_status = 'マッチ' THEN 1 END) as matched,
                COUNT(CASE WHEN vr.match_status = '未マッチ' THEN 1 END) as unmatched,
                COUNT(CASE WHEN vr.match_status = '複数候補' THEN 1 END) as multiple
                FROM player_applications pa
                LEFT JOIN verification_results vr ON pa.id = vr.application_id
                WHERE pa.tournament_id = ?
                ''', (active_tournament['id'],))

                result = cursor.fetchone()
                matched = result[0] if result[0] else 0
                unmatched = result[1] if result[1] else 0
                multiple = result[2] if result[2] else 0

                conn.close()

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("総申請数", total_applications)
                with col2:
                    st.metric("マッチ", matched)
                with col3:
                    st.metric("未マッチ", unmatched)
                with col4:
                    st.metric("複数候補", multiple)
            else:
                st.warning("アクティブな大会が設定されていません")

        # 管理者機能
        with tab5:
            st.header("管理者ダッシュボード")

            # 大会管理
            st.subheader("大会管理")

            # 現在のアクティブな大会
            active_tournament = st.session_state.tournament_management.get_active_tournament()

            if active_tournament:
                st.info(f"**現在のアクティブな大会**: {active_tournament['tournament_name']} ({active_tournament['tournament_year']}年度)")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("回答受付制御"):
                        new_status = not active_tournament['response_accepting']
                        st.session_state.tournament_management.set_tournament_response_accepting(
                            active_tournament['id'], new_status
                        )
                        st.success(f"回答受付を{'有効' if new_status else '無効'}にしました")
                        st.rerun()

                with col2:
                    st.write(f"**回答受付**: {'有効' if active_tournament['response_accepting'] else '無効'}")
            else:
                st.warning("アクティブな大会が設定されていません")

            # 新しい大会を作成
            st.subheader("新しい大会を作成")

            with st.form("create_tournament_form"):
                col1, col2 = st.columns(2)

                with col1:
                    tournament_type = st.selectbox("大会種別", ["選手権大会", "新人戦", "リーグ戦"])
                    tournament_number = st.number_input("第○回", min_value=1, max_value=999, value=101)

                with col2:
                    new_tournament_year = st.text_input("年度", placeholder="例:2025")

                # 自動生成された大会名を表示
                if tournament_type and tournament_number:
                    auto_generated_name = f"第{tournament_number}回関東大学バスケットボール{tournament_type}"
                    st.info(f"**生成される大会名**: {auto_generated_name}")

                if st.form_submit_button("大会を作成"):
                    if tournament_type and tournament_number and new_tournament_year:
                        tournament_name = f"第{tournament_number}回関東大学バスケットボール{tournament_type}"
                        tournament_id = st.session_state.tournament_management.create_tournament(
                            tournament_name, new_tournament_year
                        )

                        st.success(f"大会を作成しました（ID: {tournament_id}）")
                        st.success(f"**大会名**: {tournament_name}")
                        st.rerun()
                    else:
                        st.error("大会種別、回数、年度を入力してください")

            # 大会を切り替え
            st.subheader("大会を切り替え")

            tournaments = st.session_state.tournament_management.get_all_tournaments()

            if tournaments:
                tournament_options = {f"{t['tournament_name']} ({t['tournament_year']}年度)": t['id'] for t in tournaments}
                selected_tournament = st.selectbox("大会を選択", list(tournament_options.keys()))

                if st.button("大会を切り替え"):
                    tournament_id = tournament_options[selected_tournament]
                    st.session_state.tournament_management.switch_tournament(tournament_id)
                    st.success("大会を切り替えました")
                    st.rerun()
            else:
                st.info("大会がありません")

            # システム設定
            st.subheader("システム設定")

            settings = st.session_state.admin_dashboard.get_system_settings()

            if settings:
                with st.form("system_settings_form"):
                    st.text_input("JBAメールアドレス", value=settings.get('jba_email', ''), key="admin_jba_email")
                    st.text_input("JBAパスワード", value=settings.get('jba_password', ''), type="password", key="admin_jba_password")
                    st.text_input("通知メールアドレス", value=settings.get('notification_email', ''), key="admin_notification_email")

                    auto_verification = st.checkbox("自動照合を有効にする", value=settings.get('auto_verification_enabled', True))
                    verification_threshold = st.slider("照合閾値", 0.1, 1.0, settings.get('verification_threshold', 1.0), 0.05)

                    if st.form_submit_button("設定を保存"):
                        new_settings = {
                            'jba_email': st.session_state.admin_jba_email,
                            'jba_password': st.session_state.admin_jba_password,
                            'notification_email': st.session_state.admin_notification_email,
                            'auto_verification_enabled': auto_verification,
                            'verification_threshold': verification_threshold,
                            'current_tournament_id': active_tournament['id'] if active_tournament else None
                        }

                        st.session_state.admin_dashboard.save_system_settings(new_settings)
                        st.success("設定を保存しました")


if __name__ == "__main__":
    main()