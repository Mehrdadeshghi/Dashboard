from flask import Flask, redirect, url_for, session, render_template, jsonify, request
from flask_session import Session
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import mysql.connector
import os
from datetime import datetime, date, time, timedelta

# Lade Umgebungsvariablen
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Sitzung konfigurieren
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# Auth0-Konfiguration
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=os.getenv('AUTH0_CLIENT_ID'),
    client_secret=os.getenv('AUTH0_CLIENT_SECRET'),
    api_base_url=f'https://{os.getenv("AUTH0_DOMAIN")}',
    access_token_url=f'https://{os.getenv("AUTH0_DOMAIN")}/oauth/token',
    authorize_url=f'https://{os.getenv("AUTH0_DOMAIN")}/authorize',
    jwks_uri=f'https://{os.getenv("AUTH0_DOMAIN")}/.well-known/jwks.json',
    client_kwargs={
        'scope': 'openid profile email',
        'audience': os.getenv('AUTH0_AUDIENCE')
    },
)

# Funktion zur Herstellung der Datenbankverbindung
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='esp_user',
        password='esp_password',
        database='ESPv2'
    )

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    return auth0.authorize_redirect(redirect_uri=os.getenv('AUTH0_CALLBACK_URL'))

@app.route('/callback')
def callback():
    token = auth0.authorize_access_token()
    user_info = auth0.get('userinfo').json()
    session['user'] = user_info

    auth0_id = user_info.get('sub')
    email = user_info.get('email')
    first_name = user_info.get('given_name', 'Unbekannt')
    last_name = user_info.get('family_name', 'Unbekannt')

    # Verbindung zur Datenbank herstellen
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Benutzer in der Datenbank hinzufügen, falls noch nicht vorhanden
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    result = cursor.fetchone()
    if not result:
        cursor.execute(
            "INSERT INTO users (auth0_id, email, first_name, last_name) VALUES (%s, %s, %s, %s)",
            (auth0_id, email, first_name, last_name)
        )
        conn.commit()
    cursor.close()
    conn.close()

    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    # Hole die Benutzerdaten aus der Session
    user = session.get('user')
    if not user:
        return redirect('/login')  # Wenn nicht eingeloggt, weiterleiten zur Login-Seite

    auth0_id = user.get('sub')  # Auth0-Sub-ID des Benutzers

    # Verbindung zur Datenbank herstellen
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Benutzerdaten (Vorname, Nachname) aus der Datenbank abrufen
    cursor.execute("SELECT first_name, last_name FROM users WHERE auth0_id = %s", (auth0_id,))
    user_data = cursor.fetchone()
    first_name = user_data['first_name'] if user_data and user_data['first_name'] else 'Benutzer'

    # Geräte des Benutzers zusammen mit last_seen abrufen
    cursor.execute("""
        SELECT ud.mac_address, ud.hostname, ei.last_seen
        FROM user_devices ud
        LEFT JOIN esp_info ei ON ud.mac_address = ei.mac_address
        WHERE ud.user_id = (SELECT id FROM users WHERE auth0_id = %s)
    """, (auth0_id,))
    devices = cursor.fetchall()

    # Wenn keine Geräte gefunden wurden, wird eine leere Liste verwendet
    if not devices:
        devices = []

    # Ausgewähltes Gerät bestimmen
    selected_device_mac = request.args.get('device_mac')
    if devices and not selected_device_mac:
        selected_device_mac = devices[0]['mac_address']  # Standardmäßig erstes Gerät auswählen

    # Letzte Temperaturmessung, last_seen und wifi_strength für das ausgewählte Gerät abrufen
    last_temperature = "Keine Daten"
    selected_device_last_seen = None
    selected_device_wifi_strength = None

    if selected_device_mac:
        # Letzte Temperatur abrufen
        cursor.execute("""
            SELECT temperature_celsius
            FROM mailbox_temperature
            WHERE device_mac = %s
            ORDER BY date DESC, time DESC
            LIMIT 1
        """, (selected_device_mac,))
        temp_result = cursor.fetchone()
        if temp_result:
            last_temperature = temp_result['temperature_celsius']

        # Last seen und wifi_strength abrufen
        cursor.execute("""
            SELECT last_seen, wifi_strength
            FROM esp_info
            WHERE mac_address = %s
        """, (selected_device_mac,))
        device_info_result = cursor.fetchone()
        if device_info_result:
            selected_device_last_seen = device_info_result['last_seen']
            selected_device_wifi_strength = device_info_result['wifi_strength']

    cursor.close()
    conn.close()

    # Render das Dashboard-Template und übergebe die Daten
    return render_template(
        'dashboard.html',
        first_name=first_name,
        devices=devices,
        selected_device_mac=selected_device_mac,
        last_temperature=last_temperature,
        selected_device_last_seen=selected_device_last_seen,
        selected_device_wifi_strength=selected_device_wifi_strength
    )

@app.route('/einstellungen')
def einstellungen():
    user = session.get('user')
    if not user:
        return redirect('/login')

    auth0_id = user.get('sub')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Abrufen der Benutzerdaten aus der Datenbank
    cursor.execute("SELECT first_name, last_name FROM users WHERE auth0_id = %s", (auth0_id,))
    user_data = cursor.fetchone()

    cursor.close()
    conn.close()

    # Benutzerdaten an die Vorlage übergeben
    return render_template('settings.html', user_data=user_data)

@app.route('/api/save_user_data', methods=['POST'])
def save_user_data():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()

    if not first_name or not last_name:
        return jsonify({'error': 'Vorname und Nachname dürfen nicht leer sein'}), 400

    auth0_id = user.get('sub')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Aktualisieren der Benutzerdaten in der Datenbank
    cursor.execute(
        "UPDATE users SET first_name = %s, last_name = %s WHERE auth0_id = %s",
        (first_name, last_name, auth0_id)
    )
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Daten erfolgreich gespeichert'})

@app.route('/meine_geraete')
def meine_geraete():
    return render_template('meine_geraete.html')

@app.route('/api/my_devices')
def my_devices():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    auth0_id = user.get('sub')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    user_id = result['id']
    cursor.execute("SELECT id, mac_address, hostname FROM user_devices WHERE user_id = %s", (user_id,))
    devices = cursor.fetchall()
    cursor.close()
    conn.close()

    return jsonify({'devices': devices})

@app.route('/api/add_device', methods=['POST'])
def add_device():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    mac_address = request.json.get('mac_address')
    hostname = request.json.get('hostname')
    auth0_id = user.get('sub')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Überprüfe, ob die MAC-Adresse bereits registriert ist
    cursor.execute("SELECT * FROM user_devices WHERE mac_address = %s", (mac_address,))
    existing_device = cursor.fetchone()

    if existing_device:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Dieses Gerät ist bereits bei einem Konto registriert'}), 400

    # Benutzer-ID anhand der Auth0-Sub-ID abrufen
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    user_id = result['id']

    # Neues Gerät hinzufügen
    cursor.execute(
        "INSERT INTO user_devices (user_id, mac_address, hostname) VALUES (%s, %s, %s)",
        (user_id, mac_address, hostname)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/delete_device', methods=['POST'])
def delete_device():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    device_id = request.json.get('device_id')
    auth0_id = user.get('sub')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    user_id = result['id']

    cursor.execute("DELETE FROM user_devices WHERE id = %s AND user_id = %s", (device_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

# API-Endpunkt zum Abrufen der letzten Temperaturmessung
@app.route('/api/get_temperature')
def get_temperature():
    device_mac = request.args.get('device_mac')
    if not device_mac:
        return jsonify({'error': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Letzte Temperaturmessung für das ausgewählte Gerät abrufen
    cursor.execute("""
        SELECT temperature_celsius
        FROM mailbox_temperature
        WHERE device_mac = %s
        ORDER BY date DESC, time DESC
        LIMIT 1
    """, (device_mac,))

    temp_result = cursor.fetchone()
    cursor.close()
    conn.close()

    last_temperature = temp_result['temperature_celsius'] if temp_result else "Keine Daten"
    return jsonify({'last_temperature': last_temperature})

# API-Endpunkt zum Abrufen des Gerätestatus (Online/Offline je nach last_seen)
@app.route('/api/get_last_seen')
def get_last_seen():
    device_mac = request.args.get('device_mac')
    if not device_mac:
        return jsonify({'status': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT last_seen
        FROM esp_info
        WHERE mac_address = %s
    """, (device_mac,))
    last_seen_result = cursor.fetchone()
    cursor.close()
    conn.close()

    if last_seen_result and last_seen_result['last_seen']:
        last_seen_value = last_seen_result['last_seen']
        try:
            if isinstance(last_seen_value, str):
                last_seen = datetime.strptime(last_seen_value, '%Y-%m-%d %H:%M:%S')
            elif isinstance(last_seen_value, datetime):
                last_seen = last_seen_value
            else:
                last_seen = None

            if last_seen:
                current_time = datetime.utcnow()
                time_diff = (current_time - last_seen).total_seconds() / 60
                if time_diff <= 30:
                    status = "Online"
                elif 30 < time_diff <= 60:
                    status = "Unregelmäßig"
                else:
                    status = "Offline"
            else:
                status = "Keine Daten"
        except Exception as e:
            print(f"Fehler bei der Verarbeitung von last_seen: {e}")
            status = "Fehler"
    else:
        status = "Keine Daten"

    return jsonify({'status': status})

# API-Endpunkt zum Abrufen der Signalstärke
@app.route('/api/get_wifi_strength')
def get_wifi_strength():
    device_mac = request.args.get('device_mac')
    if not device_mac:
        return jsonify({'wifi_strength_rating': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT wifi_strength
        FROM esp_info
        WHERE mac_address = %s
    """, (device_mac,))
    wifi_strength_result = cursor.fetchone()
    cursor.close()
    conn.close()

    if wifi_strength_result and wifi_strength_result['wifi_strength'] is not None:
        try:
            wifi_strength = int(wifi_strength_result['wifi_strength'])
            if wifi_strength >= -50:
                wifi_strength_rating = "Gut"
            elif -70 < wifi_strength < -50:
                wifi_strength_rating = "Normal"
            else:
                wifi_strength_rating = "Schlecht"
        except ValueError:
            wifi_strength_rating = "Unbekannt"
    else:
        wifi_strength_rating = "Keine Daten"

    return jsonify({'wifi_strength_rating': wifi_strength_rating})

# API-Endpunkt für Bewegungsdaten (Chart)
@app.route('/api/motion_chart_data')
def motion_chart_data():
    mac_address = request.args.get('mac_address')
    days = request.args.get('days', 30)  # Standard: 30 Tage

    if not mac_address:
        return jsonify({'error': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT event_date, COUNT(*) AS movement_count
        FROM post_logs
        WHERE mac_address = %s 
          AND event_date >= CURDATE() - INTERVAL %s DAY
        GROUP BY event_date
        ORDER BY event_date
    """, (mac_address, int(days)))

    motion_data = cursor.fetchall()
    cursor.close()
    conn.close()

    labels = [row['event_date'].strftime('%Y-%m-%d') for row in motion_data]
    values = [row['movement_count'] for row in motion_data]

    return jsonify({'labels': labels, 'values': values})

# API-Endpunkt zum Abrufen des Post-Status
@app.route('/api/post_status')
def post_status():
    mac_address = request.args.get('mac_address')
    if not mac_address:
        return jsonify({'error': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT has_post, last_cleared_at
        FROM post_status
        WHERE mac_address = %s
    """, (mac_address,))
    post_status_result = cursor.fetchone()
    cursor.close()
    conn.close()

    if post_status_result:
        has_post = bool(post_status_result['has_post'])
        last_cleared_at = post_status_result['last_cleared_at']
        if last_cleared_at:
            last_cleared_at = last_cleared_at.strftime('%Y-%m-%d %H:%M:%S')
        else:
            last_cleared_at = 'Noch nie'
    else:
        has_post = False
        last_cleared_at = 'Noch nie'

    return jsonify({'has_post': has_post, 'last_cleared_at': last_cleared_at})

# API-Endpunkt zum Zurücksetzen des Post-Status
@app.route('/api/reset_post_status', methods=['POST'])
def reset_post_status():
    mac_address = request.args.get('mac_address')
    if not mac_address:
        return jsonify({'error': 'MAC-Adresse fehlt'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.utcnow()

    cursor.execute("SELECT id FROM post_status WHERE mac_address = %s", (mac_address,))
    status_result = cursor.fetchone()

    if status_result:
        cursor.execute("""
            UPDATE post_status
            SET has_post = %s, email_sent = %s, last_cleared_at = %s
            WHERE mac_address = %s
        """, (0, 0, now, mac_address))
    else:
        cursor.execute("""
            INSERT INTO post_status (mac_address, has_post, email_sent, last_cleared_at)
            VALUES (%s, %s, %s, %s)
        """, (mac_address, 0, 0, now))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

# API-Endpunkt zum Abrufen der letzten 5 Meldungen (inkl. Bewertungsstatus)
@app.route('/api/recent_logs')
def recent_logs():
    mac_address = request.args.get('mac_address')
    if not mac_address:
        return jsonify({'error': 'MAC-Adresse fehlt'}), 400

    # Prüfen, ob der Nutzer eingeloggt ist
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    # user_id aus DB ermitteln
    auth0_id = user.get('sub')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    user_in_db = cursor.fetchone()

    if not user_in_db:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    user_id = user_in_db['id']

    try:
        # Letzte 5 Meldungen aus post_logs (JOIN event_classifications)
        cursor.execute("""
            SELECT 
                pl.id AS event_id,
                pl.event_date,
                pl.event_time,
                ec.classification
            FROM post_logs pl
            LEFT JOIN event_classifications ec
                ON pl.id = ec.event_id
                AND ec.user_id = %s
            WHERE pl.mac_address = %s
            ORDER BY pl.event_date DESC, pl.event_time DESC
            LIMIT 5
        """, (user_id, mac_address))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return jsonify([])

        log_list = []
        for idx, row in enumerate(rows, start=1):
            event_date = row['event_date']
            event_time = row['event_time']
            classification = row['classification']  # kann None sein

            # Zusammenbauen: datetime
            if isinstance(event_time, time):
                created_at = datetime.combine(event_date, event_time)
            elif isinstance(event_time, timedelta):
                # Oder falls event_time ein timedelta
                created_at = datetime.combine(event_date, time(0,0,0)) + event_time
            else:
                created_at = None

            if created_at:
                created_at_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
            else:
                created_at_str = 'Unbekannt'

            # Wenn classification None => Keine Bewertung
            if classification is None:
                classification_text = "Keine Bewertung"
            else:
                classification_text = classification  # "Correct" / "Incorrect"

            log_list.append({
                'index': idx,
                'event_id': row['event_id'],
                'created_at': created_at_str,
                'classification': classification_text
            })

        return jsonify(log_list)

    except Exception as e:
        print(f"Fehler im Endpunkt /api/recent_logs: {e}")
        return jsonify({'error': 'Interner Serverfehler'}), 500

# API-Endpunkt zum Speichern einer Klassifikation
@app.route('/api/classify_event', methods=['POST'])
def classify_event():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    event_id = data.get('event_id')           # ID aus post_logs
    classification = data.get('classification')  # "Correct" oder "Incorrect"

    if not event_id or not classification:
        return jsonify({'error': 'Fehlende Parameter (event_id / classification)'}), 400
    if classification not in ['Correct', 'Incorrect']:
        return jsonify({'error': 'Ungültige Klassifikation!'}), 400

    # user_id aus DB ermitteln, statt clientseitig
    auth0_id = user.get('sub')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE auth0_id = %s", (auth0_id,))
    user_in_db = cursor.fetchone()
    if not user_in_db:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    user_id = user_in_db['id']

    # Insert in event_classifications
    try:
        cursor.execute("""
            INSERT INTO event_classifications (event_id, user_id, classification)
            VALUES (%s, %s, %s)
        """, (event_id, user_id, classification))
        conn.commit()
    except Exception as e:
        print(f"Fehler beim Einfügen der Klassifikation: {e}")
        cursor.close()
        conn.close()
        return jsonify({'error': 'Datenbankfehler'}), 500

    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(
        f'https://{os.getenv("AUTH0_DOMAIN")}/v2/logout?client_id={os.getenv("AUTH0_CLIENT_ID")}&returnTo={url_for("home", _external=True)}'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5100)

