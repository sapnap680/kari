

#!/usr/bin/env python3
"""
仮選手証システム v2.0
- Playwright依存を排除
- requests + BeautifulSoupベース
- 既存の管理者機能を統合
"""

import streamlit as st
import pandas as pd
import json
import requests
import sys

# 依存関係チェック（bs4 不足時に明示して停止）
_BS4_VERSION = None
try:
    from bs4 import BeautifulSoup  # type: ignore
    import bs4 as _bs4  # type: ignore
    _BS4_VERSION = getattr(_bs4, "__version__", "unknown")
except Exception:
    st.error(
        "依存パッケージ 'beautifulsoup4' が見つかりません。requirements.txt がデプロイで読み込まれているか確認してください。"
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
    page_title="🏀 仮選手証システム v2.0",
    page_icon="🏀",
    layout="wide"
)

class JBAVerificationSystem:
    """JBA検証システム（requests + BeautifulSoupベース）"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ja,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
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
            st.info("🔐 JBAサイトにログイン中...")
            
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
                st.success("✅ ログイン成功")
                self.logged_in = True
                return True
            else:
                st.error("❌ ログインに失敗しました")
                return False
                
        except Exception as e:
            st.error(f"❌ ログインエラー: {str(e)}")
            return False
    
    def search_teams_by_university(self, university_name):
        """大学名でチームを検索"""
        try:
            if not self.logged_in:
                st.error("❌ ログインが必要です")
                return []
            
            current_year = self.get_current_fiscal_year()
            st.info(f"🔍 {university_name}の男子チームを検索中... ({current_year}年度)")
            
            # 検索ページにアクセスしてCSRFトークンを取得
            search_url = "https://team-jba.jp/organization/15250600/team/search"
            search_page = self.session.get(search_url)
            
            if search_page.status_code != 200:
                st.error("❌ 検索ページにアクセスできません")
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
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
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
                st.error("❌ 検索リクエストが失敗しました")
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
                
                st.success(f"✅ {university_name}の男子チーム: {len(teams)}件見つかりました")
                return teams
                
            except Exception as e:
                st.error(f"❌ 検索結果の解析に失敗しました: {str(e)}")
                return []
            
        except Exception as e:
            st.error(f"❌ チーム検索エラー: {str(e)}")
            return []
    
    def get_team_members(self, team_url):
        """チームのメンバー情報を取得（男子チームのみ）"""
        try:
            st.info(f"📊 チームメンバー情報を取得中...")
            
            # チーム詳細ページにアクセス
            team_page = self.session.get(team_url)
            
            if team_page.status_code != 200:
                st.error(f"❌ チームページにアクセスできません (Status: {team_page.status_code})")
                return {"team_name": "Error", "members": []}
            
            soup = BeautifulSoup(team_page.content, 'html.parser')
            
            # チーム名を取得
            team_name = "Unknown Team"
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
                    # 最初の行に「メンバーID / 氏名 / 生年月日」があるかチェック
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
            st.error(f"❌ メンバー取得エラー: {str(e)}")
            import traceback
            st.write(f"**エラー詳細**: {traceback.format_exc()}")
            return {"team_name": "Error", "team_url": team_url, "members": []}
    
    def verify_player_info(self, player_name, birth_date, university):
        """個別選手情報の照合（男子チームのみ）"""
        try:
            # 大学のチームを検索
            teams = self.search_teams_by_university(university)
            
            if not teams:
                return {"status": "not_found", "message": f"{university}の男子チームが見つかりませんでした"}
            
            # 各チームのメンバー情報を取得して照合
            for team in teams:
                team_data = self.get_team_members(team['url'])
                if team_data and team_data["members"]:
                    for member in team_data["members"]:
                        # 名前の類似度チェック
                        name_similarity = SequenceMatcher(None, player_name, member["name"]).ratio()
                        
                        # 生年月日の照合
                        birth_match = birth_date == member["birth_date"]
                        
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
                                "message": f"名前は一致しますが、生年月日が異なります。JBA登録: {member['birth_date']}"
                            }
            
            return {"status": "not_found", "message": "JBAデータベースに該当する選手が見つかりませんでした"}
            
        except Exception as e:
            return {"status": "error", "message": f"照合エラー: {str(e)}"}
    
    def get_university_data(self, university_name):
        """大学のデータを取得"""
        st.info(f"🔍 {university_name}のチームを検索中...")
        
        # チームを検索
        teams = self.search_teams_by_university(university_name)
        
        if not teams:
            st.warning(f"⚠️ {university_name}のチームが見つかりませんでした")
            return None
        
        st.info(f"📊 {university_name}の選手・スタッフ情報を取得中...")
        
        # 各チームのメンバー情報を取得
        all_members = []
        for i, team in enumerate(teams):
            with st.spinner(f"チーム {i+1}/{len(teams)} を処理中..."):
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
                    card_table.style = 'Table Grid'
                    
                    # カードの内容（指定された形式）
                    card_cell = card_table.rows[0].cells[0]
                    card_cell.width = Inches(3.8)
                    
                    # 大会名
                    card_cell.text = f"{tournament_name}\n仮選手証・スタッフ証\n\n"
                    
                    # 大学名
                    card_cell.text += f"大学: {result[2]}\n"
                    
                    # 氏名
                    card_cell.text += f"氏名: {result[0]}\n"
            
            # 生年月日
                    card_cell.text += f"生年月日: {result[1]}\n"
            
            # 役職
                    card_cell.text += f"役職: {result[4]}\n"
            
            # 部
            card_cell.text += f"部: {result[3]}\n"
            
            # 照合結果
            if result[6]:  # 照合結果がある場合
                card_cell.text += f"照合結果: {result[6]}\n"
            else:
                card_cell.text += "照合結果: 未照合\n"
            
            # 顔写真エリア
            card_cell.text += "\n【顔写真】\n"
            
            # 有効期限
            card_cell.text += f"※ {tournament_name}のみ有効\n"
            
            # 発行機関
            card_cell.text += "一般社団法人関東大学バスケットボール連盟\n"
            
            # 発行日
            card_cell.text += f"発行日: {datetime.now().strftime('%Y年%m月%d日')}"
            
            return doc
            
        except Exception as e:
            st.error(f"個別証明書作成エラー: {str(e)}")
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
    st.title("🏀 仮選手証システム v2.0")
    st.markdown("**Playwright不要・requests + BeautifulSoupベース**")
    # 環境情報（サイドバー）
    with st.sidebar.expander("🧰 環境情報", expanded=False):
        st.write(f"bs4: {_BS4_VERSION}")
        st.write(f"requests: {requests.__version__}")
        st.write(f"python: {sys.version.split()[0]}")
    
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
    
    # 管理者ログイン（パスワード: 0503）
    with st.sidebar.expander("🔐 管理者ログイン", expanded=False):
        if 'is_admin' not in st.session_state:
            st.session_state.is_admin = False
        if not st.session_state.is_admin:
            admin_password_input = st.text_input("パスワード", type="password", key="admin_password_input")
            if st.button("ログイン"):
                if admin_password_input == "0503":
                    st.session_state.is_admin = True
                    st.success("ログインしました")
                else:
                    st.error("パスワードが違います")
        else:
            st.success("管理者としてログイン中")
            if st.button("ログアウト"):
                st.session_state.is_admin = False
                st.session_state.pop("admin_password_input", None)

    admin_mode = st.session_state.is_admin
    
    if admin_mode:
        # 管理者タブ
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📝 申請フォーム", "🔍 照合結果", "🖨️ 印刷", "📧 通知", "📊 統計", "🎛️ 管理者"
        ])
    else:
        # 一般ユーザータブ
        tab1, tab2, tab3, tab4 = st.tabs([
            "📝 申請フォーム", "🔍 照合結果", "🖨️ 印刷", "📧 通知"
        ])
    
    # 申請フォーム
    with tab1:
        st.header("📝 仮選手証・仮スタッフ証申請フォーム")
        
        # アクティブな大会情報を表示（フォームはガードし、アプリ全体は止めない）
        active_tournament = st.session_state.tournament_management.get_active_tournament()
        if active_tournament:
            st.info(f"**大会名**: {active_tournament['tournament_name']} ({active_tournament['tournament_year']}年度)")
            if active_tournament['response_accepting']:
                st.success("✅ 回答受付中")
            else:
                st.error("❌ 回答受付停止中")
        else:
            st.warning("⚠️ アクティブな大会が設定されていません（管理者は“🎛️ 管理者”タブから大会を作成してください）")
        
        # 申請フォーム（アクティブ大会かつ受付中のときのみ表示）
        if active_tournament and active_tournament.get('response_accepting'):
            st.subheader("🏫 基本情報")
            with st.form("basic_info_form"):
                col1, col2 = st.columns(2)
            
            with col1:
                division = st.selectbox("部（2025年度）", ["1部", "2部", "3部", "4部", "5部"])
                university = st.text_input("大学名", placeholder="例: 白鴎大学")
                
                with col2:
                    is_newcomer = st.radio("新入生ですか？", ["はい", "いいえ"], horizontal=True)
                
                basic_submitted = st.form_submit_button("📝 基本情報を設定", type="primary")
            
            if basic_submitted and university:
                st.session_state.basic_info = {
                    'division': division,
                    'university': university,
                    'is_newcomer': is_newcomer == "はい"
                }
                st.success("✅ 基本情報を設定しました")
            
            # 選手・スタッフ情報入力
            if 'basic_info' in st.session_state:
                st.subheader("👥 選手・スタッフ情報")
                st.info(f"**{st.session_state.basic_info['university']}** - {st.session_state.basic_info['division']} - **{active_tournament['tournament_name']}**")
                
                with st.form("player_application_form"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        role = st.selectbox("役職", ["選手", "スタッフ"])
                        player_name = st.text_input("氏名（漢字）", placeholder="例: 田中太郎")
                        birth_date = st.date_input("生年月日（年・月・日）")
                    
                    with col2:
                        photo_file = st.file_uploader("顔写真アップロード", type=['jpg', 'jpeg', 'png'])
                        
                        # 役職に応じてファイルアップローダーを表示
                        if role == "選手":
                            jba_file = st.file_uploader("JBA登録用紙（PDF）", type=['pdf'])
                            staff_file = None
                        else:  # スタッフの場合
                            jba_file = None
                            staff_file = st.file_uploader("スタッフ登録用紙", type=['pdf'])
                        
                        remarks = st.text_area("備考欄", height=100)
                    
                    submitted = st.form_submit_button("📤 申請を送信", type="primary")
                    
                    if submitted:
                        if not all([player_name, birth_date]):
                            st.error("❌ 必須項目を入力してください")
                        else:
                            # JBAデータベースとの照合
                            st.info("🔍 JBAデータベースと照合中...")
                            verification_result = st.session_state.jba_system.verify_player_info(
                                player_name,
                                birth_date.strftime('%Y/%m/%d'),
                                st.session_state.basic_info['university']
                            )
                        
                            # 照合結果の表示
                            if verification_result["status"] == "match":
                                st.success("✅ JBAデータベースと完全一致しました")
                            elif verification_result["status"] == "name_match_birth_mismatch":
                                st.warning(f"⚠️ {verification_result['message']}")
                            elif verification_result["status"] == "birth_match_name_mismatch":
                                st.warning(f"⚠️ {verification_result['message']}")
                            elif verification_result["status"] == "not_found":
                                st.error(f"❌ {verification_result['message']}")
                            else:
                                st.error(f"❌ {verification_result['message']}")
                            
                    # 申請データを保存
                    player_data = {
                        'player_name': player_name,
                        'birth_date': birth_date.strftime('%Y/%m/%d'),
                                'university': st.session_state.basic_info['university'],
                                'division': st.session_state.basic_info['division'],
                        'role': role,
                                'is_newcomer': st.session_state.basic_info['is_newcomer'],
                        'remarks': remarks,
                        'photo_path': f"photos/{player_name}_{birth_date}.jpg" if photo_file else None,
                        'jba_file_path': f"jba_files/{player_name}_{birth_date}.pdf" if jba_file else None,
                                'staff_file_path': f"staff_files/{player_name}_{birth_date}.pdf" if staff_file else None,
                                'verification_result': verification_result["status"],
                                'jba_match_data': str(verification_result.get("jba_data", {}))
                    }
                    
                    # データベースに保存
                    conn = sqlite3.connect(st.session_state.db_manager.db_path)
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        INSERT INTO player_applications 
                                    (tournament_id, player_name, birth_date, university, division, role, remarks, photo_path, jba_file_path, staff_file_path, verification_result, jba_match_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        active_tournament['id'],
                        player_data['player_name'],
                        player_data['birth_date'],
                        player_data['university'],
                        player_data['division'],
                        player_data['role'],
                        player_data['remarks'],
                        player_data['photo_path'],
                        player_data['jba_file_path'],
                        player_data['staff_file_path'],
                        player_data['verification_result'],
                        player_data['jba_match_data']
                    ))
                    
                    application_id = cursor.lastrowid
                    
                    # 照合結果も保存
                    cursor.execute('''
                                INSERT INTO verification_results 
                                (application_id, match_status, jba_name, jba_birth_date, similarity_score)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (
                                application_id,
                                verification_result["status"],
                                verification_result.get("jba_data", {}).get("name", ""),
                                verification_result.get("jba_data", {}).get("birth_date", ""),
                                verification_result.get("similarity", 0.0)
                            ))
                            
                    conn.commit()
                    conn.close()
                    
                    st.success(f"✅ 申請が送信されました（申請ID: {application_id}）")
                    st.info("🔄 次の選手・スタッフの情報を入力してください")
        else:
            # フォーム非表示時の案内
            if active_tournament is None:
                st.info("管理者が大会を作成すると申請フォームが表示されます。")
            elif not active_tournament.get('response_accepting'):
                st.info("現在、この大会の回答受付は停止中です。")
    
    # 照合結果
    with tab2:
        st.header("🔍 照合結果")
        
        # JBAログイン情報
        with st.expander("🔐 JBAログイン設定"):
            jba_email = st.text_input("JBAメールアドレス", type="default")
            jba_password = st.text_input("JBAパスワード", type="password")
            
            if st.button("🔐 JBAにログイン"):
                if jba_email and jba_password:
                    if st.session_state.jba_system.login(jba_email, jba_password):
                        st.success("✅ ログイン成功")
                    else:
                        st.error("❌ ログイン失敗")
                else:
                    st.error("❌ ログイン情報を入力してください")
        
        # チームURL直接テスト
        st.subheader("🧪 チームURL直接テスト")
        team_url = st.text_input("チームURL", placeholder="例: https://team-jba.jp/organization/15250600/team/12345")
        
        if st.button("🔍 チーム情報取得テスト") and team_url:
            if not st.session_state.jba_system.logged_in:
                st.error("❌ 先にJBAにログインしてください")
            else:
                st.info("チーム情報を取得中...")
                team_data = st.session_state.jba_system.get_team_members(team_url)
                
                if team_data and team_data["members"]:
                    st.success(f"✅ チーム情報を取得しました")
                    st.write(f"**チーム名**: {team_data['team_name']}")
                    st.write(f"**メンバー数**: {len(team_data['members'])}人")
                    
                    # メンバー一覧を表示
                    if team_data['members']:
                        df = pd.DataFrame(team_data['members'])
                        st.dataframe(df)
                else:
                    st.error("❌ チーム情報を取得できませんでした")
        
        # 大学名で検索
        st.subheader("🏫 大学名で検索")
        university_name = st.text_input("大学名", placeholder="例: 白鴎大学")
        
        if st.button("🔍 大学検索実行") and university_name:
            if not st.session_state.jba_system.logged_in:
                st.error("❌ 先にJBAにログインしてください")
            else:
                # 大学データを取得
                university_data = st.session_state.jba_system.get_university_data(university_name)
                
                if university_data:
                    st.success(f"✅ {university_name}のデータを取得しました")
                    st.write(f"**メンバー数**: {len(university_data['members'])}人")
                    
                    # メンバー一覧を表示
                    if university_data['members']:
                        df = pd.DataFrame(university_data['members'])
                        st.dataframe(df)
                else:
                    st.error(f"❌ {university_name}のデータを取得できませんでした")
    
    
    # 印刷
    with tab3:
        st.header("🖨️ 印刷")
        
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
                        if st.button(f"🖨️ 印刷", key=f"print_{app[0]}"):
                            doc = st.session_state.print_system.create_individual_certificate(app[0])
                            if doc:
                                # ファイル名を生成
                                filename = f"仮選手証_{app[1]}_{app[0]}.docx"
                                doc.save(filename)
                                st.success(f"✅ {filename} を作成しました")
                    
                    
                    st.divider()
            else:
                st.info("申請がありません")
        else:
            st.warning("⚠️ アクティブな大会が設定されていません")
    
    # 通知
    with tab4:
        st.header("📧 通知設定")
        st.info("通知機能は開発中です")
    
    # 統計（管理者のみ）
    if admin_mode:
        with tab5:
            st.header("📊 統計情報")
            
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
                st.warning("⚠️ アクティブな大会が設定されていません")
    
    # 管理者機能
    if admin_mode:
        with tab6:
            st.header("🎛️ 管理者ダッシュボード")
            
            # 大会管理
            st.subheader("🏆 大会管理")
            
            # 現在のアクティブな大会
            active_tournament = st.session_state.tournament_management.get_active_tournament()
            if active_tournament:
                st.info(f"**現在のアクティブな大会**: {active_tournament['tournament_name']} ({active_tournament['tournament_year']}年度)")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 回答受付制御"):
                        new_status = not active_tournament['response_accepting']
                        st.session_state.tournament_management.set_tournament_response_accepting(
                            active_tournament['id'], new_status
                        )
                        st.success(f"✅ 回答受付を{'有効' if new_status else '無効'}にしました")
                        st.rerun()
                
                with col2:
                    st.write(f"**回答受付**: {'有効' if active_tournament['response_accepting'] else '無効'}")
            else:
                st.warning("⚠️ アクティブな大会が設定されていません")
            
            # 新しい大会を作成
            st.subheader("➕ 新しい大会を作成")
            with st.form("create_tournament_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    tournament_type = st.selectbox("大会種別", ["選手権大会", "新人戦", "リーグ戦"])
                    tournament_number = st.number_input("第○回", min_value=1, max_value=999, value=101)
                
                with col2:
                    new_tournament_year = st.text_input("年度", placeholder="例: 2025")
                
                # 自動生成された大会名を表示
                if tournament_type and tournament_number:
                    auto_generated_name = f"第{tournament_number}回関東大学バスケットボール{tournament_type}"
                    st.info(f"**生成される大会名**: {auto_generated_name}")
                
                if st.form_submit_button("🏆 大会を作成"):
                    if tournament_type and tournament_number and new_tournament_year:
                        tournament_name = f"第{tournament_number}回関東大学バスケットボール{tournament_type}"
                        tournament_id = st.session_state.tournament_management.create_tournament(
                            tournament_name, new_tournament_year
                        )
                        st.success(f"✅ 大会を作成しました（ID: {tournament_id}）")
                        st.success(f"**大会名**: {tournament_name}")
                        st.rerun()
                    else:
                        st.error("❌ 大会種別、回数、年度を入力してください")
            
            # 大会を切り替え
            st.subheader("🔄 大会を切り替え")
            tournaments = st.session_state.tournament_management.get_all_tournaments()
            
            if tournaments:
                tournament_options = {f"{t['tournament_name']} ({t['tournament_year']}年度)": t['id'] for t in tournaments}
                selected_tournament = st.selectbox("大会を選択", list(tournament_options.keys()))
                
                if st.button("🔄 大会を切り替え"):
                    tournament_id = tournament_options[selected_tournament]
                    st.session_state.tournament_management.switch_tournament(tournament_id)
                    st.success("✅ 大会を切り替えました")
                    st.rerun()
            else:
                st.info("大会がありません")
            
            # システム設定
            st.subheader("⚙️ システム設定")
            settings = st.session_state.admin_dashboard.get_system_settings()
            
            if settings:
                with st.form("system_settings_form"):
                    st.text_input("JBAメールアドレス", value=settings.get('jba_email', ''), key="admin_jba_email")
                    st.text_input("JBAパスワード", value=settings.get('jba_password', ''), type="password", key="admin_jba_password")
                    st.text_input("通知メールアドレス", value=settings.get('notification_email', ''), key="admin_notification_email")
                    
                    auto_verification = st.checkbox("自動照合を有効にする", value=settings.get('auto_verification_enabled', True))
                    verification_threshold = st.slider("照合閾値", 0.1, 1.0, settings.get('verification_threshold', 1.0), 0.05)
                    
                    if st.form_submit_button("💾 設定を保存"):
                        new_settings = {
                            'jba_email': st.session_state.admin_jba_email,
                            'jba_password': st.session_state.admin_jba_password,
                            'notification_email': st.session_state.admin_notification_email,
                            'auto_verification_enabled': auto_verification,
                            'verification_threshold': verification_threshold,
                            'current_tournament_id': active_tournament['id'] if active_tournament else None
                        }
                        
                        st.session_state.admin_dashboard.save_system_settings(new_settings)
                        st.success("✅ 設定を保存しました")

if __name__ == "__main__":
    main()
