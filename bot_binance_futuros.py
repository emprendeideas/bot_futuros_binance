import websocket
import json
import requests
import time
import os
import threading
from flask import Flask
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CallbackQueryHandler

# =========================
# FLASK
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "BOT ACTIVO 🚀", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def iniciar_web():
    threading.Thread(target=run_web, daemon=True).start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "1m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))

klines = []
trend = 0
last_candle_time = None

ultima_senal_historica = None
primera_senal_valida = False

# =========================
# TRADING SIMULADO
# =========================
capital = 100.0
posicion = None
entry_price = 0.0
trades = 0
FEE = 0.0005
ultimo_precio = 0

bot_activo = True

# =========================
# TELEGRAM SIMPLE
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
# TELEGRAM BOT
# =========================
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, workers=0)

def enviar_botones():
    keyboard = [
        [InlineKeyboardButton("⏸️ Pausar", callback_data="pause"),
         InlineKeyboardButton("▶️ Reanudar", callback_data="resume")],
        [InlineKeyboardButton("🔴 Cerrar operación", callback_data="close")],
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=TELEGRAM_ADMIN_ID,
        text="⚙️ CONTROL DEL BOT",
        reply_markup=reply_markup
    )

def cerrar_manual():
    global capital, posicion, entry_price, trades

    if posicion is None:
        return

    if posicion == "BUY":
        pnl = (ultimo_precio - entry_price) / entry_price
    else:
        pnl = (entry_price - ultimo_precio) / entry_price

    capital *= (1 + pnl)
    capital *= (1 - FEE)

    trades += 1

    enviar_telegram(
        f"🧑‍💻 CIERRE MANUAL {posicion}\n"
        f"💰 Capital: {capital:.2f} USDT\n"
        f"📊 PnL: {pnl*100:.2f}%\n"
        f"🤖 Trades: {trades}"
    )

    posicion = None

def manejar_botones(update: Update, context):
    global bot_activo

    query = update.callback_query
    query.answer()

    data = query.data

    if data == "pause":
        bot_activo = False
        bot.send_message(TELEGRAM_ADMIN_ID, "⏸ Bot pausado")
        enviar_botones()

    elif data == "resume":
        bot_activo = True
        bot.send_message(TELEGRAM_ADMIN_ID, "▶️ Bot reanudado")
        enviar_botones()

    elif data == "close":
        cerrar_manual()
        bot.send_message(TELEGRAM_ADMIN_ID, "🔴 Operación cerrada manualmente")
        enviar_botones()

    elif data == "saldo":
        bot.send_message(
            TELEGRAM_ADMIN_ID,
            f"💰 Capital: {capital:.2f} USDT\n📊 Posición: {posicion}"
        )
        enviar_botones()

dispatcher.add_handler(CallbackQueryHandler(manejar_botones))

def iniciar_bot_telegram():
    def run():
        offset = None
        while True:
            try:
                updates = bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    dispatcher.process_update(update)
                    offset = update.update_id + 1
            except Exception as e:
                print("Error Telegram:", e)
                time.sleep(2)

    threading.Thread(target=run, daemon=True).start()

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
# (TODO TU LÓGICA COMPLETA SIN CAMBIOS)
# =========================
# 👉 TODO lo demás se queda EXACTAMENTE IGUAL
# (obtener_ultima_senal_real, sincronizar_trend, calcular_senal, ejecutar_trade, on_message)
# 👉 NO LO MODIFIQUÉ

# =========================
# 🚀 BOT PRINCIPAL (THREAD)
# =========================
def iniciar_bot():
    print("🚀 BOT PERFECTO ACTIVADO", flush=True)

    enviar_telegram("🤖 BOT PERFECTO ACTIVADO")

    cargar_historico()
    sincronizar_trend()

    enviar_botones()
    iniciar_bot_telegram()

    websocket.WebSocketApp(
        f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}",
        on_message=on_message
    ).run_forever()

# =========================
# MAIN (ESTILO BOT ESTABLE)
# =========================
def main():
    iniciar_web()  # 🔥 primero siempre

    threading.Thread(target=iniciar_bot, daemon=True).start()

    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
