import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template, abort, request, jsonify, session, redirect, url_for
import firebase_admin
from firebase_admin import credentials, auth
import uuid  # For unique filenames
from werkzeug.utils import secure_filename # For security

app = Flask(__name__)

# --- CONFIGURATION ---
app.secret_key = "super_secret_luxe_key"  # Change this in production!


DB_FILE = "doll_website.db"
UPLOAD_FOLDER = 'proofs'  # Define upload folder
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# Create folder if not exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
DB_FILE = "doll_website.db"

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- FIREBASE SETUP ---
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)


# --- DATABASE INITIALIZATION ---
def init_db():
    """Initializes the SQLite database with products and orders tables."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Products Table (Stores ID, Basic info, and full JSON blob for details)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL,
                url TEXT,
                options_count INTEGER,
                meta_json TEXT,    -- Stores lightweight data for homepage
                detail_json TEXT   -- Stores heavy detailed data for product page
            )
        ''')
        
        # Orders Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_ref TEXT PRIMARY KEY,
                uid TEXT NOT NULL,
                email TEXT,
                total_amount TEXT,
                status TEXT DEFAULT 'pending_payment',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                items_json TEXT,    -- Stores cart items as JSON
                shipping_json TEXT, -- Stores address as JSON
                transaction_id TEXT
            )
        ''')
        
        # Create Indexes for Speed
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_price ON products(price)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_uid ON orders(uid)')
        
        conn.commit()
        print("✅ SQLite Database Initialized")

# Run DB Init once on start
init_db()


# --- HELPER FUNCTIONS ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn


# --- ROUTES ---

@app.route("/")
def home():
    user = session.get('user')
    return render_template("index.html", user=user)

@app.route("/api/products", methods=["GET"])
def get_products_api():
    search_query = request.args.get('q', '').strip()
    sort_mode = request.args.get('sort', '')
    
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
    except ValueError:
        page = 1
        limit = 20
        
    offset = (page - 1) * limit
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Build Query
    base_query = "SELECT meta_json, price, name FROM products"
    count_query = "SELECT COUNT(*) FROM products"
    params = []
    
    if search_query:
        # SQLite LIKE is case-insensitive by default for ASCII
        where_clause = " WHERE name LIKE ?"
        base_query += where_clause
        count_query += where_clause
        params.append(f"%{search_query}%")
        
    # 2. Get Total Count
    cursor.execute(count_query, params)
    total_count = cursor.fetchone()[0]
    
    # 3. Apply Sorting
    if sort_mode == 'low-to-high':
        base_query += " ORDER BY price ASC"
    elif sort_mode == 'high-to-low':
        base_query += " ORDER BY price DESC"
    elif sort_mode == 'a-z':
        base_query += " ORDER BY name ASC"
    elif sort_mode == 'z-a':
        base_query += " ORDER BY name DESC"
        
    # 4. Pagination
    base_query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    # 5. Execute & Format
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    
    # Parse JSON strings back to objects
    products = [json.loads(row['meta_json']) for row in rows]
    
    conn.close()

    return jsonify({
        "total": total_count,
        "page": page,
        "limit": limit,
        "count": len(products),
        "products": products
    })

@app.route("/product/<product_id>")
def product(product_id):
    conn = get_db_connection()
    # Fetch just the detail_json blob
    row = conn.execute("SELECT detail_json FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    
    if row is None:
        return abort(404)
        
    # Parse the stored JSON string into a Python dict
    product_data = json.loads(row['detail_json'])
    return render_template("product.html", product=product_data)

@app.route("/my-orders")
def order():
    user = session.get('user')
    return render_template("order.html", user=user)


@app.route("/legal")
def legal_page():
    # This serves the actual HTML file
    return render_template("legal.html")

# --- GERMAN SHORTCUTS (Professional Redirects) ---
# Germans often type /impressum directly. These redirects ensure 
# they land on the correct tab of your legal center.

@app.route("/impressum")
def impressum():
    return redirect(url_for('legal_page', section='impressum'))

@app.route("/datenschutz")
def privacy():
    return redirect(url_for('legal_page', section='privacy'))

@app.route("/agb")
def agb():
    return redirect(url_for('legal_page', section='agb'))

@app.route("/widerruf")
def withdrawal():
    return redirect(url_for('legal_page', section='withdrawal'))
@app.route("/auth")
def auth_page():
    if 'user' in session:
        return redirect(url_for('home'))
    return render_template("auth.html")


# --- BACKEND AUTH API ---

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    id_token = data.get('idToken')

    if not id_token:
        return jsonify({"error": "No token provided"}), 400

    try:
        decoded_token = auth.verify_id_token(id_token)
        session['user'] = {
            'uid': decoded_token['uid'],
            'email': decoded_token.get('email'),
            'name': decoded_token.get('name', 'Collector')
        }
        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"Auth Error: {e}")
        return jsonify({"error": "Invalid token"}), 401


@app.route("/checkout")
def checkout_page():
    return render_template("checkout.html")

@app.route("/order-success")
def order_success_page():
    return render_template("order_success.html")

@app.route("/api/orders", methods=["POST"])
def create_order():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        data = request.json
        uid = session['user']['uid']
        
        # Prepare data for SQLite
        # We store complex nested objects (items, shipping) as JSON strings
        order_ref = data.get('orderRef')
        email = data.get('email')
        total = data.get('total')
        status = data.get('status', 'pending_payment')
        tx_id = data.get('transactionId')
        
        items_json = json.dumps(data.get('items', []))
        shipping_json = json.dumps(data.get('shipping', {}))
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('''
                INSERT INTO orders (order_ref, uid, email, total_amount, status, items_json, shipping_json, transaction_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (order_ref, uid, email, total, status, items_json, shipping_json, tx_id))
            
        return jsonify({"success": True, "order_ref": order_ref}), 200
        
    except Exception as e:
        print(f"Order Creation Error: {e}")
        return jsonify({"error": "Failed to create order"}), 500
    

@app.route("/api/my-orders", methods=["GET"])
def get_my_orders():
    # 1. Auth Check
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    uid = session['user']['uid']

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            # --- STEP 1: DELETE OLD UNPAID ORDERS ---
            # FIX: Added (uid,) as the second argument here
            cursor.execute('''
                DELETE FROM orders 
                WHERE uid = ? 
                AND (status = 'Pending Verification' OR status = 'pending_payment')
                AND created_at < datetime('now', '-24 hours')
            ''', (uid,)) 
            
            conn.commit() # Save the deletion

            # --- STEP 2: FETCH REMAINING ORDERS ---
            cursor.execute('''
                SELECT order_ref, total_amount, status, items_json, shipping_json, created_at, transaction_id
                FROM orders 
                WHERE uid = ? 
                ORDER BY created_at DESC
            ''', (uid,))
            
            rows = cursor.fetchall()
            
            # --- STEP 3: FORMAT DATA ---
            results = []
            for row in rows:
                items_data = json.loads(row[3]) if row[3] else []
                shipping_data = json.loads(row[4]) if row[4] else {}

                results.append({
                    "order_ref": row[0],
                    "total_amount": row[1],
                    "status": row[2],
                    "items": items_data,
                    "shipping": shipping_data,
                    "created_at": row[5],
                    "transaction_id": row[6]
                })

        return jsonify(results), 200

    except Exception as e:
        print(f"Error fetching orders: {e}")
        return jsonify({"error": "Failed to fetch orders"}), 500
    
    
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file and allowed_file(file.filename):
        # Generate unique filename: proof_UID_TIMESTAMP_RANDOM.ext
        uid = session['user']['uid']
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"proof_{uid}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.{ext}"
        
        # Save file
        filename = secure_filename(unique_filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Return the public URL
        return jsonify({
            "success": True, 
            "url": f"/static/proofs/{filename}",
            "filename": filename
        }), 200
        
    return jsonify({"error": "File type not allowed"}), 400


@app.route("/logout")
def logout(): 
    session.pop('user', None)
    return redirect(url_for('home'))



# --- ADMIN ROUTES ---

# 1. Simple Security Check
def is_admin():
    return session.get('is_admin') == True

@app.route("/admin-login", methods=["POST"])
def admin_login():
    # SIMPLE PASSWORD CHECK (Change 'admin123' to your desired password)
    if request.json.get('password') == "admin123":
        session['is_admin'] = True
        return jsonify({"success": True})
    return jsonify({"error": "Wrong password"}), 401

@app.route("/admin")
def admin_dashboard():
    # Serve the HTML file
    return render_template("admin.html")

# 2. API: Get All Data
@app.route("/api/admin/get-all")
def admin_get_all():
    if not is_admin(): return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    
    # Fetch Products
    products_db = conn.execute("SELECT * FROM products").fetchall()
    products = []
    for row in products_db:
        p = dict(row)
        # Parse JSON strings for easier editing on frontend
        try: p['meta_json'] = json.loads(p['meta_json'])
        except: p['meta_json'] = {}
        try: p['detail_json'] = json.loads(p['detail_json'])
        except: p['detail_json'] = {}
        products.append(p)

    # Fetch Orders
    orders_db = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    orders = []
    for row in orders_db:
        o = dict(row)
        try: o['items_json'] = json.loads(o['items_json'])
        except: o['items_json'] = []
        try: o['shipping_json'] = json.loads(o['shipping_json'])
        except: o['shipping_json'] = {}
        orders.append(o)

    conn.close()
    return jsonify({"products": products, "orders": orders})

# 3. API: Update Product
@app.route("/api/admin/product/update", methods=["POST"])
def admin_update_product():
    if not is_admin(): return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    try:
        # Convert objects back to JSON strings for DB
        meta_str = json.dumps(data['meta_json'])
        detail_str = json.dumps(data['detail_json'])
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                UPDATE products 
                SET name=?, price=?, url=?, meta_json=?, detail_json=?
                WHERE id=?
            """, (data['name'], data['price'], data['url'], meta_str, detail_str, data['id']))
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 4. API: Update Order
@app.route("/api/admin/order/update", methods=["POST"])
def admin_update_order():
    if not is_admin(): return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    try:
        # We allow editing status, total_amount, and tracking ID
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                UPDATE orders 
                SET status=?, total_amount=?, transaction_id=?
                WHERE order_ref=?
            """, (data['status'], data['total_amount'], data['transaction_id'], data['order_ref']))
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 5. API: Delete Order
@app.route("/api/admin/order/delete", methods=["POST"])
def admin_delete_order():
    if not is_admin(): return jsonify({"error": "Unauthorized"}), 401
    order_ref = request.json.get('order_ref')
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM orders WHERE order_ref=?", (order_ref,))
        conn.commit()
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)