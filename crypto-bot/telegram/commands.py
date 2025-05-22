from strategy.ma90_disparity import report_15m_ma90_outliers
from order_manager import auto_trade_from_signal
from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines

from strategy.spike_disparity import report_spike_disparity
from dotenv import load_dotenv
import requests
import time
import os

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def telegram_command_listener():
    
    print("[텔레그램 TOKEN]",TELEGRAM_TOKEN )
    print("[텔레그램 CHAT]",TELEGRAM_CHAT_ID )
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

                print("[텔레그램 message]",message )
                
                
                if message == "/ma90":
                    send_telegram_message("🔍 MA90 이격도 리포트 생성 중...")
                    report_15m_ma90_outliers()
                # telegram/commands.py 안에 추가
                elif message == "/spike":
                    send_telegram_message("🔍 스파이크 이격도 리포트 생성 중...")
                    report_spike_disparity()
                elif message.startswith("/manual"):
                    parts = message.split()
                    if len(parts) == 3:
                        symbol = parts[1].upper()
                        direction = parts[2].lower()

                        df = get_1m_klines(symbol, interval='1m', limit=5)
                        if df.empty:
                            send_telegram_message(f"❌ {symbol} 데이터 불러오기 실패")
                            continue

                        entry_price = float(df['close'].iloc[-1])
                        take_profit = entry_price * 1.02
                        stop_loss = entry_price * 0.99

                        mock_signal = {
                            "symbol": symbol,
                            "direction": direction,
                            "price": entry_price,
                            "take_profit": take_profit,
                            "stop_loss": stop_loss
                        }

                        send_telegram_message(f"🧪 수동 진입 테스트: {symbol} {direction.upper()} @ {round(entry_price, 4)}")
                        auto_trade_from_signal(mock_signal)
                    else:
                        send_telegram_message("사용법: /manual BTCUSDT long")


        except Exception as e:
            print("[텔레그램 명령 오류]", e)
        time.sleep(5)