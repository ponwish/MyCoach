from flask import Flask, request, jsonify, session
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client
from postgrest.exceptions import APIError
import os
import requests
import uuid
from datetime import datetime

app = Flask(__name__)
# Production session cookie settings
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "your_default_secret_key")
CORS(
    app,
    origins=["http://127.0.0.1:5500", "https://imaginative-meerkat-5675d3.netlify.app"],
    supports_credentials=True
)

# OpenAI client
oai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Use service role key in backend to bypass RLS
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ------------------------------------
# Utility functions
def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}

# ------------------------------------
# Goal endpoints
def upsert_user_goal(user_id, goal_text):
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
        app.logger.error(f"Upsert error: {e}")
        raise

@app.route('/goal', methods=['POST'])
def handle_goal():
    data = request.json
    user_id = data.get('userId', '')
    goal_text = data.get('goal', '').strip()
    if not goal_text:
        return jsonify({'message': '目標が入力されていません'}), 400
    try:
        upsert_user_goal(user_id, goal_text)
    except Exception:
        return jsonify({'message': 'DBエラーが発生しました'}), 500

    prompt = f"あなたの目標は「{goal_text}」です。最初の具体的なアドバイスを1つ提案してください。"
    response = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "あなたはプロフェッショナルなコーチです。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
    )
    message = response.choices[0].message.content.strip()
    return jsonify({'message': message})

@app.route('/user/goal', methods=['GET'])
def get_user_goal():
    user_id = request.args.get('userId', '')
    try:
        resp = supabase.table('user_goals')\
            .select('goal')\
            .eq('user_id', user_id)\
            .single()\
            .execute()
        return jsonify({'goal': resp.data['goal']}), 200
    except APIError:
        return jsonify({'goal': None}), 404

# ------------------------------------
# Coach assignment endpoints
@app.route('/user/coach', methods=['GET'])
def get_user_coach():
    user_id = request.args.get('userId', '')
    # fetch mapping from coach_client_map
    resp = supabase.table('coach_client_map')\
        .select('coach_id')\
        .eq('client_id', user_id)\
        .single()\
        .execute()
    if resp.error or not resp.data:
        return jsonify({'coachId': None}), 404
    return jsonify({'coachId': resp.data['coach_id']}), 200

@app.route('/user/assign_coach', methods=['POST'])
def assign_coach():
    data = request.json
    user_id = data.get('userId')
    coach_id = data.get('coachId')
    # upsert mapping
    try:
        supabase.table('coach_client_map').upsert(
            {
                'client_id': user_id,
                'coach_id': coach_id,
                'updated_at': datetime.utcnow().isoformat()
            },
            ['client_id']
        ).execute()
    except APIError:
        return jsonify({'message': 'DBエラー'}), 500
    return jsonify({'message': 'OK'})

# ------------------------------------
# Chat endpoints
@app.route('/talk', methods=['POST'])
def handle_talk():
    data = request.json
    user_id = data.get('userId', '')
    user_message = data.get('message', '')

    # check goal
    try:
        g = supabase.table('user_goals').select('goal').eq('user_id', user_id).single().execute()
    except APIError:
        return jsonify({'message': '目標を設定してください', 'requireGoal': True}), 400

    # check coach
    try:
        m = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        coach_id = m.data['coach_id']
    except APIError:
        return jsonify({'message': '担当コーチを選択してください', 'requireCoach': True}), 400

    # fetch chat history and profile omitted for brevity...
    # generate AI response and save to chat_history
    return jsonify({'message': 'AIの応答'})

# ------------------------------------
# Main
if __name__ == "__main__":
    from os import environ
    port = int(environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
