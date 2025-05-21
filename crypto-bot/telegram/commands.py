from strategy.ma90_disparity import report_15m_ma90_outliers
from utils.telegram import send_telegram_message
import requests
import time
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def telegram_command_listener():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            if offset:
                url += f"?offset={offset}"
            res = requests.get(url).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                if "message" not in update:
                    continue
                message = update["message"].get("text", "").strip().lower()

                if message == "/ma90":
                    send_telegram_message("🔍 MA90 이격도 리포트 생성 중...")
                    report_15m_ma90_outliers()

        except Exception as e:
            print("[텔레그램 명령 오류]", e)
        time.sleep(5)