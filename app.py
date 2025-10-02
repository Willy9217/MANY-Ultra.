# app.py
import os, json, time, secrets, hmac, hashlib, requests
from flask import Flask, render_template, request, jsonify, redirect
from dotenv import load_dotenv

load_dotenv()  # solo en desarrollo local

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", secrets.token_hex(16))

# Stripe
import stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
stripe.api_key = STRIPE_SECRET_KEY

# Binance Pay
BINANCE_BASE = os.getenv("BINANCE_BASE_URL", "https://bpay.binanceapi.com")
BINANCE_CERT_SN = os.getenv("BINANCE_CERT_SN", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_MERCHANT_ID = os.getenv("BINANCE_MERCHANT_ID", "")
BINANCE_WEBHOOK_URL = os.getenv("BINANCE_WEBHOOK_URL", "")

# PayPal
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET", "")
PAYPAL_BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")  # sandbox por defecto

# Twilio
from twilio.rest import Client as TwilioClient
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID and TWILIO_TOKEN else None

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Helpers: Binance signature
def binance_make_signature(body_str: str, timestamp_ms: int, nonce: str) -> str:
    payload = f"{timestamp_ms}\n{nonce}\n{body_str}\n".encode("utf-8")
    sig = hmac.new(BINANCE_SECRET_KEY.encode("utf-8"), payload, hashlib.sha512).hexdigest().upper()
    return sig

# Routes / dashboard
@app.route("/")
def index():
    return render_template("dashboard.html")

# --- Stripe: crear session (test/live según tu clave) ---
@app.route("/test/create_stripe_session", methods=["POST"])
def create_stripe_session():
    data = request.json or {}
    amount = int(float(data.get("amount", 1.0)) * 100)
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": data.get("currency", "usd"),
                    "product_data": {"name": data.get("product", "MANY Pro")},
                    "unit_amount": amount,
                }, "quantity": 1,
            }],
            mode="payment",
            success_url=data.get("success_url", "https://example.com/success"),
            cancel_url=data.get("cancel_url", "https://example.com/cancel"),
        )
        return jsonify({"ok": True, "url": session.url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# Stripe webhook (verifica firma)
@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        app.logger.error("Stripe webhook verification failed: %s", e)
        return "", 400
    if event['type'] == 'checkout.session.completed':
        app.logger.info("Stripe checkout completed: %s", event['data']['object'].get('id'))
        # TODO: marcar pago en BD, entregar producto
    return "", 200

# --- Binance Pay: crear orden ---
@app.route("/test/create_binance_order", methods=["POST"])
def create_binance_order():
    data = request.json or {}
    amount = str(data.get("amount", "1.00"))
    currency = data.get("currency", "USDT")
    goods_name = data.get("goodsName", "MANY Pro")
    merchant_trade_no = f"MANY-{int(time.time())}-{secrets.token_hex(4)}"
    body = {
        "merchantTradeNo": merchant_trade_no,
        "orderAmount": amount,
        "currency": currency,
        "goods": {"goodsType": "DIGITAL", "goodsName": goods_name},
        "merchant": {"merchantId": BINANCE_MERCHANT_ID} if BINANCE_MERCHANT_ID else {},
        "env": {"terminalType": "WEB"},
        "notifyUrl": BINANCE_WEBHOOK_URL,
        "returnUrl": data.get("returnUrl", "")
    }
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    ts = int(time.time() * 1000)
    nonce = secrets.token_hex(16)
    signature = binance_make_signature(body_str, ts, nonce)
    headers = {
        "Content-Type": "application/json",
        "BinancePay-Timestamp": str(ts),
        "BinancePay-Nonce": nonce,
        "BinancePay-Certificate-SN": BINANCE_CERT_SN,
        "BinancePay-Signature": signature
    }
    url = f"{BINANCE_BASE}/binancepay/openapi/v2/order"
    resp = requests.post(url, data=body_str.encode("utf-8"), headers=headers, timeout=20)
    if resp.status_code not in (200, 201):
        return jsonify({"ok": False, "status": resp.status_code, "body": resp.text}), 400
    rj = resp.json()
    return jsonify({"ok": True, "data": rj.get("data", {})})

# Binance webhook skeleton (DEBES implementar verificación real)
@app.route("/binance/webhook", methods=["POST"])
def binance_webhook():
    raw = request.get_data(as_text=True)
    app.logger.info("BINANCE webhook raw: %s", raw)
    # TODO: verificar firma usando la clave pública/certificado de Binance.
    # Por ahora solo responde para pruebas.
    return "SUCCESS", 200

# --- PayPal: crear orden (v2) ---
@app.route("/test/create_paypal_order", methods=["POST"])
def create_paypal_order():
    data = request.json or {}
    amount = data.get("amount", "1.00")
    # obtener token
    token_res = requests.post(f"{PAYPAL_BASE}/v1/oauth2/token",
                              auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
                              data={"grant_type": "client_credentials"})
    if token_res.status_code != 200:
        return jsonify({"ok": False, "error": "token failed", "detail": token_res.text}), 400
    token = token_res.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": data.get("currency", "USD"), "value": str(amount)}}],
            "application_context": {"return_url": data.get("return_url", ""), "cancel_url": data.get("cancel_url", "")}}
    r = requests.post(f"{PAYPAL_BASE}/v2/checkout/orders", headers=headers, json=body)
    if r.status_code not in (201,):
        return jsonify({"ok": False, "status": r.status_code, "body": r.text}), 400
    return jsonify({"ok": True, "order": r.json()})

# --- Twilio: enviar SMS ---
@app.route("/test/send_twilio_sms", methods=["POST"])
def send_twilio_sms():
    if not twilio_client:
        return jsonify({"ok": False, "error": "Twilio no configurado"}), 400
    data = request.json or {}
    to = data.get("to")
    body = data.get("body", "Mensaje de prueba MANY-ULTRA")
    if not to:
        return jsonify({"ok": False, "error": "to (phone) requerido"}), 400
    msg = twilio_client.messages.create(body=body, from_=TWILIO_FROM, to=to)
    return jsonify({"ok": True, "sid": msg.sid})

# --- Telegram: enviar mensaje ---
@app.route("/test/send_telegram", methods=["POST"])
def send_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return jsonify({"ok": False, "error": "Telegram no configurado"}), 400
    data = request.json or {}
    text = data.get("text", "Mensaje de prueba MANY-ULTRA")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    if r.status_code != 200:
        return jsonify({"ok": False, "status": r.status_code, "body": r.text}), 400
    return jsonify({"ok": True, "data": r.json()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
