import websocket
import json
import requests
import time
import os
import threading
from flask import Flask

# =========================
# FLASK
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def iniciar_web():
    threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 10000))
        ),
        daemon=True
    ).start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "5m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("❌ Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

klines = []
trend = 0
last_candle_time = None

# 🔥 MEMORIA REAL
ultima_senal_historica = None
primera_senal_valida = False

# =========================
# 💰 TRADING SIMULADO
# =========================
capital = 100.0
posicion = None
entry_price = 0.0
trades = 0
FEE = 0.0005

# =========================
# TELEGRAM
# =========================
def enviar_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=3
        )
    except:
        pass

# =========================
# EMA / SMA
# =========================
def ema(src, length):
    ema_vals = []
    k = 2 / (length + 1)
    for i, v in enumerate(src):
        ema_vals.append(v if i == 0 else v * k + ema_vals[i - 1] * (1 - k))
    return ema_vals

def sma(src, length):
    return [
        None if i < length - 1
        else sum(src[i - length + 1:i + 1]) / length
        for i in range(len(src))
    ]

# =========================
# HISTÓRICO
# =========================
def cargar_historico():
    global klines, last_candle_time

    data = requests.get(
        f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=500"
    ).json()

    klines = [{
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4]),
        "time": k[6]
    } for k in data]

    last_candle_time = klines[-1]["time"]

    print("📊 Histórico cargado", flush=True)

# =========================
# 🔥 DETECTAR ÚLTIMA SEÑAL REAL DEL HISTÓRICO
# =========================
def obtener_ultima_senal_real():
    global trend

    if len(klines) < 100:
        return None

    close = [k["close"] for k in klines]
    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]

    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen = [ohlc4[0]/2]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i]+haOpen[i-1])/2)

    haC = [
        (ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4
        for i in range(len(close))
    ]

    L=25

    EMA1=ema(haC,L)
    EMA2=ema(EMA1,L)
    EMA3=ema(EMA2,L)
    TMA1=[3*EMA1[i]-3*EMA2[i]+EMA3[i] for i in range(len(close))]

    EMA4=ema(TMA1,L)
    EMA5=ema(EMA4,L)
    EMA6=ema(EMA5,L)
    TMA2=[3*EMA4[i]-3*EMA5[i]+EMA6[i] for i in range(len(close))]

    mavi=TMA1
    kirmizi=TMA2

    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    ultima = None
    temp_trend = 0

    for i in range(1, len(close)):

        if dist_media[i] is None:
            continue

        cruce_up = mavi[i] > kirmizi[i] and mavi[i-1] <= kirmizi[i-1]
        cruce_down = mavi[i] < kirmizi[i] and mavi[i-1] >= kirmizi[i-1]

        confirm_up = mavi[i] > mavi[i-1]
        confirm_down = mavi[i] < mavi[i-1]

        filtro = dist[i] > dist_media[i]*0.3

        if cruce_up and confirm_up and filtro and temp_trend != 1:
            temp_trend = 1
            ultima = "BUY"

        elif cruce_down and confirm_down and filtro and temp_trend != -1:
            temp_trend = -1
            ultima = "SELL"

    trend = temp_trend
    return ultima

# =========================
# =========================
# SINCRONIZACIÓN
# =========================
def sincronizar_trend():
    global ultima_senal_historica

    ultima_senal_historica = obtener_ultima_senal_real()

    if ultima_senal_historica == "BUY":
        ultima_txt = "BUY 🔼"
        esperar = "SELL 🔽"

    elif ultima_senal_historica == "SELL":
        ultima_txt = "SELL 🔽"
        esperar = "BUY 🔼"

    else:
        ultima_txt = "None"
        esperar = "BUY 🔼 / SELL 🔽"

    enviar_telegram(
        f"📌 Última señal detectada: {ultima_txt}\n"
        f"⏳ Esperando señal {esperar} para operar..."
    )

# =========================
# SEÑALES (TIEMPO REAL)
# =========================
def calcular_senal():
    global trend

    if len(klines) < 100:
        return None

    close = [k["close"] for k in klines]
    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]

    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen = [ohlc4[0]/2]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i]+haOpen[i-1])/2)

    haC = [
        (ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4
        for i in range(len(close))
    ]

    L=38

    EMA1=ema(haC,L)
    EMA2=ema(EMA1,L)
    EMA3=ema(EMA2,L)
    TMA1=[3*EMA1[i]-3*EMA2[i]+EMA3[i] for i in range(len(close))]

    EMA4=ema(TMA1,L)
    EMA5=ema(EMA4,L)
    EMA6=ema(EMA5,L)
    TMA2=[3*EMA4[i]-3*EMA5[i]+EMA6[i] for i in range(len(close))]

    mavi=TMA1
    kirmizi=TMA2

    i=-1

    cruce_up = mavi[i] > kirmizi[i] and mavi[i-1] <= kirmizi[i-1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i-1] >= kirmizi[i-1]

    confirm_up = mavi[i] > mavi[i-1]
    confirm_down = mavi[i] < mavi[i-1]

    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    if dist_media[i] is None:
        return None

    filtro = dist[i] > dist_media[i]*0.3

    if cruce_up and confirm_up and filtro and trend != 1:
        trend = 1
        return "BUY"

    if cruce_down and confirm_down and filtro and trend != -1:
        trend = -1
        return "SELL"

    return None

# =========================
# TRADING
# =========================
def ejecutar_trade(señal, precio):
    global capital, posicion, entry_price, trades

    if posicion is not None:
        if posicion == "BUY":
            pnl = (precio - entry_price) / entry_price
        else:
            pnl = (entry_price - precio) / entry_price

        capital *= (1 + pnl)
        capital *= (1 - FEE)

        trades += 1

        enviar_telegram(
            f"❌ CIERRE {posicion}\n"
            f"💰 Capital: {capital:.2f} USDT\n"
            f"📊 PnL: {pnl*100:.2f}%\n"
            f"🔢 Trades: {trades}"
        )

    posicion = señal
    entry_price = precio
    capital *= (1 - FEE)

    enviar_telegram(
        f"🚀 APERTURA {señal}\n"
        f"💰 Precio: {precio}\n"
        f"💼 Capital: {capital:.2f} USDT"
    )

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, primera_senal_valida

    data = json.loads(message)
    k = data['k']

    if not k["x"]:
        return

    candle_time = k["T"]

    if candle_time <= last_candle_time:
        return

    last_candle_time = candle_time

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "time": candle_time
    }

    klines.append(candle)
    if len(klines) > 500:
        klines.pop(0)

    señal = calcular_senal()

    if not señal:
        return

    # 🔥 BLOQUEO DEFINITIVO
    if not primera_senal_valida:
        if señal != ultima_senal_historica:
            primera_senal_valida = True
        else:
            return

    precio = candle["close"]

    print(f"🚀 {señal} | {precio}", flush=True)

    ejecutar_trade(señal, precio)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT PERFECTO ACTIVADO", flush=True)

    iniciar_web()

    # 🔥 Mensaje Telegram
    enviar_telegram("🤖 BOT PERFECTO ACTIVADO")

    cargar_historico()
    sincronizar_trend()

    websocket.WebSocketApp(
        f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}",
        on_message=on_message
    ).run_forever()
