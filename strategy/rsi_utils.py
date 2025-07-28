import pandas as pd

def calculate_rsi_binance(prices, period=14):
    """
    바이낸스/트레이딩뷰와 거의 동일한 방식으로 RSI를 계산합니다.
    - Wilder's Smoothing Method (특수한 EMA)를 사용합니다.
    - pandas 라이브러리를 사용하여 정확성을 높입니다.
    """
    if len(prices) < period:
        return None # 계산에 필요한 데이터가 충분하지 않음

    # 가격 데이터를 pandas Series로 변환
    close_prices = pd.Series(prices)

    # 가격 변동 계산
    delta = close_prices.diff()

    # 상승분과 하락분 분리
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    # Wilder's Smoothing을 사용한 평균 계산 (alpha = 1 / period)
    # com (center of mass) = period - 1 과 동일
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    # RS (Relative Strength) 계산
    rs = avg_gain / avg_loss

    # RSI 계산
    rsi = 100 - (100 / (1 + rs))

    # 마지막 RSI 값 반환 (Series가 아닌 단일 float 값)
    return rsi.iloc[-1]