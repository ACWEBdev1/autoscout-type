import json
import time
import random
import os
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# === 設定項目 ===
TYPE_LOGIN_URL = "https://type.jp/login/" 
TYPE_SEARCH_URL = "https://type.jp/search/" 
MAX_CANDIDATES = 200

# n8nのExecute Command経由で実行されるため、判断基準テキストはファイルから読み込む（base64デコード対策）
try:
    with open("/tmp/doc.txt", "r", encoding="utf-8") as f:
        DOC_TEXT = f.read()
except FileNotFoundError:
    DOC_TEXT = "ローカル環境テスト用スカウト判断基準..."

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TYPE_USER_ID = os.environ.get("TYPE_USER_ID", "")
TYPE_PASSWORD = os.environ.get("TYPE_PASSWORD", "")

def random_sleep(min_sec=2, max_sec=5):
    """人間らしいランダムな待機時間を挿入"""
    time.sleep(random.uniform(min_sec, max_sec))

def ask_gemini(doc_text, resume_text):
    if not GEMINI_API_KEY:
        # デバッグログは標準エラー出力（stderr）に出すとn8nの標準出力JSONを汚染しない
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
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        try:
            page.goto(TYPE_LOGIN_URL)
            random_sleep(2, 4)
            page.fill('input[name="userId"]', TYPE_USER_ID)
            random_sleep(1, 2)
            page.fill('input[name="password"]', TYPE_PASSWORD)
            random_sleep(1, 2)
            page.click('button:has-text("ログイン"), input[type="submit"]')
            page.wait_for_load_state("networkidle")
            random_sleep(3, 5)

            page.goto(TYPE_SEARCH_URL)
            page.wait_for_load_state("networkidle")
            random_sleep(3, 5)

            processed_count = 0

            while processed_count < MAX_CANDIDATES:
                candidates = page.locator('.candidate-list-item')
                count = candidates.count()

                if count == 0:
                    break

                for i in range(count):
                    if processed_count >= MAX_CANDIDATES:
                        break

                    candidate = candidates.nth(i)
                    candidate.click()
                    random_sleep(2, 4)

                    modal = page.locator('[id^="boss-modal-control-"]').first
                    modal.wait_for(state="visible", timeout=10000)
                    
                    modal_id = modal.get_attribute("id")
                    candidate_id = modal_id.replace("boss-modal-control-", "") if modal_id else f"unknown_{processed_count}"
                    
                    resume_text = modal.inner_text()
                    
                    decision_data = ask_gemini(DOC_TEXT, resume_text)

                    try:
                        if decision_data.get('decision') == "Send":
                            if not decision_data.get('scout_text'):
                                raise ValueError("スカウト文が空です。")
                                
                            modal.locator('button:has-text("スカウト送信")').click()
                            random_sleep(2, 4)
                            page.fill('textarea.scout-message-body', decision_data['scout_text'])
                            random_sleep(1, 2)
                            page.locator('button:has-text("送信")').click()
                            random_sleep(2, 4)
                            
                            success_close = page.locator('button:has-text("閉じる")')
                            if success_close.count() > 0:
                                success_close.first.click()
                                
                            results_log.append({
                                "status": "Sent",
                                "candidate_id": candidate_id,
                                "reason": decision_data.get('reason'),
                                "scout_text": decision_data.get('scout_text')
                            })
                        else:
                            exclude_btn = modal.locator('button:has-text("除外者へ")')
                            if exclude_btn.is_visible():
                                exclude_btn.click()
                                random_sleep(2, 3)
                            results_log.append({
                                "status": "Skipped",
                                "candidate_id": candidate_id,
                                "reason": decision_data.get('reason'),
                                "scout_text": ""
                            })
                            
                    except Exception as action_e:
                        results_log.append({
                            "status": "Error",
                            "candidate_id": candidate_id,
                            "reason": str(action_e),
                            "scout_text": ""
                        })
                    
                    close_btn = page.locator('button:has-text("閉じる")')
                    if close_btn.count() > 0 and close_btn.first.is_visible():
                        close_btn.first.click()
                        random_sleep(1, 2)
                        
                    processed_count += 1

                next_btn = page.locator('a:has-text("次へ")')
                if next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_load_state("networkidle")
                    random_sleep(3, 6)
                else:
                    break

        except PlaywrightTimeoutError as e:
            pass # タイムアウトはエラーログを出さずに終了へ
        finally:
            browser.close()
            
    return {"status": "success", "processed": processed_count, "results": results_log}

if __name__ == "__main__":
    out = main()
    # n8nのExecute Commandノードで受け取るために、結果のみを標準出力（JSON）としてプリントする
    print(json.dumps(out))
