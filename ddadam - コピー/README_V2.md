# 🏀 仮選手証システム v2.0

## 概要
Playwright依存を完全に排除し、`requests` + `BeautifulSoup`ベースで動作する仮選手証システムです。

## 🚀 主な特徴

### ✅ **Playwright不要**
- `requests` + `BeautifulSoup`のみ使用
- クラウド環境でのデプロイが簡単
- 軽量で高速

### 🎛️ **管理者機能**
- 大会管理（作成、切り替え、回答受付制御）
- 印刷システム（個別証明書生成）
- 統計情報
- システム設定

### 📝 **申請フォーム**
- 仮選手証・仮スタッフ証申請
- ファイルアップロード対応
- リアルタイム照合

### 🔍 **JBA照合**
- リアルタイムデータ取得
- 男子チームのみ対象
- 現在年度自動検索

## 📦 インストール

```bash
pip install -r requirements.txt
```

## 🚀 実行

```bash
streamlit run player_verification_system_v2.py
```

## 🌐 デプロイ

### Create AI
1. `player_verification_system_v2.py`をアップロード
2. `requirements.txt`をアップロード
3. 環境変数を設定（必要に応じて）

### Streamlit Community Cloud
1. GitHubリポジトリにプッシュ
2. Streamlit Community Cloudでデプロイ

## 🔧 設定

### 環境変数
```bash
# JBAログイン情報（オプション）
JBA_EMAIL=your_email@example.com
JBA_PASSWORD=your_password

# 通知設定（オプション）
NOTIFICATION_EMAIL=admin@example.com
```

## 📊 データベース

SQLiteを使用（軽量・ファイルベース）
- `tournaments`: 大会情報
- `player_applications`: 申請情報
- `verification_results`: 照合結果
- `admin_settings`: システム設定

## 🎯 使用方法

### 1. 管理者設定
1. 管理者機能を有効にする
2. 大会を作成・設定
3. 回答受付を開始

### 2. 申請受付
1. 申請フォームで情報入力
2. ファイルアップロード
3. 申請送信

### 3. 照合処理
1. JBAログイン情報を入力
2. 大学名で検索
3. 自動照合実行

### 4. 印刷・出力
1. 申請一覧から選択
2. 個別証明書生成
3. ダウンロード

## 🔒 セキュリティ

- パスワードは暗号化して保存
- セッション管理
- 入力値検証

## 📈 パフォーマンス

- 軽量設計
- 高速レスポンス
- メモリ効率

## 🐛 トラブルシューティング

### よくある問題

1. **JBAログイン失敗**
   - 認証情報を確認
   - ネットワーク接続を確認

2. **照合結果が取得できない**
   - 大学名の表記を確認
   - 年度設定を確認

3. **印刷ができない**
   - ファイル権限を確認
   - ディスク容量を確認

## 📞 サポート

問題が発生した場合は、ログを確認してください。

## 🔄 更新履歴

### v2.0
- Playwright依存を削除
- requests + BeautifulSoupベースに変更
- 管理者機能を統合
- 軽量化・高速化

### v1.0
- 初期リリース
- Playwrightベース
- 基本機能実装
