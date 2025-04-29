import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, session, abort, send_from_directory
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client, Client
import requests

# Flaskアプリ初期化
app = Flask(__name__, static_folder="static")
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "your_default_secret_key")
CORS(
    app,
    origins=[
        "http://127.0.0.1:5500",
        "https://imaginative-meerkat-5675d3.netlify.app",
        "https://mycoach.onrender.com"
    ],
    supports_credentials=True
)

# OpenAIクライアント
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabaseクライアント
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# 目標データ保存用
GOALS_FILE = "goals.json"

# Admin認証情報
ADMIN_ID = "admin"
ADMIN_PASSWORD = "password1234"

# =========================
# Admin画面ルーティング
# =========================
@app.route('/admin/login', methods=['GET'])
def serve_admin_login():
    return send_from_directory(app.static_folder, 'admin.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if data.get('admin_id') == ADMIN_ID and data.get('admin_password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'message': 'ログイン成功'})
    return jsonify({'message': '認証失敗'}), 401

# Admin用: コーチ一覧 / 作成 / 更新 / ステータス変更
@app.route('/admin/profiles', methods=['GET', 'POST'])
def admin_profiles():
    if not session.get('admin_logged_in'):
        return abort(403)
    if request.method == 'GET':
        res = supabase.table('profiles').select('*').execute()
        return jsonify(res.data)
    # POST: 新規作成
    payload = request.json
    payload['id'] = str(uuid.uuid4())
    payload['created_at'] = datetime.utcnow().isoformat()
    res = supabase.table('profiles').insert(payload).execute()
    return jsonify(res.data[0]), 201

@app.route('/admin/profiles/<profile_id>', methods=['PATCH'])
def admin_update_profile(profile_id):
    if not session.get('admin_logged_in'):
        return abort(403)
    updates = request.json
    res = supabase.table('profiles').update(updates).eq('id', profile_id).execute()
    return jsonify(res.data[0])

# =========================
# コーチ選択・マッピング API
# =========================
# コーチ一覧取得
@app.route('/coaches', methods=['GET'])
def get_coaches():
    res = supabase.table('profiles') \
        .select('id, code_id, name, job') \
        .eq('availability_status', True) \
        .execute()
    return jsonify(res.data)

# ユーザの担当コーチ取得
@app.route('/user/coach', methods=['GET'])
def get_user_coach():
    user_id = request.args.get('userId', '')
    res = supabase.table('coach_client_map') \
        .select('coach_id') \
        .eq('client_id', user_id) \
        .single().execute()
    if res.data:
        return jsonify({'coachId': res.data['coach_id']})
    return jsonify({}), 404

# コーチマッピング（upsert）
@app.route('/user/assign_coach', methods=['POST'])
def assign_coach():
    data = request.json
    user_id = data.get('userId')
    coach_id = data.get('coachId')
    record = {
        'client_id': user_id,
        'coach_id': coach_id,
        'created_at': datetime.utcnow().isoformat()
    }
    # upsert: 既存の場合は更新
    res = supabase.table('coach_client_map') \
        .upsert(record, on_conflict=['client_id']) \
        .execute()
    return jsonify(res.data[0]), 200

# =========================
# 既存のユーザーAPI
# =========================
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
        prompt = f"""あなたは優秀なコーチです。目標: {goal}"""
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
        import traceback; traceback.print_exc()
        return jsonify({'message': 'サーバエラーが発生しました', 'error': str(e)}), 500

@app.route('/talk', methods=['POST'])
def handle_talk():
    try:
        data = request.json
        user_id = data.get('userId', '')
        user_message = data.get('message', '')
        if not user_message:
            return jsonify({'message': 'メッセージが入力されていません'}), 400
        # クライアントの担当コーチ取得
        map_res = supabase.table('coach_client_map') \
            .select('coach_id') \
            .eq('client_id', user_id) \
            .single().execute()
        coach_id = map_res.data['coach_id'] if map_res.data else None
        # プロファイル取得
        prof_res = supabase.table('profiles') \
            .select('*') \
            .eq('id', coach_id).single().execute()
        profile_data = prof_res.data or {}
        # プロファイルテキスト生成
        profile_text = (
            f"年齢: {profile_data.get('age','')}歳, "
            f"性別: {profile_data.get('gender','')}, "
            f"職業: {profile_data.get('job','')}"
        )
        # 履歴取得（ソート済）
        history_res = supabase.table('chat_history') \
            .select('role, content, created_at') \
            .eq('user_id', user_id).execute()
        raw = history_res.data or []
        sorted_history = sorted(raw, key=lambda x: x['created_at'])
        user_history = [{'role': r['role'], 'content': r['content']} for r in sorted_history]
        # システムメッセージ
        system_message = f"""
あなたは以下の人物になりきってコーチングを行ってください。
{profile_text}
"""
        messages = [{'role':'system','content':system_message}] + user_history + [{'role':'user','content':user_message}]
        res = client.chat.completions.create(model="gpt-4o", messages=messages, temperature=0.7)
        assistant_message = res.choices[0].message.content.strip()
        # 会話履歴保存
        supabase.table('chat_history').insert({'user_id':user_id,'role':'user','content':user_message}).execute()
        supabase.table('chat_history').insert({'user_id':user_id,'role':'assistant','content':assistant_message}).execute()
        return jsonify({'message': assistant_message})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'message': 'サーバエラーが発生しました', 'error': str(e)}), 500

@app.route('/user/history', methods=['GET'])
def get_history():
    user_id = request.args.get('userId', '')
    res = supabase.table('chat_history') \
        .select('role, content, created_at') \
        .eq('user_id', user_id) \
        .execute()
    raw = res.data or []
    history = sorted(raw, key=lambda x: x['created_at'])
    return jsonify([
        {'role': h['role'], 'content': h['content'], 'created_at': h['created_at']}
        for h in history
    ])


# ヘルスチェック
@app.route('/healthz', methods=['GET'])
def healthz():
    try:
        res = supabase.table('chat_history').select('id').limit(1).execute()
        return jsonify({'db': 'ok', 'count': len(res.data or [])})
    except Exception as e:
        return jsonify({'db': 'error', 'message': str(e)}), 500

# ファイル入出力関数

def load_json(path):
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}

def save_json(path, data):
    json.dump(data, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

# メイン
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
