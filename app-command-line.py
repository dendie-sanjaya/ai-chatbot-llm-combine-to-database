import google.generativeai as genai
import sqlite3
import re # Untuk regex sederhana dalam deteksi entitas
import os # Untuk mendapatkan API key dari environment variable

# --- 1. Konfigurasi Gemini API ---
# Pastikan Anda telah mengatur GEMINI_API_KEY di environment variable Anda
# Contoh: export GEMINI_API_KEY='YOUR_API_KEY'
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set. Please set it.")

genai.configure(api_key=GEMINI_API_KEY)

# Inisialisasi model Gemini
model = genai.GenerativeModel('gemini-2.0-flash') # Anda bisa menggunakan 'gemini-1.5-pro' untuk performa lebih baik

# --- 2. Inisialisasi Database SQLite ---
DB_NAME = 'chatbot_data.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Tabel Products
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            price REAL NOT NULL,
            stock INTEGER
        )
    ''')

    # Tabel Devices (misalnya OLTs)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            location TEXT,
            last_online TEXT
        )
    ''')

    # Contoh data (insert jika belum ada)
    try:
        cursor.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", ('Laptop A', 15000000, 50))
        cursor.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", ('Smartphone B', 7500000, 120))
        cursor.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", ('Keyboard C', 1200000, 200))
        cursor.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", ('Handphone Samsung', 3500000, 80)) # Menambahkan data ini
        
        cursor.execute("INSERT INTO devices (device_id, status, location, last_online) VALUES (?, ?, ?, ?)", ('OLT-BDG-001', 'Online', 'Bandung', '2025-05-25 09:00:00'))
        cursor.execute("INSERT INTO devices (device_id, status, location, last_online) VALUES (?, ?, ?, ?)", ('OLT-JKT-002', 'Offline', 'Jakarta', '2025-05-24 18:30:00'))
    except sqlite3.IntegrityError:
        print("Data sudah ada di database.")
    
    conn.commit()
    conn.close()

# --- 3. Fungsi untuk Menjalankan Query SQL ---
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

# --- 4. Deteksi Niat dan Ekstraksi Entitas ---
def detect_intent_and_extract_entities(user_query):
    query_lower = user_query.lower()
    intent = "unknown"
    entities = {}

    # Niat: Menanyakan harga produk
    if "harga" in query_lower or "price" in query_lower:
        intent = "get_product_price"
        # Ekstraksi nama produk (regex sederhana)
        match = re.search(r'(produk|handphone|laptop|keyboard)\s*([a-z0-9\s]+)', query_lower)
        if match:
            # Ambil bagian setelah "produk/handphone/laptop/keyboard"
            # Coba ambil 2 kata setelah "produk/handphone/laptop/keyboard"
            product_name_candidates = re.findall(r'(?:produk|handphone|laptop|keyboard)\s+([a-z0-9\s]+)', query_lower)
            if product_name_candidates:
                # Ambil yang paling relevan (misalnya yang terakhir)
                product_name = product_name_candidates[-1].strip()
                # Hapus kata kunci seperti "berapa" jika ikut terbawa
                product_name = product_name.replace("berapa", "").strip()
                # Jika ada "adalah x", buang bagian itu
                if "adalah" in product_name:
                    product_name = product_name.split("adalah")[0].strip()

                entities['product_name'] = product_name.title() # Kapitalisasi awal untuk pencocokan DB
            else:
                # Kasus jika hanya "harga" tanpa nama produk jelas
                pass # Biarkan entitas kosong, LLM bisa menanyakan balik

    # Niat: Mengecek status perangkat
    elif "status" in query_lower and ("olt" in query_lower or "router" in query_lower):
        intent = "check_device_status"
        # Ekstraksi Device ID (regex sederhana)
        match = re.search(r'(olt|router)-[a-z]{3}-\d{3}', query_lower)
        if match:
            entities['device_id'] = match.group(0).upper() # Kapitalisasi untuk pencocokan DB

    return intent, entities

# --- 5. Fungsi untuk Mengambil Konteks dari Database ---
def get_context_from_db(intent, entities):
    context = ""
    if intent == "get_product_price" and 'product_name' in entities:
        product_name = entities['product_name']
        query = "SELECT name, price, stock FROM products WHERE name LIKE ? LIMIT 1"
        result = execute_sql_query(query, (f'%{product_name}%',))
        
        if result:
            name, price, stock = result[0]
            context = f"Konteks: Informasi produk {name}: Harga adalah Rp {price:,.0f}. Stok tersedia {stock} unit."
        else:
            context = f"Konteks: Maaf, data harga untuk produk '{product_name}' tidak ditemukan."
    
    elif intent == "check_device_status" and 'device_id' in entities:
        device_id = entities['device_id']
        query = "SELECT device_id, status, location, last_online FROM devices WHERE device_id = ? LIMIT 1"
        result = execute_sql_query(query, (device_id,))

        if result:
            dev_id, status, location, last_online = result[0]
            context = f"Konteks: Status perangkat {dev_id}: Saat ini {status} di {location}. Terakhir online pada {last_online}."
        else:
            context = f"Konteks: Maaf, data status untuk perangkat '{device_id}' tidak ditemukan."
            
    return context

# --- 6. Fungsi Utama untuk Berinteraksi dengan Gemini ---
def chat_with_gemini(user_query):
    print(f"\nUser: {user_query}")

    # Deteksi niat dan entitas
    intent, entities = detect_intent_and_extract_entities(user_query)
    print(f"Detected Intent: {intent}, Entities: {entities}")

    # Ambil konteks dari database
    db_context = get_context_from_db(intent, entities)
    print(f"Database Context: {db_context if db_context else 'No specific context retrieved.'}")

    # Tentukan peran LLM berdasarkan niat
    if intent == "check_device_status":
        llm_role = "Anda adalah customer service yang ramah dan responsif untuk layanan jaringan."
    elif intent == "get_product_price":
        llm_role = "Anda adalah asisten penjualan yang ramah dan informatif untuk produk retail."
    else:
        llm_role = "Anda adalah asisten virtual yang ramah dan membantu."

    # Bangun prompt untuk Gemini
    prompt_parts = [
        f"{llm_role}",
        db_context,
        "---",
        f"Pertanyaan Pengguna: {user_query}",
        "---",
        "Berikan jawaban yang ramah, informatif, dan ringkas berdasarkan konteks yang diberikan. "
        "Jika konteks dari database tidak memberikan informasi yang cukup, katakan bahwa Anda tidak memiliki data spesifik atau butuh informasi lebih lanjut."
    ]
    
    full_prompt = "\n".join(filter(None, prompt_parts)) # Filter None untuk baris kosong

    # Panggil Gemini API
    try:
        response = model.generate_content(full_prompt)
        # Menangani respons yang mungkin memiliki 'parts'
        if hasattr(response, 'parts') and response.parts:
            gemini_response = "".join([part.text for part in response.parts])
        elif hasattr(response, 'text'):
            gemini_response = response.text
        else:
            gemini_response = "Maaf, ada masalah dalam memahami respons dari Gemini."
            print(f"Debug: Unexpected Gemini response structure: {response}")

        print(f"Gemini: {gemini_response}")
        return gemini_response
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return "Maaf, ada masalah teknis. Silakan coba lagi nanti."

# --- Jalankan Program ---
if __name__ == "__main__":
    init_db() # Pastikan database dan data awal sudah ada

    print("Halo! Saya adalah chatbot yang bisa membantu Anda mengecek harga produk atau status perangkat.")
    print("Silakan ketik pertanyaan Anda (ketik 'exit' untuk keluar).")

    while True:
        user_input = input("\nAnda: ")
        if user_input.lower() == 'exit':
            print("Chatbot: Sampai jumpa!")
            break
        
        chat_with_gemini(user_input)