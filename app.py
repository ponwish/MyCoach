from flask import Flask, request, jsonify, session, abort
from flask_cors import CORS
from openai import OpenAI
import json
import os

app = Flask(__name__)
app.secret_key = "super_secret_admin_key"  # セッション用のシークレットキー
CORS(app, origins=["https://imaginative-meerkat-5675d3.netlify.app"], supports_credentials=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GOALS_FILE = "goals.json"
CONVERSATIONS_FILE = "conversations.json"
PROFILE_FILE = "profile.json"

# Admin認証情報（仮ハードコーディング）
ADMIN_ID = "admin"
ADMIN_PASSWORD = "password1234"

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

        # 会話履歴取得
        conv_data = load_json(CONVERSATIONS_FILE)
        user_history = conv_data.get(user_id, [])

        # コーチプロファイル取得
        profile_data = load_json(PROFILE_FILE)
        profile_text = (
            f"年齢: {profile_data.get('age', '')}歳, "
            f"性別: {profile_data.get('gender', '')}, "
            f"職業: {profile_data.get('job', '')}, "
            f"経歴: {profile_data.get('background', '')}, "
            f"資格: {profile_data.get('certifications', '')}, "
            f"ビジョン: {profile_data.get('vision', '')}"
        )

        system_message = f"""あなたは以下の人物になりきって、クライアントにコーチングを行ってください。

{profile_text}

クライアントの目標は「{user_goal}」です。
過去の会話履歴も踏まえて、前向きで具体的なアドバイスを1つだけ提案してください。
"""

        messages = [{"role": "system", "content": system_message}] + user_history + [{"role": "user", "content": user_message}]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
        )

        assistant_message = response.choices[0].message.content.strip()

        # 履歴追加
        user_history.append({"role": "user", "content": user_message})
        user_history.append({"role": "assistant", "content": assistant_message})

        conv_data[user_id] = user_history
        save_json(CONVERSATIONS_FILE, conv_data)

        return jsonify({'message': assistant_message})

    except Exception as e:
        print(f"エラー発生: {e}")
        return jsonify({'message': 'サーバエラーが発生しました'}), 500

# ------------------------------
# Admin用API
# ------------------------------
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    admin_id = data.get('admin_id')
    admin_password = data.get('admin_password')

    if admin_id == ADMIN_ID and admin_password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'message': 'ログイン成功'})
    else:
        return jsonify({'message': '認証失敗'}), 401

@app.route('/admin/set_profile', methods=['POST'])
def set_profile():
    if not session.get('admin_logged_in'):
        return jsonify({'message': '未認証です'}), 403

    profile_data = request.json
    save_json(PROFILE_FILE, profile_data)
    return jsonify({'message': 'プロファイルを更新しました'})

# ------------------------------
# メイン
# ------------------------------
if __name__ == "__main__":
    from os import environ
    port = int(environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    