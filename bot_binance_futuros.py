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

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "BOT ACTIVO 🚀", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def iniciar_web():
    t = threading.Thread(target=run_web)
    t.start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "1m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

try:
    TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except:
    TELEGRAM_ADMIN_ID = None

print("ADMIN ID:", TELEGRAM_ADMIN_ID)

klines = []
trend = 0
last_candle_time = None

ultima_senal_historica = None
primera_senal_valida = False

# =========================
# 💰 TRADING SIMULADO
# =========================
capital = 100.0
capital_inicial = 100.0
posicion = None
entry_price = 0.0
trades = 0
FEE = 0.0005
ultimo_precio = 0

bot_activo = True
detener_bot_total = False

nivel_actual = 1
EMA_LENGTH = 14

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
    except Exception as e:
        print("ERROR TELEGRAM:", e)

# =========================
# TELEGRAM BOT SEGURO
# =========================
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, workers=1)

def safe_send_bot(chat_id, text, reply_markup=None):
    try:
        if chat_id is None:
            print("⚠️ ADMIN_ID inválido")
            return

        bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        print("❌ ERROR BOT:", e)

def enviar_botones():
    try:
        keyboard = [
            [InlineKeyboardButton("⏸️ Pausar", callback_data="pause"),
             InlineKeyboardButton("▶️ Reanudar", callback_data="resume")],
            [InlineKeyboardButton("🔴 Cerrar operación", callback_data="close")],
            [InlineKeyboardButton("💰 Saldo", callback_data="saldo")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        safe_send_bot(TELEGRAM_ADMIN_ID, "⚙️ CONTROL DEL BOT", reply_markup)

    except Exception as e:
        print("ERROR BOTONES:", e)

def enviar_control_ganancia():
    try:
        keyboard = [
            [InlineKeyboardButton("✅ Continuar", callback_data="continue_profit"),
             InlineKeyboardButton("🛑 Parar", callback_data="stop_profit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        safe_send_bot(
            TELEGRAM_ADMIN_ID,
            "📊 Se alcanzó el objetivo mensual.\n¿Desea continuar operando?",
            reply_markup
        )

    except Exception as e:
        print("ERROR CONTROL GANANCIA:", e)

# =========================
# 🔥 CIERRE MANUAL
# =========================
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

    verificar_ganancia()

    enviar_telegram(
        f"🧑‍💻 CIERRE MANUAL {posicion}\n"
        f"💰 Capital: {capital:.2f} USDT\n"
        f"📊 PnL: {pnl*100:.2f}%\n"
        f"🤖 Trades: {trades}"
    )

    posicion = None

# =========================
# BOTONES
# =========================
def manejar_botones(update: Update, context):
    global bot_activo, nivel_actual, detener_bot_total

    query = update.callback_query
    query.answer()

    data = query.data

    if data == "pause":
        bot_activo = False
        safe_send_bot(TELEGRAM_ADMIN_ID, "⏸ Bot pausado")
        enviar_botones()

    elif data == "resume":
        bot_activo = True
        safe_send_bot(TELEGRAM_ADMIN_ID, "▶️ Bot reanudado")
        enviar_botones()

    elif data == "close":
        cerrar_manual()
        safe_send_bot(TELEGRAM_ADMIN_ID, "🔴 Operación cerrada manualmente")
        enviar_botones()

    elif data == "saldo":
        safe_send_bot(
            TELEGRAM_ADMIN_ID,
            f"💰 Capital: {capital:.2f} USDT\n📊 Posición: {posicion}"
        )
        enviar_botones()

    elif data == "continue_profit":
        safe_send_bot(TELEGRAM_ADMIN_ID, "✅ Se continúa operando")

    elif data == "stop_profit":
        bot_activo = False
        detener_bot_total = True

        ganancia = ((capital - capital_inicial) / capital_inicial) * 100

        enviar_telegram(
            f"🏁 OPERACIONES FINALIZADAS DEL MES\n\n"
            f"📊 Ganancia total: {ganancia:.2f}%\n"
            f"💰 Capital final: {capital:.2f} USDT\n"
            f"🤖 Total trades: {trades}"
        )

        safe_send_bot(TELEGRAM_ADMIN_ID, "🛑 Bot detenido completamente")

dispatcher.add_handler(CallbackQueryHandler(manejar_botones))

# =========================
# TELEGRAM LOOP
# =========================
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
                print("Error Telegram Loop:", e)
                time.sleep(2)

    threading.Thread(target=run, daemon=True).start()

# =========================
# GANANCIA
# =========================
def verificar_ganancia():
    global nivel_actual

    try:
        ganancia = ((capital - capital_inicial) / capital_inicial) * 100

        print(f"[DEBUG] Ganancia: {ganancia:.2f}% | Nivel: {nivel_actual}")

        if ganancia >= nivel_actual:
            print("🔥 NIVEL ALCANZADO")

            nivel_detectado = nivel_actual
            nivel_actual += 1

            enviar_telegram(
                f"🎯 ¡Objetivo alcanzado!\n\n"
                f"📈 +{nivel_detectado}% logrado\n"
                f"💰 Actual: {ganancia:.2f}%"
            )

            enviar_control_ganancia()

    except Exception as e:
        print("ERROR GANANCIA:", e)

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, primera_senal_valida, ultimo_precio, detener_bot_total

    try:
        if detener_bot_total:
            return

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

        ultimo_precio = candle["close"]

        klines.append(candle)
        if len(klines) > 500:
            klines.pop(0)

        if not bot_activo:
            return

        señal = calcular_senal()

        if not señal:
            return

        if not primera_senal_valida:
            if señal != ultima_senal_historica:
                primera_senal_valida = True
            else:
                return

        ejecutar_trade(señal, ultimo_precio)

    except Exception as e:
        print("ERROR WEBSOCKET:", e)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT PERFECTO ACTIVADO", flush=True)

    iniciar_web()

    def run_bot():
        enviar_telegram("🤖 BOT PERFECTO ACTIVADO")

        cargar_historico()
        sincronizar_trend()

        enviar_botones()
        iniciar_bot_telegram()

        websocket.WebSocketApp(
            f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}",
            on_message=on_message
        ).run_forever()

    threading.Thread(target=run_bot).start()
