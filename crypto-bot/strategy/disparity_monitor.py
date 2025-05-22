import time
import threading
from utils.binance import get_top_symbols
from strategy.disparity_monitor import check_disparity

def run_disparity_monitor():
    sent = {}

    while True:
        top_symbols = get_top_symbols(cfg["top_n"])
        for symbol in top_symbols:
            result = check_disparity(symbol)
            if result:
                key = f"{symbol}"
                if sent.get(key) != int(result["disparity"]):
                    msg = (
                        f"📊 *{symbol}* 5분봉 이격 감지!\n"
                        f"   ├ 현재가: `{round(result['close'], 4)}`\n"
                        f"   ├ MA{cfg['ma_window']}: `{round(result['ma'], 4)}`\n"
                        f"   └ 이격도: `{round(result['disparity'], 2)}%` 🚨"
                    )
                    send_telegram_message(msg)
                    sent[key] = int(result["disparity"])

        time.sleep(cfg["check_interval_sec"])
        