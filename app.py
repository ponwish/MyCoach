from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client
from postgrest.exceptions import APIError
import os
from datetime import datetime

app = Flask(__name__)
# Session settings for production
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "default_secret")
CORS(
    app,
    origins=["https://imaginative-meerkat-5675d3.netlify.app"],
    supports_credentials=True
)

# OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase client (service role key)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# -----------------------------
# /goal endpoints

@app.route('/goal', methods=['POST'])
def handle_goal():
    data = request.json
    user_id = data.get('userId', '')
    goal_text = (data.get('goal') or '').strip()
    if not goal_text:
        return jsonify({'message': '目標が入力されていません'}), 400
    # upsert goal
    try:
        supabase.table('user_goals').upsert(
            {
                'user_id': user_id,
                'goal': goal_text,
                'updated_at': datetime.utcnow().isoformat()
            },
            ['user_id']
        ).execute()
    except APIError as e:
        app.logger.error(f"Goal upsert error: {e}")
        return jsonify({'message': 'DBエラー'}), 500
    # generate AI advice
    prompt = f"あなたの目標は「{goal_text}」です。最初の具体的なアドバイスを1つ提案してください。"
    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role":"system","content":"あなたはプロフェッショナルなコーチです。"},
            {"role":"user","content":prompt}
        ],
        temperature=0.7,
    )
    advice = resp.choices[0].message.content.strip()
    return jsonify({'message': advice}), 200

@app.route('/user/goal', methods=['GET'])
def get_user_goal():
    user_id = request.args.get('userId', '')
    try:
        resp = supabase.table('user_goals').select('goal').eq('user_id', user_id).single().execute()
        return jsonify({'goal': resp.data['goal']}), 200
    except APIError:
        return jsonify({'goal': None}), 404

# -----------------------------
# coach endpoints

@app.route('/coaches', methods=['GET'])
def list_coaches():
    try:
        resp = supabase.table('profiles').select('id, code_id, name').execute()
        return jsonify(resp.data), 200
    except APIError as e:
        app.logger.error(f"List coaches error: {e}")
        return jsonify([]), 500

@app.route('/user/coach', methods=['GET'])
def get_user_coach():
    user_id = request.args.get('userId', '')
    try:
        resp = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        return jsonify({'coachId': resp.data['coach_id']}), 200
    except APIError:
        return jsonify({'coachId': None}), 404

@app.route('/user/assign_coach', methods=['POST'])
def assign_coach():
    data = request.json
    user_id = data.get('userId', '')
    coach_id = data.get('coachId', '')
    try:
        supabase.table('coach_client_map').upsert(
            {'client_id': user_id, 'coach_id': coach_id, 'updated_at': datetime.utcnow().isoformat()},
            ['client_id']
        ).execute()
        return jsonify({'message': 'OK'}), 200
    except APIError as e:
        app.logger.error(f"Assign coach error: {e}")
        return jsonify({'message': 'DBエラー'}), 500

# -----------------------------
# chat endpoints

@app.route('/talk', methods=['POST'])
def handle_talk():
    data = request.json
    user_id = data.get('userId', '')
    user_msg = data.get('message', '')
    # validate goal
    try:
        goal_resp = supabase.table('user_goals').select('goal').eq('user_id', user_id).single().execute()
    except APIError:
        return jsonify({'message': '目標を設定してください', 'requireGoal': True}), 400
    # validate coach
    try:
        coach_resp = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        coach_id = coach_resp.data['coach_id']
    except APIError:
        return jsonify({'message': '担当コーチを選択してください', 'requireCoach': True}), 400
    # fetch history
    try:
        history_resp = supabase.table('chat_history').select('role,content,created_at').eq('user_id', user_id).eq('coach_id', coach_id).order('created_at').execute()
        history = history_resp.data or []
    except APIError:
        history = []
    # fetch coach profile
    profile_resp = supabase.table('profiles').select('age,gender,job,background,certifications,vision').eq('id', coach_id).single().execute()
    p = profile_resp.data or {}
    profile_text = f"年齢: {p.get('age','')}歳, 性別: {p.get('gender','')}, 職業: {p.get('job','')}, 経歴: {p.get('background','')}, 資格: {p.get('certifications','')}, ビジョン: {p.get('vision','')}"
    # compose messages
    messages = [{"role":"system","content":f"あなたは以下の人物になりきってコーチングを行ってください。\n\n{profile_text}\n\nクライアントの目標は「{goal_resp.data['goal']}」です。過去の会話履歴も踏まえ、前向きで具体的なアドバイスを1つだけ提案してください。"}]
    for msg in history:
        messages.append({"role": msg['role'], "content": msg['content']})
    messages.append({"role":"user","content": user_msg})
    # call OpenAI
    ai_resp = openai_client.chat.completions.create(model="gpt-4o", messages=messages, temperature=0.7)
    ai_msg = ai_resp.choices[0].message.content.strip()
    # save history
    supabase.table('chat_history').insert([
        {"user_id": user_id, "coach_id": coach_id, "role": "user", "content": user_msg, "created_at": datetime.utcnow().isoformat()},
        {"user_id": user_id, "coach_id": coach_id, "role": "assistant", "content": ai_msg, "created_at": datetime.utcnow().isoformat()}
    ]).execute()
    return jsonify({'message': ai_msg}), 200

@app.route('/user/history', methods=['GET'])
def get_history():
    user_id = request.args.get('userId', '')
    coach_id = request.args.get('coachId')
    try:
        query = supabase.table('chat_history').select('role,content,created_at').eq('user_id', user_id)
        if coach_id:
            query = query.eq('coach_id', coach_id)
        resp = query.order('created_at').execute()
        return jsonify(resp.data or []), 200
    except APIError as e:
        app.logger.error(f"Get history error: {e}")
        return jsonify([]), 200

# -----------------------------
# main
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
