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
EMA_LENGTH = 38

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID"))     # GRUPO
TELEGRAM_ADMIN_ID = str(os.getenv("TELEGRAM_ADMIN_ID"))   # PRIVADO

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not TELEGRAM_ADMIN_ID:
    raise ValueError("❌ Faltan variables de entorno")

klines = []
trend = 0
last_candle_time = None

ultima_senal_historica = None
primera_senal_valida = False

bot_pausado = False
ultimo_precio = 0

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
def enviar_telegram(msg, chat_id=None, botones=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        data = {
            "chat_id": chat_id if chat_id else TELEGRAM_CHAT_ID,
            "text": msg
        }

        if botones:
            data["reply_markup"] = json.dumps({
                "inline_keyboard": botones
            })

        requests.post(url, data=data, timeout=3)
    except:
        pass

def enviar_panel():
    botones = [
        [{"text": "📊 Estado", "callback_data": "status"}],
        [{"text": "🟡 Cerrar operación", "callback_data": "close"}],
        [{"text": "🔴 Pausar bot", "callback_data": "pause"}],
        [{"text": "🟢 Reanudar bot", "callback_data": "resume"}],
    ]

    enviar_telegram("🎛 PANEL DE CONTROL", TELEGRAM_ADMIN_ID, botones)

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

# =========================
# DETECTAR ÚLTIMA SEÑAL
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

    haC = [(ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L = EMA_LENGTH

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
# SEÑALES
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

    haC = [(ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L = EMA_LENGTH

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
        pnl = (precio - entry_price) / entry_price if posicion == "BUY" else (entry_price - precio) / entry_price
        capital *= (1 + pnl)
        capital *= (1 - FEE)
        trades += 1

        enviar_telegram(f"❌ CIERRE {posicion}\n💰 {capital:.2f} USDT\n📊 {pnl*100:.2f}%\n🔢 {trades}")

    posicion = señal
    entry_price = precio
    capital *= (1 - FEE)

    enviar_telegram(f"🚀 APERTURA {señal}\n💰 {precio}\n💼 {capital:.2f} USDT")

# =========================
# BOTONES
# =========================
def escuchar_botones():
    global bot_pausado, posicion

    offset = None

    while True:
        try:
            res = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"timeout":10,"offset":offset}
            ).json()

            for update in res["result"]:
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    data = update["callback_query"]["data"]
                    chat_id = str(update["callback_query"]["message"]["chat"]["id"])

                    if chat_id != TELEGRAM_ADMIN_ID:
                        continue

                    if data == "status":
                        enviar_telegram(f"📊 Capital: {capital:.2f}\n📍 Posición: {posicion}", TELEGRAM_ADMIN_ID)

                    elif data == "close" and posicion:
                        ejecutar_trade("SELL" if posicion=="BUY" else "BUY", ultimo_precio)

                    elif data == "pause":
                        bot_pausado = True
                        enviar_telegram("🔴 Bot pausado", TELEGRAM_ADMIN_ID)

                    elif data == "resume":
                        bot_pausado = False
                        enviar_telegram("🟢 Bot reanudado", TELEGRAM_ADMIN_ID)

        except:
            pass

        time.sleep(2)

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, primera_senal_valida, ultimo_precio

    data = json.loads(message)
    k = data['k']

    if not k["x"]:
        return

    if k["T"] <= last_candle_time:
        return

    last_candle_time = k["T"]

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "time": k["T"]
    }

    ultimo_precio = candle["close"]

    klines.append(candle)
    if len(klines) > 500:
        klines.pop(0)

    señal = calcular_senal()

    if not señal or bot_pausado:
        return

    if not primera_senal_valida:
        if señal != ultima_senal_historica:
            primera_senal_valida = True
        else:
            return

    ejecutar_trade(señal, candle["close"])

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT PERFECTO ACTIVADO", flush=True)

    iniciar_web()

    enviar_telegram("🤖 BOT PERFECTO ACTIVADO")
    enviar_panel()

    threading.Thread(target=escuchar_botones, daemon=True).start()

    cargar_historico()
    sincronizar_trend()

    websocket.WebSocketApp(
        f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}",
        on_message=on_message
    ).run_forever()
