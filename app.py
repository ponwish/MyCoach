import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, session, abort, send_from_directory
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client, Client
import requests

app = Flask(__name__, static_folder="static")
# セッションCookie設定（SameSite=None + Secure属性）
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "your_default_secret_key")

# CORS設定
CORS(
    app,
    origins=["http://localhost:5500", "https://imaginative-meerkat-5675d3.netlify.app"],
    supports_credentials=True
)

# OpenAIクライアント
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# JSONファイルパス（目標のみファイルに残す）
GOALS_FILE = "goals.json"

# Admin認証情報
ADMIN_ID = "admin"
ADMIN_PASSWORD = "password1234"

# Utility

def load_json(fp):
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(fp, data):
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# プロフィール設定用
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

# コーチプロフィールCRUD
@app.route('/admin/profiles', methods=['GET'])
def list_profiles():
    if not session.get('admin_logged_in'):
        return abort(403)
    res = supabase.table('profiles').select('*').execute()
    return jsonify(res.data or []), 200

@app.route('/admin/profiles', methods=['POST'])
def create_profile():
    if not session.get('admin_logged_in'):
        return abort(403)
    payload = request.json
    payload['id'] = str(uuid.uuid4())
    payload['created_at'] = datetime.utcnow().isoformat()
    # availability_status は DB default TRUE
    res = supabase.table('profiles').insert(payload).execute()
    return jsonify(res.data[0]), 201

@app.route('/admin/profiles/<profile_id>', methods=['PATCH'])
def update_profile(profile_id):
    if not session.get('admin_logged_in'):
        return abort(403)
    updates = request.json
    res = supabase.table('profiles') \
        .update(updates) \
        .eq('id', profile_id) \
        .execute()
    return jsonify(res.data[0] if res.data else {}), 200

# Mini App: 目標登録
@app.route('/goal', methods=['POST'])
def handle_goal():
    data = request.json
    user_id = data.get('userId', '')
    goal = data.get('goal', '')
    if not goal:
        return jsonify({'message': '目標が入力されていません'}), 400
    goals = load_json(GOALS_FILE)
    goals[user_id] = goal
    save_json(GOALS_FILE, goals)
    prompt = f"""あなたは優秀なコーチです。クライアントの目標: {goal} に対し、最初の具体的なアドバイスを1つ提案してください。"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{'role':'system','content':'プロフェッショナルなキャリアコーチです。'},
                  {'role':'user','content':prompt}],
        temperature=0.7)
    return jsonify({'message': resp.choices[0].message.content.strip()}), 200

# Mini App: チャット
@app.route('/talk', methods=['POST'])
def handle_talk():
    try:
        data = request.json
        user_id = data.get('userId','')
        user_msg = data.get('message','')
        if not user_msg:
            return jsonify({'message':'メッセージが入力されていません'}),400
        # 目標
        goals = load_json(GOALS_FILE)
        user_goal = goals.get(user_id,'')
        # コーチ選択: user → mapping 省略（デフォルト1件利用）
        # プロファイル取得
        profiles = supabase.table('profiles').select('*').execute().data or []
        coach = profiles[0] if profiles else {}
        prof_text = f"年齢:{coach.get('age','')}歳,性別:{coach.get('gender','')},職業:{coach.get('job','')},経歴:{coach.get('background','')},資格:{coach.get('certifications','')},ビジョン:{coach.get('vision','')}"
        # 履歴取得
        res = supabase.table('chat_history').select('role,content,created_at').eq('user_id',user_id).execute()
        raw = res.data or []
        sorted_hist = sorted(raw, key=lambda x: x['created_at'])
        user_hist = [{'role':r['role'],'content':r['content']} for r in sorted_hist]
        system_msg = f"""あなたは以下人物になりきりコーチングしてください。{prof_text}\nクライアントの目標「{user_goal}」。過去履歴を踏まえ前向きで具体的なアドバイスを1つ提案。"""
        msgs = [{'role':'system','content':system_msg}] + user_hist + [{'role':'user','content':user_msg}]
        resp = client.chat.completions.create(model="gpt-4o", messages=msgs, temperature=0.7)
        bot_msg = resp.choices[0].message.content.strip()
        # 履歴保存
        supabase.table('chat_history').insert({'user_id':user_id,'role':'user','content':user_msg}).execute()
        supabase.table('chat_history').insert({'user_id':user_id,'role':'assistant','content':bot_msg}).execute()
        return jsonify({'message':bot_msg}),200
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'message':'サーバエラー','error':str(e)}),500

if __name__ == '__main__':
    port = int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0', port=port)