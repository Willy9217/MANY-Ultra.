from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("dashboard.html")

@app.route("/stripe")
def stripe_sim():
    return "✅ Stripe conectado (simulación de cobro $1)"

@app.route("/binance")
def binance_sim():
    return "✅ Binance Pay conectado (simulación pago USDT)"

@app.route("/paypal")
def paypal_sim():
    return "✅ PayPal conectado (simulación checkout)"

@app.route("/twilio")
def twilio_sim():
    return "✅ Twilio funcionando (mensaje de prueba enviado)"

@app.route("/telegram")
def telegram_sim():
    return "✅ Telegram Bot responde (mensaje enviado a canal de prueba)"

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
