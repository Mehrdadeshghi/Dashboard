from flask import Flask, redirect, url_for, session, jsonify, request, render_template
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
import mysql.connector

# Lade .env Datei
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['FLASK_SECRET_KEY']

# Auth0 Konfiguration
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=os.environ['AUTH0_CLIENT_ID'],
    client_secret=os.environ['AUTH0_CLIENT_SECRET'],
    client_kwargs={'scope': 'openid profile email'},
    server_metadata_url=f'https://{os.environ["AUTH0_DOMAIN"]}/.well-known/openid-configuration',
)

# MySQL Verbindung
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='esp_user',
        password='esp_password',
        database='ESPv2'
    )

@app.route("/")
def home():
    if "user" in session:
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/login")
def login():
    return auth0.authorize_redirect(redirect_uri=os.environ["AUTH0_CALLBACK_URL"])

@app.route("/callback")
def callback():
    token = auth0.authorize_access_token()
    userinfo = token['userinfo']

    session['user'] = {
        'email': userinfo['email'],
        'name': userinfo['name'],
        'sub': userinfo['sub']
    }

    # Nutzer in DB speichern (wenn neu)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (userinfo['sub'],))
    result = cursor.fetchone()

    if result:
        user_id = result[0]
    else:
        cursor.execute(
            "INSERT INTO users (email, name, auth0_id) VALUES (%s, %s, %s)",
            (userinfo['email'], userinfo['name'], userinfo['sub'])
        )
        conn.commit()
        user_id = cursor.lastrowid

    # Geräteprüfung
    cursor.execute("SELECT COUNT(*) FROM devices WHERE user_id = %s", (user_id,))
    device_count = cursor.fetchone()[0]

    conn.close()

    if device_count == 0:
        return redirect("/geraete-hinzufuegen")
    else:
        return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")
    return render_template("dashboard.html")

@app.route("/geraete-hinzufuegen")
def geraete_hinzufuegen():
    if "user" not in session:
        return redirect("/")
    return render_template("geraete_hinzufuegen.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100, debug=True)
