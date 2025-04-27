# LINE Mini App + AIコーチングサービス作成マニュアル

【目的】
LINE Mini App上で目標を入力してもらい，AIがパーソナライズドしたコーチングメッセージを送り返すサービスを構築する

---

# 【STEP一覧】

| Step | 内容 |
|:---|:---|
| 1 | LINE DevelopersでLINEログインチャネルを作成 |
| 2 | LIFFアプリ作成 (エンドポイントURLにNetlify URL) |
| 3 | Netlifyにindex.htmlを公開 |
| 4 | Flaskサーバを構築（OpenAI API連携） |
| 5 | ngrokでローカルサーバを公開 |
| 6 | Mini Appからサーバへfetch通信 |
| 7 | CORS対応 (Flask-CORS) |
| 8 | LINE公式アカウントからMini Appを起動（メッセージ送信） |

---

# 【詳細手順】

## STEP1: LINEログインチャネル作成
- LINE Developersでチャネル種別「LINE Login」を選択
- プロバイダー作成

## STEP2: LIFFアプリ作成
- LINE LoginチャネルのLIFFタブから作成
- Scope: profile を指定
- エンドポイントURLにNetlify公開URLを設定

## STEP3: Netlifyにindex.html公開
- LIFF IDを貼り付けたindex.htmlをデプロイ
- Mini App上で目標入力フォームを作成

## STEP4: Flaskサーバ構築
- `/goal`エンドポイントをPOST受信に設定
- OpenAI APIを呼び出し，目標からコーチングメッセージを生成

## STEP5: ngrokで公開
- `ngrok http 5000`でローカルサーバを一時公開
- 発行されたhttps URLをindex.htmlのfetch URLに設定

## STEP6: Mini Appからfetch通信
- 目標をPOSTし，コーチングメッセージを受け取る

## STEP7: CORS対応
- Flaskに`flask-cors` を追加
- `CORS(app)` を追加し，OPTIONSリクエストに対応

## STEP8: LINE公式アカウントからMini App起動
- LINE Official Account Managerからメッセージ送信
- Mini App URLを貼付
- LINEのライン内ブラウザでMini Appを起動


---

# 【よくあるトラブル】

### Q1. LIFF Init failed: channel not found
- liffIdが間違っている
- LINEログインチャネルでLIFF作成しているか見直す

### Q2. fetch失敗 (404)
- fetch先URLに`/goal`が付いていない
- ngrokのURLを見直す

### Q3. OPTIONS 404
- CORSに対応していない
- `pip install flask-cors`、`CORS(app)`を追加

### Q4. 送信は成功したが後が続かない
- FlaskでPOST受け取りを立て直しているか確認


---

# 【まとめ】

- LINEとLIFFの連携を確実にする
- ngrokとNetlifyのURLを管理する
- FlaskサーバをCORS対応で最新にする
- 一つ一つログを確認しながら進める

---