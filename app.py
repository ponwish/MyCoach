from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from openai import OpenAI
from supabase import create_client
from postgrest.exceptions import APIError
import os
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import uuid, logging, traceback

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=True,
)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")

# ✅ CORS設定を強化
CORS(
    app,
    resources={r"/*": {"origins": [
        "https://imaginative-meerkat-5675d3.netlify.app",
        "https://mycoach.onrender.com"
    ]}},
    supports_credentials=True,
    allow_headers="*",
    methods=["GET", "POST", "PATCH", "OPTIONS"]
)

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password1234")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SUPABASE_URL                = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY   = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # 管理/DB 用
SUPABASE_ANON_KEY           = os.getenv("SUPABASE_ANON_KEY")          # 認証用

# 🔑 クライアントを 2 系統に分離
supabase_admin  = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)  # 旧 supabase
supabase_public = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ----------------- 以降は supabase_admin を従来の supabase として利用 -----------------
supabase = supabase_admin

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
    previous_status = None
    if 'availability_status' in data:
        try:
            old = supabase.table('profiles').select('availability_status').eq('id', profile_id).single().execute()
            previous_status = old.data['availability_status']
        except:
            pass
    for key in ['name','age','gender','job','background','certifications','vision','availability_status']:
        if key in data:
            update_data[key] = data[key]
    try:
        supabase.table('profiles').update(update_data).eq('id', profile_id).execute()
        if 'availability_status' in update_data and previous_status is not None and previous_status != update_data['availability_status']:
            supabase.table('status_change_logs').insert({
                'profile_id': profile_id,
                'previous_status': previous_status,
                'new_status': update_data['availability_status'],
                'changed_by': 'admin',
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

@app.route('/goal', methods=['POST', 'OPTIONS'])
def handle_goal():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json
    try:
        # INSERT による履歴保持型保存
        supabase.table('user_goals').insert({
            "user_id": data.get("userId"),
            "goal": data.get("goal"),
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        return jsonify({"message": "OK"}), 200
    except Exception as e:
        app.logger.error(f"Goal insert error: {e}")
        return jsonify({"message": "DBエラー"}), 500

@app.route('/user/goal', methods=['GET', 'OPTIONS'])
def get_latest_goal():
    user_id = request.args.get('userId')
    try:
        response = supabase.table('user_goals') \
            .select('goal, created_at') \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(1) \
            .execute()
        latest = response.data[0] if response.data else {}
        return jsonify(latest)
    except Exception as e:
        app.logger.error(f"Goal fetch error: {e}")
        return jsonify({}), 500

@app.route('/coaches', methods=['GET', 'OPTIONS'])
def list_coaches():
    try:
        resp = supabase.table('profiles').select('id,code_id,name,availability_status').execute()
        return jsonify(resp.data), 200
    except APIError as e:
        app.logger.error(f"List coaches error: {e}")
        return jsonify([]), 500

@app.route('/user/coach', methods=['GET', 'OPTIONS'])
def get_user_coach():
    user_id = request.args.get('userId','')
    try:
        resp = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        return jsonify({'coachId': resp.data['coach_id']}), 200
    except APIError:
        return jsonify({'coachId': None}), 404

@app.route('/user/assign_coach', methods=['POST', 'OPTIONS'])
def assign_coach():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json(force=True)
        user_id = data.get('userId')
        coach_id = data.get('coachId')

        if not user_id or not coach_id:
            return jsonify({'message': 'userIdとcoachIdは必須です'}), 400

        supabase.table('coach_client_map').upsert({
                'client_id': user_id,
                'coach_id': coach_id
            }, on_conflict=['client_id']).execute()


        return jsonify({'message': 'OK'}), 200

    except APIError as e:
        app.logger.error(f"Assign coach error: {e}")
        return jsonify({'message': 'DBエラー'}), 500

    except Exception as e:
        app.logger.error(f"Unexpected error in assign_coach: {e}")
        return jsonify({'message': 'サーバーエラー'}), 500

@app.route('/talk', methods=['POST', 'OPTIONS'])
def handle_talk():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.json
    user_id = data.get('userId', '')
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'message': 'メッセージが空です'}), 400

    # ✅ 最新の目標を取得
    try:
        goal_resp = supabase.table('user_goals') \
            .select('goal') \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(1) \
            .execute()
        if not goal_resp.data:
            return jsonify({'requireGoal': True}), 200
        user_goal = goal_resp.data[0]['goal']
    except Exception as e:
        app.logger.error(f"Goal fetch error: {e}")
        return jsonify({'requireGoal': True}), 200

    # ✅ コーチチェック
    try:
        coach_resp = supabase.table('coach_client_map').select('coach_id').eq('client_id', user_id).single().execute()
        coach_id = coach_resp.data['coach_id']
    except:
        return jsonify({'requireCoach': True}), 200

    # ✅ コーチ情報を取得（コーチ名など）
    try:
        coach_profile = supabase.table('profiles').select('name').eq('id', coach_id).single().execute()
        coach_name = coach_profile.data['name']
    except:
        coach_name = "あなたの担当コーチ"

    # ✅ ユーザー発言を履歴登録
    try:
        supabase.table('chat_history').insert({
            'user_id': user_id,
            'coach_id': coach_id,
            'content': user_message,
            'role': 'user',
            'created_at': datetime.utcnow().isoformat()
        }).execute()
    except:
        pass

    # ✅ GPTに文脈込みで問い合わせ
    prompt = f"""あなたの担当コーチは「{coach_name}」です。
ユーザーの目標は「{user_goal}」です。
ユーザーからの質問:「{user_message}」
プロのコーチとして的確に助言してください。"""

    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {'role': 'system', 'content': 'あなたはプロのコーチです。'},
            {'role': 'user', 'content': prompt}
        ],
        temperature=0.7
    )

    ai_message = resp.choices[0].message.content.strip()

    try:
        supabase.table('chat_history').insert({
            'user_id': user_id,
            'coach_id': coach_id,
            'content': ai_message,
            'role': 'assistant',
            'created_at': datetime.utcnow().isoformat()
        }).execute()
    except:
        pass

    return jsonify({'message': ai_message}), 200


@app.route('/user/history', methods=['GET', 'OPTIONS'])
def get_chat_history():
    user_id = request.args.get('userId', '')
    coach_id = request.args.get('coachId')

    if not user_id:
        return jsonify({'error': 'userId is required'}), 400

    try:
        q = supabase.table('chat_history').select('*').eq('user_id', user_id)

        if coach_id:
            q = q.eq('coach_id', coach_id)

        # ✅ 正しい並び順指定方法
        q = q.order('created_at', desc=False)

        data = q.execute()
        return jsonify(data.data), 200

    except Exception as e:
        app.logger.error(f"履歴取得中のエラー: {str(e)}")
        return jsonify({'error': '履歴取得に失敗しました', 'details': str(e)}), 500

@app.route('/coach/login', methods=['POST'])
def coach_login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'error': 'メールアドレスとパスワードは必須です。'}), 400

        # 該当コーチを取得
        result = supabase.table('profiles') \
            .select('id, name, password_hash') \
            .eq('email', email).single().execute()

        coach = result.data  # v2では .data でOK
        if not coach:
            return jsonify({'error': 'ユーザーが見つかりませんでした'}), 401

        stored_hash = coach.get('password_hash')
        if not stored_hash or not check_password_hash(stored_hash, password):
            return jsonify({'error': 'パスワードが正しくありません'}), 401

        return jsonify({
            'id': coach['id'],
            'name': coach['name'],
            'message': 'ログインに成功しました'
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'サーバーエラー: {str(e)}'}), 500


@app.route('/coach/register', methods=['POST'])
def register_coach():
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')

        if not all([name, email, password]):
            return jsonify({'error': '全ての項目を入力してください'}), 400

        # 既存のメールチェック
        existing = supabase.table('profiles').select('id').eq('email', email).execute()
        if existing.data and len(existing.data) > 0:
            return jsonify({'error': 'このメールアドレスは既に登録されています'}), 400

        # ✅ code_id を自動採番
        latest = supabase.table('profiles') \
            .select('code_id') \
            .neq('code_id', None) \
            .order('code_id', desc=True) \
            .limit(1).execute()

        max_code = latest.data[0]['code_id'] if latest.data else 'C_0000000'
        next_number = int(max_code.split('_')[1]) + 1
        new_code_id = f'C_{next_number:07d}'

        # パスワードハッシュ生成
        hashed_pw = generate_password_hash(password)

        # 登録処理
        supabase.table('profiles').insert({
            'id': str(uuid.uuid4()),
            'name': name,
            'email': email,
            'password_hash': hashed_pw,
            'code_id': new_code_id,
            'availability_status': True
        }).execute()

        return jsonify({'success': True, 'message': '登録が完了しました！'}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# ---------- Coach Profile ----------
@app.route('/coach/profile', methods=['GET', 'PATCH'])
def coach_profile():
    coach_id = request.args.get('coachId') or request.form.get('coachId') or (request.json or {}).get('coachId')
    if not coach_id:
        return jsonify({'error': 'coachId is required'}), 400

    if request.method == 'GET':
        try:
            resp = supabase.table('profiles').select('*').eq('id', coach_id).single().execute()
            return jsonify(resp.data), 200
        except Exception as e:
            app.logger.error(f"profile fetch: {e}")
            return jsonify({'error': 'fetch error'}), 500

    # PATCH
    data = request.form if request.form else request.json
    payload = {
        'name': data.get('name'),
        'email': data.get('email'),
        'tel': data.get('tel'),
        'preference': data.get('preference')
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    # アイコン
    if 'icon' in request.files:
        file = request.files['icon']
        filename = f'icon_{coach_id}.png'
        with open(f'/tmp/{filename}', 'wb') as f:
            f.write(file.read())
        payload['icon_url'] = f'https://{SUPABASE_URL}/storage/v1/object/public/icons/{filename}'

    try:
        supabase.table('profiles').update(payload).eq('id', coach_id).execute()
        return jsonify({'message': 'updated'}), 200
    except Exception as e:
        app.logger.error(f"profile update: {e}")
        return jsonify({'error': 'update error'}), 500


# ---------- Coach Clients ----------
@app.route('/coach/clients', methods=['GET'])
def coach_clients():
    coach_id = request.args.get('coachId')
    if not coach_id:
        return jsonify([]), 200

    try:
        # ① coach_client_map から user_id 抽出
        resp = supabase.table('coach_client_map').select('client_id').eq('coach_id', coach_id).execute()
        ids = [r['client_id'] for r in resp.data]
        if not ids:
            return jsonify([]), 200

        # ② auth.users から email を名前代わりに取得（Schema 指定がポイント）
        try:
            auth_users = supabase.table('users', schema='auth').select('id, email').in_('id', ids).execute()
            users = [{'id': u['id'], 'name': u['email']} for u in auth_users.data]
        except Exception:
            # auth.users が取れない場合は ID だけ返却
            users = [{'id': i, 'name': ''} for i in ids]

        return jsonify(users), 200
    except Exception as e:
        app.logger.error(f"clients fetch: {e}")
        return jsonify([]), 500


# ---------- Coach History ----------
@app.route('/coach/history', methods=['GET'])
def coach_history():
    coach_id = request.args.get('coachId')
    client_id = request.args.get('clientId')
    if not (coach_id and client_id):
        return jsonify([]), 200
    try:
        rows = (supabase
                .table('chat_history')
                .select('*')
                .eq('coach_id', coach_id)
                .eq('user_id', client_id)
                .order('created_at', desc=False)
                .execute())
        return jsonify(rows.data), 200
    except Exception as e:
        app.logger.error(f"history fetch: {e}")
        return jsonify([], 500)


# ---------- CSV エクスポート ----------
@app.route('/coach/history_csv', methods=['GET'])
def history_csv():
    coach_id = request.args.get('coachId')
    client_id = request.args.get('clientId')
    if not (coach_id and client_id):
        return jsonify({'error': 'params'}), 400
    try:
        import csv, io
        rows = (supabase
                .table('chat_history')
                .select('*')
                .eq('coach_id', coach_id)
                .eq('user_id', client_id)
                .order('created_at', desc=False)
                .execute()
                .data)
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['role', 'content', 'created_at'])
        for r in rows:
            cw.writerow([r['role'], r['content'], r['created_at']])
        return si.getvalue(), 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename=history.csv'
        }
    except Exception as e:
        app.logger.error(f"csv export: {e}")
        return jsonify({'error': 'csv'}), 500
    
# --- サインアップ (メール) ---
@app.route('/user/signup', methods=['POST'])
def user_signup():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')
    name = data.get('name') or ''
    if not (email and password):
        return jsonify({'error': 'email & password required'}), 400

    try:
        # 1) Service‑Role で “確認済み” ユーザを作成
        res = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True       # ← ここがポイント
        })
        auth_id = res.user.id  # uuid

        # 2) app_users に INSERT（id はシーケンス自動採番）
        inserted = supabase_admin.table('app_users').insert({
            'auth_id': auth_id,
            'name': name,
            'email': email
        }).execute()
        user_id = inserted.data[0]['id']

        return jsonify({'message': 'signed up', 'userId': user_id}), 200

    except Exception as e:
        app.logger.error(f"[signup] {e}")
        return jsonify({'error': 'signup failed'}), 500


# --- サインイン (メール) ---
@app.route('/user/login', methods=['POST'])
def user_login():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')
    if not (email and password):
        return jsonify({'error': 'email & password required'}), 400

    try:
        # 1) anon key で認証
        auth_res = supabase_public.auth.sign_in_with_password({"email": email, "password": password})
        auth_id  = auth_res.user.id

        # 2) アプリ独自 ID を取得
        u = (supabase_admin
             .table('app_users')
             .select('id')
             .eq('auth_id', auth_id)
             .single()
             .execute())
        user_id = u.data['id']

        return jsonify({'userId': user_id}), 200

    except Exception as e:
        app.logger.warning(f"[login failed] {e}")
        return jsonify({'error': 'unauthorized'}), 401
    
    # ===================== OAuth ログイン / メール紐づけ =====================
@app.route('/user/oauth_login', methods=['POST'])
def oauth_login():
    """
    フロントで Supabase OAuth 認証が完了したあと、
    auth_id (uuid) と email を受け取り、app_users と紐づけて userId を返す。
    """
    data   = request.json or {}
    auth_id = data.get('authId')
    email   = (data.get('email') or '').strip().lower()

    if not auth_id or not email:
        return jsonify({'error': 'authId & email required'}), 400
    try:
        # ① app_users に email が既に存在するかチェック
        q = supabase_admin.table('app_users').select('id').eq('email', email).single()
        try:
            existing = q.execute()
            user_id  = existing.data['id']
            # auth_id を更新
            supabase_admin.table('app_users').update({'auth_id': auth_id}).eq('id', user_id).execute()
        except Exception:
            # ② ない場合は新規 INSERT（id はシーケンス自動採番）
            ins = supabase_admin.table('app_users').insert({
                'auth_id': auth_id,
                'email':   email
            }).execute()
            user_id = ins.data[0]['id']

        return jsonify({'userId': user_id}), 200

    except Exception as e:
        app.logger.error(f"[oauth_login] {e}")
        return jsonify({'error': 'oauth login failed'}), 500
    
    # ---------------- LINE LIFF: login ----------------
@app.route('/user/liff_login', methods=['POST'])
def liff_login():
    data = request.json or {}
    line_id = data.get('lineId')
    if not line_id:
        return jsonify({'error':'lineId required'}), 400
    try:
        row = supabase_admin.table('app_users').select('id').eq('line_id', line_id).single().execute()
        if row.data:
            user_id = row.data['id']
        else:
            ins = supabase_admin.table('app_users').insert({'line_id': line_id}).execute()
            user_id = ins.data[0]['id']
        return jsonify({'userId': user_id}), 200
    except Exception as e:
        app.logger.error(f"[liff_login] {e}")
        return jsonify({'error':'liff login failed'}), 500

# ---------------- LINE LIFF: email link ----------------
@app.route('/user/liff_link', methods=['POST'])
def liff_link():
    """
    LINE ID とメールを受け取り、app_users を 1 行に集約する。
    既存行があれば UPDATE、無ければ INSERT。
    """
    data = request.json or {}
    line_id = data.get('lineId')
    email   = (data.get('email') or '').strip().lower()

    if not line_id or not email:
        return jsonify({'error': 'lineId & email required'}), 400

    try:
        # ① email または line_id が一致する行を検索
        q = (supabase_admin
             .table('app_users')
             .select('id')
             .or_(f'email.eq.{email},line_id.eq.{line_id}')
             .limit(1)
             .execute())

        if q.data:
            # ② 既存レコードを上書き
            user_id = q.data[0]['id']
            supabase_admin.table('app_users').update({
                'email':   email,
                'line_id': line_id
            }).eq('id', user_id).execute()
        else:
            # ③ 新規 INSERT
            ins = supabase_admin.table('app_users').insert({
                'email':   email,
                'line_id': line_id
            }).execute()
            user_id = ins.data[0]['id']

        return jsonify({'userId': user_id}), 200

    except Exception as e:
        app.logger.error(f"[liff_link] {e}")
        return jsonify({'error': 'liff link failed'}), 500
    
@app.route("/")
def home():
    return redirect("https://imaginative-meerkat-5675d3.netlify.app/user_login.html", code=302)
    
if __name__ == '__main__':
    # ログにタイムスタンプを出すとデバッグしやすい
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    app.run(host='0.0.0.0', port=4000, debug=False)