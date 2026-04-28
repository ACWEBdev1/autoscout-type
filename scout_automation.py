import json
import time
import random
import os
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# === 設定項目 ===
TYPE_LOGIN_URL = "https://hr.type.jp/" 
TYPE_SCOUT_URL = "https://hr.type.jp/#/scouts/" 
MAX_CANDIDATES = 200

# ユーザー提供のログイン情報（環境変数優先）
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TYPE_USER_ID = os.environ.get("TYPE_USER_ID", "hr216872")
TYPE_PASSWORD = os.environ.get("TYPE_PASSWORD", "Xendouoj1029type")

# スプレッドシート（n8n経由）から渡される動的設定
TYPE_JOB_ID = ""
TYPE_CONDITION_NAME = ""
TYPE_TEMPLATE_NAME = "XENDOU用 初回※共通" # デフォルト値

try:
    with open("/tmp/settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
        TYPE_JOB_ID = str(settings.get("TYPE_JOB_ID", "")).strip()
        TYPE_CONDITION_NAME = str(settings.get("TYPE_CONDITION_NAME", "")).strip()
        template = settings.get("TYPE_TEMPLATE_NAME", "").strip()
        if template:
            TYPE_TEMPLATE_NAME = template
except FileNotFoundError:
    print("Warning: /tmp/settings.json が見つかりませんでした。")

# n8nのGoogle Docsノードから保存された判断基準テキストを読み込む
try:
    with open("/tmp/doc.txt", "r", encoding="utf-8") as f:
        DOC_TEXT = f.read()
except FileNotFoundError:
    DOC_TEXT = "ローカル環境テスト用スカウト判断基準..."

def random_sleep(min_sec=2, max_sec=5):
    """人間らしいランダムな待機時間を挿入"""
    time.sleep(random.uniform(min_sec, max_sec))

def ask_gemini(doc_text, resume_text):
    if not GEMINI_API_KEY:
        import sys
        print("警告: GEMINI_API_KEYが設定されていません。Skip扱いとします。", file=sys.stderr)
        return {"decision": "Skip", "reason": "No API Key", "scout_text": ""}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
以下の「スカウト判断基準」と「候補者のレジュメ情報」をすべて読んだ上で、スカウト可否を判定してください。
以下のフォーマットに従う純粋なJSON文字列でのみ出力してください。
{{
    "decision": "Send" または "Skip",
    "reason": "判定理由の簡潔な説明",
    "scout_text": "decisionがSendの場合のスカウト文章。Skipの場合は空文字でよい。"
}}

【スカウト判断基準】
{doc_text}

【候補者のレジュメ情報】
{resume_text}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        result = response.json()
        text_response = result["candidates"][0]["content"]["parts"][0]["text"]
        text_response = text_response.replace('```json', '').replace('```', '').strip()
        return json.loads(text_response)
    except Exception as e:
        import sys
        print(f"Gemini API実行エラー: {e}", file=sys.stderr)
        return {"decision": "Skip", "reason": f"API Error: {str(e)}", "scout_text": ""}

def main():
    results_log = []
    
    # 必須パラメータチェック
    if not TYPE_JOB_ID or not TYPE_CONDITION_NAME:
        return {
            "status": "error", 
            "message": f"TYPE_JOB_ID または TYPE_CONDITION_NAME が設定されていません。現在の値: JOB_ID='{TYPE_JOB_ID}', CONDITION='{TYPE_CONDITION_NAME}'", 
            "results": []
        }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        try:
            # === 1. ログイン ===
            page.goto(TYPE_LOGIN_URL)
            page.wait_for_load_state("networkidle")
            random_sleep(2, 4)
            
            # ログインフォームに入力
            page.fill('input[type="text"], input[name="loginId"], input[placeholder*="ID"]', TYPE_USER_ID)
            random_sleep(1, 2)
            page.fill('input[type="password"], input[name="password"]', TYPE_PASSWORD)
            random_sleep(1, 2)
            page.click('button:has-text("ログイン"), button:has-text("Login")')
            page.wait_for_load_state("networkidle")
            random_sleep(4, 6)

            # === 2. スカウト画面へ遷移 ===
            page.goto(TYPE_SCOUT_URL)
            page.wait_for_load_state("networkidle")
            random_sleep(4, 6)

            # === 3. 対象の求人IDブロックを探し「保存した検索条件」をクリック ===
            # スクリーンショットに合わせて、正確なクラス名と属性（data-test）に修正しました
            job_block = page.locator('.boss-scoutlike-item').filter(has=page.locator(f'h2:has-text("{TYPE_JOB_ID}")')).first
            job_block.locator('[data-test="search-save-condition-link"]').first.click()
            page.wait_for_load_state("networkidle")
            random_sleep(3, 5)

            # === 4. 左サイドバーから指定された検索条件名をクリック ===
            page.locator(f'li:has-text("{TYPE_CONDITION_NAME}"), a:has-text("{TYPE_CONDITION_NAME}")').first.click()
            page.wait_for_load_state("networkidle")
            random_sleep(4, 6)

            processed_count = 0

            # === 5. 人材一覧のループ処理 ===
            while processed_count < MAX_CANDIDATES:
                # 候補者の行（画像より、.boss-scoutlike-item や一覧の各要素）
                candidates = page.locator('.boss-scoutlike-item-list-item, .candidate-list-item, div[class*="item"]')
                # リストが読み込まれるまで少し待機
                page.wait_for_timeout(2000)
                
                count = candidates.count()
                if count == 0:
                    break

                # スカウトや除外を行うと一覧から消える仕様のため、常に「一番上の候補者」を処理する
                candidate = candidates.nth(0)
                
                # 詳細を見るボタンを取得
                detail_btn = candidate.locator('button:has-text("詳細を見る"), a:has-text("詳細を見る"), span:has-text("詳細を見る")').first
                if not detail_btn.is_visible():
                    break # 候補者がもういないか、ボタンが見つからない場合

                # IDを取得（表示されているテキストから）
                candidate_text = candidate.inner_text()
                # 雑に最初の数十文字をID代わりにする
                candidate_id = candidate_text[:30].replace("\n", " ").strip()

                detail_btn.click()
                random_sleep(3, 5)

                # === 6. モーダル（レジュメ）解析 ===
                modal = page.locator('.reveal-overlay[style*="display: block"], [role="dialog"]').first
                modal.wait_for(state="visible", timeout=10000)
                
                resume_text = modal.inner_text()
                
                # AIに判定させる
                decision_data = ask_gemini(DOC_TEXT, resume_text)

                # === 7. モーダルを閉じる ===
                close_btn = modal.locator('button[class*="close"], span:has-text("×"), a[class*="close"]').first
                if close_btn.is_visible():
                    close_btn.click()
                random_sleep(2, 4)

                try:
                    if decision_data.get('decision') == "Send":
                        if not decision_data.get('scout_text'):
                            raise ValueError("スカウト文が空です。")
                        
                        # === 8. スカウトボタン押下 ===
                        scout_btn = candidate.locator('button:has-text("スカウト"), a:has-text("スカウト"), span:has-text("スカウト")').first
                        scout_btn.click()
                        page.wait_for_load_state("networkidle")
                        random_sleep(4, 6)

                        # URLが変わり、スカウト送信画面になる
                        # ① テンプレート選択
                        page.select_option('select[name*="template"], select', label=TYPE_TEMPLATE_NAME)
                        random_sleep(3, 5)

                        # ② 本文テキストエリアへの追記
                        textarea = page.locator('textarea').first
                        current_text = textarea.input_value()
                        
                        insert_target = "【魅力的に感じたご経験】"
                        if insert_target in current_text:
                            # ターゲット文字列の直後に改行とスカウト文を挿入
                            new_text = current_text.replace(insert_target, f"{insert_target}\n{decision_data['scout_text']}")
                        else:
                            # 見つからない場合は一番下に追加
                            new_text = current_text + "\n\n" + decision_data['scout_text']
                            
                        textarea.fill(new_text)
                        random_sleep(1, 2)

                        # ③ スカウト特典のチェックボックスをクリック
                        check_label = page.locator('text="以下のスカウト特典が設定されています"')
                        if check_label.is_visible():
                            check_label.locator('xpath=preceding-sibling::input[@type="checkbox"]').first.check()

                        # ④ 送信内容を確認するボタン
                        page.locator('button:has-text("送信内容を確認する"), a:has-text("送信内容を確認する")').click()
                        random_sleep(3, 5)

                        # ⑤ この内容で送信するボタン
                        page.locator('button:has-text("この内容で送信する"), a:has-text("この内容で送信する")').click()
                        page.wait_for_load_state("networkidle")
                        random_sleep(4, 6)

                        # ⑥ 検索条件に再度クリックして戻る
                        page.locator(f'li:has-text("{TYPE_CONDITION_NAME}"), a:has-text("{TYPE_CONDITION_NAME}")').first.click()
                        page.wait_for_load_state("networkidle")
                        random_sleep(4, 6)

                        results_log.append({
                            "status": "Sent",
                            "candidate_id": candidate_id,
                            "reason": decision_data.get('reason'),
                            "scout_text": decision_data.get('scout_text')
                        })
                    else:
                        # === 9. Skip判定の場合、「除外者へ」を押す ===
                        exclude_btn = candidate.locator('button:has-text("除外者へ"), a:has-text("除外者へ")').first
                        if exclude_btn.is_visible():
                            exclude_btn.click()
                            random_sleep(2, 4)
                            # ポップアップ確認が出る場合に対応
                            confirm_btn = page.locator('button:has-text("OK"), button:has-text("はい")')
                            if confirm_btn.is_visible():
                                confirm_btn.first.click()
                                random_sleep(2, 4)
                            
                        results_log.append({
                            "status": "Skipped",
                            "candidate_id": candidate_id,
                            "reason": decision_data.get('reason'),
                            "scout_text": ""
                        })
                        
                except Exception as action_e:
                    import sys
                    print(f"アクション実行エラー: {action_e}", file=sys.stderr)
                    results_log.append({
                        "status": "Error",
                        "candidate_id": candidate_id,
                        "reason": str(action_e),
                        "scout_text": ""
                    })
                    
                processed_count += 1
                random_sleep(2, 4)

        except PlaywrightTimeoutError as e:
            import sys
            print(f"タイムアウトエラー: {e}", file=sys.stderr)
        finally:
            browser.close()
            
    return {"status": "success", "processed": processed_count, "results": results_log}

if __name__ == "__main__":
    out = main()
    print(json.dumps(out))
