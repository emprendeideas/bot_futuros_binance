import websocket
import json
import requests
import time
import os
import threading
from flask import Flask

# =========================
# FLASK (RENDER ESTABLE)
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

def iniciar_web():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "5m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FEE = 0.0005  # 0.05%

STATE_FILE = "estado_bot.json"

klines = []
trend = 0

# =========================
# ESTADO TRADING
# =========================
estado = {
    "capital": 100.0,
    "posicion": None,
    "entry_price": 0.0,
    "trades": 0,
    "wins": 0,
    "losses": 0
}

# =========================
# PERSISTENCIA
# =========================
def guardar_estado():
    with open(STATE_FILE, "w") as f:
        json.dump(estado, f)

def cargar_estado():
    global estado
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            estado = json.load(f)

# =========================
# TELEGRAM (NO BLOQUEA)
# =========================
def enviar_telegram(msg):
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg
            }, timeout=3)
        except:
            pass

    threading.Thread(target=send).start()

# =========================
# EMA / SMA
# =========================
def ema(src, length):
    ema_vals = []
    k = 2 / (length + 1)
    for i, v in enumerate(src):
        if i == 0:
            ema_vals.append(v)
        else:
            ema_vals.append(v * k + ema_vals[i - 1] * (1 - k))
    return ema_vals

def sma(src, length):
    out = []
    for i in range(len(src)):
        if i < length - 1:
            out.append(None)
        else:
            out.append(sum(src[i - length + 1:i + 1]) / length)
    return out

# =========================
# HISTÓRICO
# =========================
def cargar_historico():
    global klines

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=500"
    data = requests.get(url).json()

    klines = []
    for k in data:
        klines.append({
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "closed": True
        })

    print("📊 Histórico cargado", flush=True)

# =========================
# SEÑALES (NO TOCAR)
# =========================
def calcular_senal():
    global trend

    if len(klines) < 100:
        return None

    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]
    close = [k["close"] for k in klines]

    ohlc4 = [(o + h + l + c) / 4 for o, h, l, c in zip(open_, high, low, close)]

    haOpen = [0.0] * len(ohlc4)
    for i in range(len(ohlc4)):
        if i == 0:
            haOpen[i] = ohlc4[i] / 2
        else:
            haOpen[i] = (ohlc4[i] + haOpen[i - 1]) / 2

    haC = [
        (ohlc4[i] + haOpen[i] + max(high[i], haOpen[i]) + min(low[i], haOpen[i])) / 4
        for i in range(len(close))
    ]

    L = 8

    EMA1 = ema(haC, L)
    EMA2 = ema(EMA1, L)
    EMA3 = ema(EMA2, L)
    TMA1 = [3 * EMA1[i] - 3 * EMA2[i] + EMA3[i] for i in range(len(close))]

    EMA4 = ema(TMA1, L)
    EMA5 = ema(EMA4, L)
    EMA6 = ema(EMA5, L)
    TMA2 = [3 * EMA4[i] - 3 * EMA5[i] + EMA6[i] for i in range(len(close))]

    mavi = TMA1
    kirmizi = TMA2

    i = -1

    cruce_up = mavi[i] > kirmizi[i] and mavi[i - 1] <= kirmizi[i - 1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i - 1] >= kirmizi[i - 1]

    confirm_up = mavi[i] > mavi[i - 1]
    confirm_down = mavi[i] < mavi[i - 1]

    dist = [abs(mavi[j] - kirmizi[j]) for j in range(len(mavi))]
    dist_media = sma(dist, 30)

    if dist_media[i] is None:
        return None

    filtro_vol = dist[i] > dist_media[i] * 0.3

    if cruce_up and confirm_up and filtro_vol and trend != 1:
        trend = 1
        return "BUY"

    elif cruce_down and confirm_down and filtro_vol and trend != -1:
        trend = -1
        return "SELL"

    return None

# =========================
# TRADING ENGINE
# =========================
def ejecutar_trade(señal, precio):
    global estado

    # CERRAR
    if estado["posicion"] is not None:
        entry = estado["entry_price"]

        pnl = (precio - entry) / entry if estado["posicion"] == "LONG" else (entry - precio) / entry

        capital_antes = estado["capital"]

        estado["capital"] *= (1 + pnl)
        estado["capital"] *= (1 - FEE)

        resultado = estado["capital"] - capital_antes

        estado["trades"] += 1
        if resultado > 0:
            estado["wins"] += 1
        else:
            estado["losses"] += 1

        enviar_telegram(
            f"❌ CIERRE {estado['posicion']}\n"
            f"💰 Capital: {estado['capital']:.2f}\n"
            f"📊 PnL: {resultado:.2f}"
        )

    # ABRIR
    estado["posicion"] = "LONG" if señal == "BUY" else "SHORT"
    estado["entry_price"] = precio

    estado["capital"] *= (1 - FEE)

    enviar_telegram(
        f"🚀 {estado['posicion']}\n"
        f"💰 Precio: {precio}\n"
        f"💼 Capital: {estado['capital']:.2f}"
    )

    guardar_estado()

# =========================
# WS
# =========================
def on_message(ws, message):
    global klines

    data = json.loads(message)
    k = data['k']

    if not k["x"]:
        return

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "closed": True
    }

    klines.append(candle)

    if len(klines) > 500:
        klines.pop(0)

    señal = calcular_senal()

    if señal:
        precio = candle["close"]
        print(f"🚀 {señal} | {precio}", flush=True)

        threading.Thread(target=ejecutar_trade, args=(señal, precio)).start()

# =========================
# WS START
# =========================
def iniciar_ws():
    socket_url = f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}"

    while True:
        try:
            ws = websocket.WebSocketApp(socket_url, on_message=on_message)
            ws.run_forever()
        except:
            print("⚠️ Reconectando...", flush=True)
            time.sleep(5)

# =========================
# ANTI-SLEEP INTERNO
# =========================
def ping_self():
    while True:
        try:
            requests.get("http://127.0.0.1:10000")
        except:
            pass
        time.sleep(60)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT ULTRA ESTABLE INICIADO", flush=True)

    iniciar_web()
    cargar_estado()

    enviar_telegram("🤖 BOT TRADING ACTIVO")

    threading.Thread(target=ping_self, daemon=True).start()

    def run_ws():
        cargar_historico()
        iniciar_ws()

    threading.Thread(target=run_ws).start()

    while True:
        time.sleep(60)
