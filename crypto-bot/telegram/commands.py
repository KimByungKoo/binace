from strategy.ma90_disparity import report_15m_ma90_outliers
from order_manager import auto_trade_from_signal
from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines, client, get_top_symbols
from strategy.trade_executor import daily_stats, open_trades, CONFIG, analyze_market_phase, calculate_volatility
from datetime import datetime
import pandas as pd
import numpy as np

from strategy.spike_disparity import report_spike_disparity
from dotenv import load_dotenv
import requests
import time
import os

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def generate_detailed_report():
    """
    상세 거래 리포트 생성
    """
    try:
        # 계좌 정보
        account = client.futures_account()
        balance = float(account['totalWalletBalance'])
        unrealized_pnl = float(account['totalUnrealizedProfit'])
        
        # 수익률 계산
        if daily_stats["start_balance"]:
            daily_return = (balance - daily_stats["start_balance"]) / daily_stats["start_balance"] * 100
        else:
            daily_return = 0
            
        # 승률 계산
        total_trades = daily_stats["total_trades"]
        win_rate = (daily_stats["winning_trades"] / total_trades * 100) if total_trades > 0 else 0
        
        # 시간대별 통계
        hour_stats = daily_stats["trading_hours_stats"]
        best_hour = max(hour_stats.items(), key=lambda x: x[1]["profit"] / x[1]["trades"])[0] if hour_stats else None
        worst_hour = min(hour_stats.items(), key=lambda x: x[1]["profit"] / x[1]["trades"])[0] if hour_stats else None
        
        report = f"""
📊 *상세 거래 리포트*
├ *계좌 정보*
│  ├ 현재 잔고: `{round(balance, 2)} USDT`
│  ├ 미실현 손익: `{round(unrealized_pnl, 2)} USDT`
│  └ 일일 수익률: `{round(daily_return, 2)}%`
│
├ *거래 통계*
│  ├ 총 거래 횟수: `{total_trades}회`
│  ├ 승률: `{round(win_rate, 1)}%`
│  ├ 총 수익: `{round(daily_stats['total_profit'], 2)} USDT`
│  ├ 총 손실: `{round(daily_stats['total_loss'], 2)} USDT`
│  └ 연속 손실: `{daily_stats['consecutive_losses']}회`
│
├ *최고/최저 거래*
"""
        # 최고/최저 거래 정보 추가
        if daily_stats["best_trade"]:
            report += f"│  ├ 최고 수익: `{round(daily_stats['best_trade']['pnl'], 2)} USDT` ({daily_stats['best_trade']['symbol']})\n"
        else:
            report += "│  ├ 최고 수익: 없음\n"
            
        if daily_stats["worst_trade"]:
            report += f"│  └ 최대 손실: `{round(daily_stats['worst_trade']['pnl'], 2)} USDT` ({daily_stats['worst_trade']['symbol']})\n"
        else:
            report += "│  └ 최대 손실: 없음\n"
        
        # 시간대별 분석 추가
        best_hour_str = f"{best_hour:02d}:00 UTC" if best_hour is not None else "없음"
        worst_hour_str = f"{worst_hour:02d}:00 UTC" if worst_hour is not None else "없음"
        
        report += f"""
├ *시간대별 분석*
│  ├ 최적 시간대: `{best_hour_str}`
│  └ 최악 시간대: `{worst_hour_str}`
│
└ *현재 포지션*: `{len(open_trades)}개`
"""
        
        # 현재 포지션 정보 추가
        if open_trades:
            report += "\n*보유 포지션*\n"
            for symbol, trade in open_trades.items():
                pnl = ((trade['current_price'] - trade['entry_price']) / trade['entry_price'] * 100) if trade['direction'] == "long" else ((trade['entry_price'] - trade['current_price']) / trade['entry_price'] * 100)
                report += f"├ {symbol}: {trade['direction']} ({round(pnl, 2)}%)\n"
                report += f"│  ├ 진입가: `{round(trade['entry_price'], 4)}`\n"
                report += f"│  ├ 현재가: `{round(trade['current_price'], 4)}`\n"
                report += f"│  ├ TP: `{round(trade['tp'], 4)}`\n"
                report += f"│  └ SL: `{round(trade['sl'], 4)}`\n"
        
        return report
        
    except Exception as e:
        return f"❌ 리포트 생성 중 오류 발생: {str(e)}"

def analyze_market_conditions(symbol: str = None):
    """
    시장 상황 분석 리포트 생성
    """
    try:
        if symbol:
            symbols = [symbol]
        else:
            symbols = get_top_symbols(5)  # 상위 5개 코인만 분석
            
        report = f"🔍 *시장 분석 리포트*\n"
        
        for sym in symbols:
            df = get_1m_klines(sym, interval="1h", limit=24)
            if df.empty:
                continue
                
            # 변동성 계산
            volatility = calculate_volatility(df)
            
            # 시장 단계 분석
            market_phase = analyze_market_phase(df)
            
            # RSI 계산
            df['rsi'] = calculate_rsi(df)
            current_rsi = df['rsi'].iloc[-1]
            
            # 볼린저 밴드
            df['bb_middle'] = df['close'].rolling(20).mean()
            df['bb_std'] = df['close'].rolling(20).std()
            df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
            df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
            
            # 현재가가 볼린저 밴드 내에서 어디에 위치하는지
            current_price = df['close'].iloc[-1]
            bb_position = (current_price - df['bb_lower'].iloc[-1]) / (df['bb_upper'].iloc[-1] - df['bb_lower'].iloc[-1]) * 100
            
            report += f"\n*{sym} 분석*\n"
            report += f"├ 현재가: `{round(current_price, 4)}`\n"
            report += f"├ 변동성: `{round(volatility * 100, 2)}%`\n"
            report += f"├ RSI: `{round(current_rsi, 1)}`\n"
            report += f"├ 시장단계: `{market_phase}`\n"
            report += f"└ BB 위치: `{round(bb_position, 1)}%`\n"
            
            # 거래 추천
            if current_rsi < 30 and bb_position < 20:
                report += f"💡 *롱 진입 고려*\n"
            elif current_rsi > 70 and bb_position > 80:
                report += f"💡 *숏 진입 고려*\n"
                
        return report
        
    except Exception as e:
        return f"❌ 시장 분석 중 오류 발생: {str(e)}"

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

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

                print(f"[텔레그램 메시지 수신] {message}")
                
                if message == "/report":
                    report = generate_detailed_report()
                    send_telegram_message(report)
                elif message == "/market":
                    report = analyze_market_conditions()
                    send_telegram_message(report)
                elif message.startswith("/analyze "):
                    symbol = message.split()[1].upper()
                    report = analyze_market_conditions(symbol)
                    send_telegram_message(report)
                elif message == "/ma90":
                    send_telegram_message("🔍 MA90 이격도 리포트 생성 중...")
                    report_15m_ma90_outliers()
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