from utils.binance import get_top_symbols, check_15m_ma90_disparity
from utils.telegram import send_telegram_message
import time

def report_15m_ma90_outliers():
    try:
        symbols = get_top_symbols(20)
        msg = "🧭 *15분봉 MA90 이격도 알림*\n"
        msg += "_이격도 < 98% 또는 > 102% 종목만 표시_\n\n"

        found = False
        for symbol in symbols:
            data = check_15m_ma90_disparity(symbol)
            if data:
                found = True
                msg += f"*{symbol}*\n"
                msg += f"   ├ 현재가: `{round(data['price'], 4)}`\n"
                msg += f"   ├ MA90: `{round(data['ma90'], 4)}`\n"
                msg += f"   └ 이격도: `{round(data['disparity'], 2)}%`\n\n"

        if found:
            send_telegram_message(msg)
        else:
            send_telegram_message("🤷‍♂️ 조건을 만족하는 종목이 없습니다. (15분봉 MA90 기준)")

    except Exception as e:
        send_telegram_message(f"⚠️ 리포트 실패: {str(e)}")

def ma90_watcher_loop():
    while True:
        try:
            symbols = get_top_symbols(20)
            for symbol in symbols:
                data = check_15m_ma90_disparity(symbol)
                if data:
                    msg = f"🚨 *{symbol}* 15분봉 MA90 이격도 이탈 감지\n"
                    msg += f"   ├ 현재가: `{round(data['price'], 4)}`\n"
                    msg += f"   ├ MA90: `{round(data['ma90'], 4)}`\n"
                    msg += f"   └ 이격도: `{round(data['disparity'], 2)}%`\n"
                    send_telegram_message(msg)

        except Exception as e:
            print("[15분봉 MA90 감시 오류]", e)

        time.sleep(900)  # 15분마다 실행