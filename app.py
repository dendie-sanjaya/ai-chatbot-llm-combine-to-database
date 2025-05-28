import os
import re
import sqlite3
import json
import google.generativeai as genai
from flask import Flask, request, jsonify, Response, stream_with_context # Import Response and stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

# --- 1. Configure Gemini API ---
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set. Please set it in your .env file.")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. Initialize SQLite Database ---
DB_NAME = 'chatbot_data.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            price REAL NOT NULL,
            stock INTEGER,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            location TEXT,
            last_online TEXT
        )
    ''')

    try:
        cursor.execute("INSERT INTO products (name, price, stock, description) VALUES (?, ?, ?, ?)", ('Laptop A', 15000000, 50, 'High-performance laptop for professionals.'))
        cursor.execute("INSERT INTO products (name, price, stock, description) VALUES (?, ?, ?, ?)", ('Smartphone B', 7500000, 120, 'Latest smartphone with advanced camera.'))
        cursor.execute("INSERT INTO products (name, price, stock, description) VALUES (?, ?, ?, ?)", ('Keyboard C', 1200000, 200, 'Mechanical keyboard for gaming and typing.'))
        cursor.execute("INSERT INTO products (name, price, stock, description) VALUES (?, ?, ?, ?)", ('Handphone Samsung', 3500000, 80, 'Popular Samsung mobile phone model.'))

        cursor.execute("INSERT INTO devices (device_id, status, location, last_online) VALUES (?, ?, ?, ?)", ('OLT-BDG-001', 'Online', 'Bandung', '2025-05-25 09:00:00'))
        cursor.execute("INSERT INTO devices (device_id, status, location, last_online) VALUES (?, ?, ?, ?)", ('OLT-JKT-002', 'Offline', 'Jakarta', '2025-05-24 18:30:00'))
        cursor.execute("INSERT INTO devices (device_id, status, location, last_online) VALUES (?, ?, ?, ?)", ('ROUTER-SBY-003', 'Online', 'Surabaya', '2025-05-25 10:15:00'))
    except sqlite3.IntegrityError:
        print("Sample data already exists in the database.")
    finally:
        conn.commit()
        conn.close()

# --- 3. Function to Execute SQL Queries ---
def execute_sql_query(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        result = cursor.fetchall()
        conn.commit()
        return result
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        conn.close()

# --- 4. Intent Detection and Entity Extraction ---
def detect_intent_and_extract_entities(user_query):
    query_lower = user_query.lower()
    intent = "unknown"
    entities = {}

    if "harga" in query_lower or "price" in query_lower or "berapa" in query_lower:
        intent = "get_product_price"
        match_product = re.search(r'(?:produk|handphone|laptop|keyboard|headset|hp)\s*([a-z0-9\s]+)', query_lower)
        if match_product:
            product_name = match_product.group(1).strip()
            product_name = re.sub(r'(berapa|adalah|ya|sih|dong)\s*', '', product_name).strip()
            entities['product_name'] = product_name.title()
        elif "harga" in query_lower:
            parts = query_lower.split("harga", 1)
            if len(parts) > 1:
                potential_product = parts[1].strip().split(' ')[0:3]
                entities['product_name'] = ' '.join(potential_product).title()

    elif "status" in query_lower or "cek" in query_lower:
        match_device = re.search(r'(olt|router|server)-[a-z]{3}-\d{3}', query_lower)
        if match_device:
            intent = "check_device_status"
            entities['device_id'] = match_device.group(0).upper()
        elif "status" in query_lower:
            if "olt" in query_lower:
                intent = "check_device_status"
                entities['device_id'] = "OLT"
            elif "router" in query_lower:
                intent = "check_device_status"
                entities['device_id'] = "ROUTER"
            elif "server" in query_lower:
                intent = "check_device_status"
                entities['device_id'] = "SERVER"
            elif "perangkat" in query_lower or "device" in query_lower:
                intent = "check_device_status" # Generic status check

    return intent, entities

# --- 5. Function to Retrieve Context from Database ---
def get_context_from_db(intent, entities):
    context = ""
    if intent == "get_product_price" and 'product_name' in entities and entities['product_name']:
        product_name = entities['product_name']
        query = "SELECT name, price, stock, description FROM products WHERE name LIKE ? LIMIT 1"
        result = execute_sql_query(query, (f'%{product_name}%',))

        if result:
            name, price, stock, description = result[0]
            context = (
                f"Konteks: Informasi produk {name}: "
                f"Harga adalah Rp {price:,.0f}. "
                f"Stok tersedia {stock} unit. "
                f"Deskripsi: {description}."
            )
        else:
            context = f"Konteks: Maaf, data harga untuk produk '{product_name}' tidak ditemukan."

    elif intent == "check_device_status" and 'device_id' in entities and entities['device_id']:
        device_id = entities['device_id']
        if device_id in ["OLT", "ROUTER", "SERVER"]:
            query = "SELECT device_id, status, location, last_online FROM devices WHERE device_id LIKE ? LIMIT 5"
            result = execute_sql_query(query, (f'%{device_id}%',))
            if result:
                context_parts = [f"Konteks: Berikut adalah status beberapa perangkat {device_id}:"]
                for dev_id, status, location, last_online in result:
                    context_parts.append(f"- {dev_id}: {status} di {location}. Terakhir online pada {last_online}.")
                context = "\n".join(context_parts)
            else:
                context = f"Konteks: Tidak ditemukan informasi untuk perangkat jenis '{device_id}'."
        else: # Specific device ID
            query = "SELECT device_id, status, location, last_online FROM devices WHERE device_id = ? LIMIT 1"
            result = execute_sql_query(query, (device_id,))

            if result:
                dev_id, status, location, last_online = result[0]
                context = (
                    f"Konteks: Status perangkat {dev_id}: "
                    f"Saat ini {status} di {location}. "
                    f"Terakhir online pada {last_online}."
                )
            else:
                context = f"Konteks: Maaf, data status untuk perangkat '{device_id}' tidak ditemukan."
    elif intent == "check_device_status": # Generic status check without specific device_id
        context = "Konteks: Pengguna ingin mengetahui status perangkat secara umum. Informasikan bahwa Anda memerlukan ID perangkat yang spesifik untuk detail lebih lanjut, atau tanyakan jenis perangkat apa yang ingin diketahui statusnya."
    return context

# --- 6. Main Function to Interact with Gemini (Streaming) ---
def generate_gemini_response_stream(user_query):
    """
    Generates a response from Gemini based on user query and database context.
    This version streams the response chunk by chunk.
    Each chunk is sent as a JSON Lines (NDJSON) object.
    """
    intent, entities = detect_intent_and_extract_entities(user_query)
    db_context = get_context_from_db(intent, entities)

    llm_role = "Anda adalah asisten virtual yang ramah dan membantu."
    if intent == "check_device_status":
        llm_role = "Anda adalah customer service yang ramah dan responsif untuk layanan jaringan."
    elif intent == "get_product_price":
        llm_role = "Anda adalah asisten penjualan yang ramah dan informatif untuk produk retail."

    prompt_parts = [
        f"{llm_role}",
        db_context,
        "---",
        f"Pertanyaan Pengguna: {user_query}",
        "---",
        "Berikan jawaban yang ramah, informatif, dan ringkas berdasarkan konteks yang diberikan. "
        "Jika konteks dari database tidak memberikan informasi yang cukup, katakan bahwa Anda tidak memiliki data spesifik atau butuh informasi lebih lanjut."
    ]

    full_prompt = "\n".join(filter(None, prompt_parts))

    try:
        # Panggil Gemini API dalam mode streaming
        response_stream = gemini_model.generate_content(full_prompt, stream=True)

        for chunk in response_stream:
            # Pastikan chunk memiliki atribut 'text' dan tidak kosong
            if hasattr(chunk, 'text') and chunk.text:
                # Bungkus teks dalam objek JSON dan tambahkan newline untuk JSON Lines
                yield json.dumps({"text": chunk.text}) + "\n"
            # Optional: Add a small delay to simulate typing more visibly for very fast responses
            # import time
            # time.sleep(0.01)

    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        # Kirim pesan error sebagai JSON line juga
        yield json.dumps({"error": f"Maaf, ada masalah teknis di server: {str(e)}"}) + "\n"

# --- Flask API Endpoint ---
@app.route('/chat', methods=['POST'])
def chat_endpoint():
    """
    Handles incoming chat messages from the frontend and streams the Gemini response.
    """
    user_message = request.json.get('message')

    if not user_message:
        # Return a JSON response for bad request
        return jsonify({"error": "Pesan tidak boleh kosong"}), 400

    # Gunakan Response dengan stream_with_context untuk mengirim generator sebagai stream
    # Set mimetype ke 'application/x-ndjson' untuk JSON Lines
    return Response(stream_with_context(generate_gemini_response_stream(user_message)), mimetype='application/x-ndjson')

# --- Initialize Database when the Flask app starts ---
with app.app_context():
    init_db()
    print("Database 'chatbot_data.db' initialized and ready.")

if __name__ == '__main__':
    if not os.getenv("GEMINI_API_KEY"):
        print("Peringatan: Variabel lingkungan 'GEMINI_API_KEY' tidak ditemukan. Harap setel di file .env atau environment Anda.")
    app.run(debug=True, port=5000)