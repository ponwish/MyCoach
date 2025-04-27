import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, session, abort
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client, Client
import requests
import traceback

app = Flask(__name__)
# 本番用セッションCookie設定（SameSite=None + Secure属性）
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)

# セッション暗号化キー
app.secret_key = os.getenv("SECRET_KEY", "your_default_secret_key")

# CORS設定（必要に応じてNetlifyやローカルURLを追加）
CORS(
    app,
    origins=[
        "http://127.0.0.1:5500",
        "https://imaginative-meerkat-5675d3.netlify.app"
    ],
    supports_credentials=True
)

# OpenAIクライアント
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Supabase REST 用（profilesテーブル）のAPIキー（anonキーでも可）
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# JSONファイルパス（目標のみファイルに残す想定）
GOALS_FILE = "goals.json"

# Admin認証情報
ADMIN_ID = "admin"
ADMIN_PASSWORD = "password1234"

# ------------------------------
# Utility関数
# ------------------------------
def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_profile_to_supabase(profile_data):
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {
        "id": str(uuid.uuid4()),
        "age": profile_data.get("age", ""),
        "gender": profile_data.get("gender", ""),
        "job": profile_data.get("job", ""),
        "background": profile_data.get("background", ""),
        "certifications": profile_data.get("certifications", ""),
        "vision": profile_data.get("vision", ""),
        "created_at": datetime.utcnow().isoformat()
    }
    return requests.post(url, json=payload, headers=headers)


def fetch_profile_from_supabase():
    url = f"{SUPABASE_URL}/rest/v1/profiles?select=*"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        profiles = res.json()
        return profiles[-1] if profiles else {}
    return {}

# ------------------------------
# Mini Appユーザー向けAPI
# ------------------------------
@app.route('/goal', methods=['POST'])
def handle_goal():
    try:
        data = request.json
        user_id = data.get('userId', '')
        goal = data.get('goal', '')

        if not goal:
            return jsonify({'message': '目標が入力されていません'}), 400

        goals_data = load_json(GOALS_FILE)
        goals_data[user_id] = goal
        save_json(GOALS_FILE, goals_data)

        prompt = f"""あなたは優秀なコーチです。
以下の目標を持つクライアントに対し、達成に向けた最初のアドバイスを具体的に1つだけ提案してください。
目標: {goal}
"""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたはプロフェッショナルなキャリアコーチです。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )

        coaching_message = response.choices[0].message.content.strip()
        return jsonify({'message': coaching_message})

    except Exception as e:
        print(f"エラー発生: {e}")
        return jsonify({'message': 'サーバエラーが発生しました'}), 500


@app.route('/talk', methods=['POST'])
def handle_talk():
    try:
        data = request.json
        user_id = data.get('userId', '')
        user_message = data.get('message', '')

        if not user_message:
            return jsonify({'message': 'メッセージが入力されていません'}), 400

        # 目標取得
        goals_data = load_json(GOALS_FILE)
        user_goal = goals_data.get(user_id, '')

        # コーチプロファイル取得
        profile_data = fetch_profile_from_supabase()
        profile_text = (
            f"年齢: {profile_data.get('age','')}歳, "
            f"性別: {profile_data.get('gender','')}, "
            f"職業: {profile_data.get('job','')}, "
            f"経歴: {profile_data.get('background','')}, "
            f"資格: {profile_data.get('certifications','')}, "
            f"ビジョン: {profile_data.get('vision','')}"
        )

        # 過去の会話履歴をDBから取得
        history_res = supabase.table('chat_history') \
            .select('role, content') \
            .eq('user_id', user_id) \
            .order('created_at', {'ascending': True}) \
            .execute()
        user_history = [
            {'role': rec['role'], 'content': rec['content']} 
            for rec in history_res.data
        ]

        # システムメッセージ組立て
        system_message = f"""
あなたは以下の人物になりきって、クライアントにコーチングを行ってください。

{profile_text}

クライアントの目標は「{user_goal}」です。
過去の会話履歴も踏まえて、前向きで具体的なアドバイスを1つだけ提案してください。
"""

        messages = (
            [{'role': 'system', 'content': system_message}] +
            user_history +
            [{'role': 'user', 'content': user_message}]
        )

        # OpenAI 呼び出し
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
        )
        assistant_message = response.choices[0].message.content.strip()

        # DBに会話履歴を保存
        supabase.table('chat_history').insert({
            'user_id': user_id,
            'role': 'user',
            'content': user_message
        }).execute()
        supabase.table('chat_history').insert({
            'user_id': user_id,
            'role': 'assistant',
            'content': assistant_message
        }).execute()

        return jsonify({'message': assistant_message})

    except Exception as e:
        # サーバログにスタックトレースを出力
        traceback.print_exc()

        # クライアントにもエラー内容を返す
        return jsonify({
            'message': 'サーバエラーが発生しました',
            'error': str(e)
        }), 500

# ------------------------------
# Admin用API
# ------------------------------
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if data.get('admin_id') == ADMIN_ID and data.get('admin_password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'message': 'ログイン成功'})
    return jsonify({'message': '認証失敗'}), 401


@app.route('/admin/set_profile', methods=['POST'])
def set_profile():
    if not session.get('admin_logged_in'):
        return jsonify({'message': '未認証です'}), 403

    supabase_response = save_profile_to_supabase(request.json)
    if supabase_response.status_code == 201:
        return jsonify({'message': 'プロファイルを保存しました'})
    return jsonify({'message': '保存失敗', 'error': supabase_response.text}), 500

@app.route('/healthz', methods=['GET'])
def healthz():
    try:
        res = supabase.table('chat_history') \
            .select('id') \
            .limit(1) \
            .execute()
        # エラーがあればエラー内容を返す
        if res.error:
            return jsonify({
                'db': 'error',
                'message': str(res.error)
            }), 500
        # 正常: レコード件数だけ返す
        return jsonify({
            'db': 'ok',
            'count': len(res.data or [])
        }), 200
    except Exception as e:
        return jsonify({
            'db': 'error',
            'message': str(e)
        }), 500
    
@app.route('/routes', methods=['GET'])
def list_routes():
    """
    現在 Flask が認識している全ルートを返します
    """
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': str(rule)
        })
    return jsonify(routes)

# ------------------------------
# メイン
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
