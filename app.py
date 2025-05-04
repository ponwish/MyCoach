from flask import Flask, request, jsonify, session
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client
from postgrest.exceptions import APIError
import os
from datetime import datetime

app = Flask(__name__)
# Production session cookie settings
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")
CORS(
    app,
    origins=[
      "https://imaginative-meerkat-5675d3.netlify.app",
      "https://mycoach.onrender.com"
    ],
    supports_credentials=True
)

# Admin credentials (should ideally be in env vars)
ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password1234")

# OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# -----------------------------
# Admin endpoints

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if data.get('admin_id') == ADMIN_ID and data.get('admin_password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'message': 'ログイン成功'})
    return jsonify({'message': '認証失敗'}), 401

@app.route('/admin/profiles', methods=['GET', 'POST'])
def manage_profiles():
    if not session.get('admin_logged_in'):
        return jsonify({'message': '未認証'}), 403
    if request.method == 'GET':
        try:
            resp = supabase.table('profiles').select('*').execute()
            return jsonify(resp.data), 200
        except APIError as e:
            app.logger.error(f"Fetch profiles error: {e}")
            return jsonify([]), 500
    # POST -> create profile
    data = request.json
    payload = {
        'code_id': data.get('code_id'),
        'name': data.get('name'),
        'age': data.get('age'),
        'gender': data.get('gender'),
        'job': data.get('job'),
        'background': data.get('background'),
        'certifications': data.get('certifications'),
        'vision': data.get('vision'),
        'availability_status': True,
        'created_at': datetime.utcnow().isoformat()
    }
    try:
        supabase.table('profiles').insert(payload).execute()
        return jsonify({'message': '追加成功'}), 201
    except APIError as e:
        app.logger.error(f"Create profile error: {e}")
        return jsonify({'message': '追加失敗'}), 500

@app.route('/admin/profiles/<profile_id>', methods=['PATCH'])
def update_profile(profile_id):
    if not session.get('admin_logged_in'):
        return jsonify({'message': '未認証'}), 403
    data = request.json
    update_data = {}

    # 特にstatus変更がある場合は、変更前のステータスを取得
    previous_status = None
    if 'availability_status' in data:
        try:
            old = supabase.table('profiles').select('availability_status').eq('id', profile_id).single().execute()
            previous_status = old.data['availability_status']
        except:
            pass  # エラーでもログなしで続行可

    for key in ['name','age','gender','job','background','certifications','vision','availability_status']:
        if key in data:
            update_data[key] = data[key]
    try:
        supabase.table('profiles').update(update_data).eq('id', profile_id).execute()

        # ログ記録：availability_statusが変わった場合のみ
        if 'availability_status' in update_data and previous_status is not None and previous_status != update_data['availability_status']:
            supabase.table('status_change_logs').insert({
                'profile_id': profile_id,
                'previous_status': previous_status,
                'new_status': update_data['availability_status'],
                'changed_by': 'admin',  # 将来的に拡張可能
            }).execute()

        return jsonify({'message': '更新成功'}), 200
    except APIError as e:
        app.logger.error(f"Update profile error: {e}")
        return jsonify({'message': '更新失敗'}), 500

@app.route('/admin/status_logs/<profile_id>', methods=['GET'])
def get_status_logs(profile_id):
    if not session.get('admin_logged_in'):
        return jsonify({'message': '未認証'}), 403
    try:
        logs = supabase.table('status_change_logs').select('*').eq('profile_id', profile_id).order('changed_at', desc=True).execute()
        return jsonify(logs.data), 200
    except:
        return jsonify([]), 200


# -----------------------------
# Goal endpoints
@app.route('/goal', methods=['POST'])
def handle_goal():
    data = request.json
    user_id = data.get('userId', '')
    goal = (data.get('goal') or '').strip()
    if not goal:
        return jsonify({'message': '目標が入力されていません'}), 400
    try:
        supabase.table('user_goals').upsert(
            {'user_id': user_id, 'goal': goal, 'updated_at': datetime.utcnow().isoformat()},
            ['user_id']
        ).execute()
    except APIError as e:
        app.logger.error(f"Goal upsert error: {e}")
        return jsonify({'message': 'DBエラー'}), 500
    prompt = f"あなたの目標は「{goal}」です。最初の具体的なアドバイスを1つ提案してください。"
    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{'role':'system','content':'プロのコーチです。'}, {'role':'user','content':prompt}],
        temperature=0.7
    )
    return jsonify({'message': resp.choices[0].message.content.strip()}), 200

@app.route('/user/goal', methods=['GET'])
def get_user_goal():
    user_id = request.args.get('userId','')
    try:
        resp = supabase.table('user_goals').select('goal').eq('user_id', user_id).single().execute()
        return jsonify({'goal': resp.data['goal']}), 200
    except APIError:
        return jsonify({'goal': None}), 404

# -----------------------------
# Coach endpoints
@app.route('/coaches', methods=['GET'])
def list_coaches():
    try:
        resp = supabase.table('profiles').select('id,code_id,name,availability_status').execute()
        return jsonify(resp.data), 200
    except APIError as e:
        app.logger.error(f"List coaches error: {e}")
        return jsonify([]), 500

@app.route('/user/coach', methods=['GET'])
def get_user_coach():
    user_id = request.args.get('userId','')
    try:
        resp = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        return jsonify({'coachId': resp.data['coach_id']}), 200
    except APIError:
        return jsonify({'coachId': None}), 404

@app.route('/user/assign_coach', methods=['POST'])
def assign_coach():
    data = request.json
    try:
        supabase.table('coach_client_map').upsert(
            {'client_id': data.get('userId'), 'coach_id': data.get('coachId'), 'updated_at': datetime.utcnow().isoformat()},
            ['client_id']
        ).execute()
        return jsonify({'message':'OK'}), 200
    except APIError as e:
        app.logger.error(f"Assign coach error: {e}")
        return jsonify({'message':'DBエラー'}), 500

# -----------------------------
# Chat endpoints and history similar...
# ...
if __name__ == '__main__':
    port = int(os.getenv('PORT',5000))
    app.run(host='0.0.0.0', port=port)
