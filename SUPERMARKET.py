import sqlite3
import datetime
import hashlib
import random
import os
import shutil
import json
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify

app = Flask(__name__)
app.secret_key = 'supermarket-secret-key-change-in-production'

# Ensure templates directory and base template exist (with UTF-8 encoding)
os.makedirs('templates', exist_ok=True)
base_html_path = os.path.join('templates', 'base.html')
if not os.path.exists(base_html_path):
    with open(base_html_path, 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title if title else company }} - Supermarket System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #d9e9f7; font-family: 'Segoe UI', Roboto, sans-serif; }
        .card, .stat-card, .table { background-color: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border: none; }
        .stat-card { padding: 20px; margin-bottom: 15px; background: white; border-radius: 16px; transition: 0.2s; }
        .navbar { background-color: #1e466e !important; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
        .navbar-brand, .nav-link { color: white !important; font-weight: 500; }
        .btn-primary { background-color: #1e466e; border-color: #1e466e; }
        .btn-success { background-color: #2b6e3c; border-color: #2b6e3c; }
        h1, h2, h3 { color: #1e466e; font-weight: 600; }
        footer { background-color: #ffffffcc; border-radius: 20px; padding: 12px; margin-top: 20px; text-align: center; }
        .stat-number { font-size: 28px; font-weight: bold; color: #1e466e; }
        /* ADDED: Grid card styling for inventory */
        .product-card { transition: transform 0.2s; margin-bottom: 20px; }
        .product-card:hover { transform: translateY(-5px); box-shadow: 0 8px 16px rgba(0,0,0,0.1); }
    </style>
    {% block extra_head %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark">
        <div class="container">
            <a class="navbar-brand" href="/dashboard">{{ company }}</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav ms-auto">
                    {% if session.username %}
                    <li class="nav-item"><span class="nav-link">User: {{ session.full_name }} ({{ session.role }})</span></li>
                    <li class="nav-item"><a class="nav-link" href="/logout">Logout</a></li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>
    <footer class="container">
        <small>&copy; {{ year }} {{ company }}. All rights reserved.</small>
    </footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block extra_scripts %}{% endblock %}
</body>
</html>''')

# ==================== CONFIGURATION MANAGER ====================
class ConfigManager:
    DEFAULT_CONFIG = {
        "company_name": "MANUEL SUPERMARKET",
        "currency": "Ksh",
        "tax_rates": [{"name": "VAT 16%", "rate": 0.16, "categories": ["general", "electronics", "beverages", "snacks"]}],
        "payment_methods": ["Cash", "Card", "MPESA", "Bank Transfer", "Voucher"],
        "loyalty_points_per_ksh": 0.01,
        "low_stock_threshold": 5,
        "auto_backup": True,
        "backup_interval_days": 1,
        "receipt_footer": "Thank you for shopping with us!\nVisit again!",
        "receipt_header": "MANUEL SUPERMARKET - Your Trusted Store",
        "enable_branch_support": False,
        "branches": [{"id": 1, "name": "Main Store", "location": "Nairobi"}],
        # ADDED: Invoice settings
        "invoice_terms": "Goods once sold cannot be returned",
        "quotation_valid_days": 7
    }

    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                user = json.load(f)
                merged = self.DEFAULT_CONFIG.copy()
                merged.update(user)
                return merged
        else:
            self.save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG

    def save_config(self, config=None):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config or self.config, f, indent=4)

    def get_tax_rate(self, product_category):
        for t in self.config["tax_rates"]:
            if product_category in t.get("categories", []):
                return t["rate"]
        return 0.16

config_manager = ConfigManager()

# ==================== DATABASE ====================
class Database:
    def __init__(self, db_name="supermarket.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.populate_initial_data()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()

    def create_tables(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                category TEXT,
                buying_price REAL,
                selling_price REAL NOT NULL,
                quantity INTEGER DEFAULT 0,
                min_stock INTEGER DEFAULT 5,
                unit TEXT DEFAULT 'pcs',
                supplier TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT UNIQUE,
                customer_name TEXT,
                customer_phone TEXT,
                total_amount REAL,
                discount REAL DEFAULT 0,
                tax REAL DEFAULT 0,
                net_amount REAL,
                payment_method TEXT,
                cash_tendered REAL,
                change_given REAL,
                cashier TEXT,
                sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                branch_id INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT,
                product_id INTEGER,
                product_name TEXT,
                quantity INTEGER,
                unit_price REAL,
                total REAL,
                returned BOOLEAN DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'cashier',
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                contact_person TEXT,
                phone TEXT,
                email TEXT,
                address TEXT
            );
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                movement_type TEXT,
                quantity INTEGER,
                reason TEXT,
                user TEXT,
                movement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_invoice TEXT,
                return_invoice TEXT UNIQUE,
                product_id INTEGER,
                product_name TEXT,
                quantity INTEGER,
                refund_amount REAL,
                reason TEXT,
                cashier TEXT,
                return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS loyalty (
                customer_phone TEXT PRIMARY KEY,
                customer_name TEXT,
                points INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'Bronze',
                total_spent REAL DEFAULT 0,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                amount REAL,
                description TEXT,
                expense_date DATE,
                user TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                action TEXT,
                table_name TEXT,
                record_id TEXT,
                old_value TEXT,
                new_value TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                cashier_name TEXT,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                total_sales REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            -- ADDED: Quotations table
            CREATE TABLE IF NOT EXISTS quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_no TEXT UNIQUE,
                customer_name TEXT,
                customer_phone TEXT,
                quote_date DATE,
                expiry_date DATE,
                items_json TEXT,
                subtotal REAL,
                tax REAL,
                total REAL,
                status TEXT DEFAULT 'draft',
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            -- ADDED: Deliveries table
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT,
                delivery_address TEXT,
                delivery_date DATE,
                status TEXT DEFAULT 'pending',
                driver_name TEXT,
                tracking_info TEXT,
                FOREIGN KEY(invoice_no) REFERENCES sales(invoice_no)
            );
        ''')
        self.conn.commit()

        # Add shift_id column to existing sales tables (for compatibility with old DBs)
        try:
            self.cursor.execute("ALTER TABLE sales ADD COLUMN shift_id INTEGER")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    def populate_initial_data(self):
        # --- Remove any user named 'victor' (case-insensitive) ---
        self.execute_query("DELETE FROM users WHERE LOWER(username) = 'victor'")

        # Admin user: manuel / manuel
        hashed_admin = hashlib.sha256("manuel".encode()).hexdigest()
        if not self.fetch_one("SELECT id FROM users WHERE username='manuel'"):
            self.execute_query("INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
                               ("manuel", hashed_admin, "admin", "Manuel Admin"))
        else:
            self.execute_query("UPDATE users SET password = ? WHERE username='manuel'", (hashed_admin,))

        # Cashier with password 'cashier'
        hashed_cashier = hashlib.sha256("cashier".encode()).hexdigest()
        if not self.fetch_one("SELECT id FROM users WHERE username='cashier'"):
            self.execute_query("INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
                               ("cashier", hashed_cashier, "cashier", "Store Cashier"))

        # Suppliers
        if self.fetch_one("SELECT COUNT(*) FROM suppliers")[0] == 0:
            for i in range(1, 21):
                name = f"Supplier {i}"
                contact = f"Contact Person {i}"
                phone = f"07{random.randint(10000000, 99999999)}"
                email = f"supplier{i}@mail.com"
                address = f"Address {i}, Nairobi"
                self.execute_query("INSERT INTO suppliers (name,contact_person,phone,email,address) VALUES (?,?,?,?,?)",
                                   (name, contact, phone, email, address))

        # Loyalty customers
        first_names = ['John', 'Jane', 'Michael', 'Sarah', 'David', 'Linda', 'James', 'Mary', 'Robert', 'Patricia']
        last_names = ['Doe', 'Smith', 'Johnson', 'Brown', 'Williams', 'Jones', 'Garcia', 'Miller', 'Davis', 'Wilson']
        if self.fetch_one("SELECT COUNT(*) FROM loyalty")[0] == 0:
            for _ in range(50):
                name = f"{random.choice(first_names)} {random.choice(last_names)}"
                phone = f"07{random.randint(10000000, 99999999)}"
                points = random.randint(0, 5000)
                spent = random.randint(0, 50000)
                self.execute_query("INSERT OR IGNORE INTO loyalty (customer_name, customer_phone, points, total_spent) VALUES (?,?,?,?)",
                                   (name, phone, points, spent))

        self.populate_products()

    def populate_products(self):
        self.cursor.execute("SELECT COUNT(*) FROM products")
        if self.cursor.fetchone()[0] > 0:
            return

        self.cursor.execute("SELECT name FROM suppliers")
        suppliers = [row[0] for row in self.cursor.fetchall()]
        if not suppliers:
            suppliers = ["General Supplier"]

        categories = {
            "Grains & Cereals": ["Rice (1kg)", "Rice (5kg)", "Rice (10kg)", "Maize Flour (1kg)", "Maize Flour (2kg)",
                "Wheat Flour (1kg)", "Wheat Flour (2kg)", "Brown Rice (1kg)", "Sorghum Flour", "Millet Flour",
                "Oats (500g)", "Oats (1kg)", "Quinoa (500g)", "Barley (500g)", "Semolina", "Buckwheat",
                "Corn Flour", "Bread Flour", "Self-Rising Flour", "Whole Wheat Flour"],
            "Dairy & Eggs": ["Fresh Milk (1L)", "Fresh Milk (500ml)", "Long Life Milk (1L)", "Skimmed Milk (1L)",
                "Yogurt (500ml)", "Yogurt (1L)", "Cheese (250g)", "Cheese (500g)", "Butter (250g)",
                "Butter (500g)", "Margarine (250g)", "Eggs (6pcs)", "Eggs (12pcs)", "Eggs (30pcs)",
                "Cream (250ml)", "Cream (500ml)", "Sour Cream (200g)", "Cottage Cheese (200g)",
                "Mozzarella (250g)", "Parmesan (150g)"],
            "Beverages": ["Mineral Water (500ml)", "Mineral Water (1L)", "Mineral Water (5L)", "Soda (330ml)",
                "Soda (2L)", "Juice (1L)", "Energy Drink (250ml)", "Sports Drink (500ml)", "Coffee (50g)",
                "Tea Bags (100)", "Green Tea (25)", "Hot Chocolate (200g)", "Milo (400g)", "Porridge Flour (500g)",
                "Chai Mix (250g)", "Cappuccino Mix (200g)", "Sparkling Water (1L)", "Tonic Water (1L)",
                "Coconut Water (500ml)", "Smoothie (300ml)"],
            "Snacks & Confectionery": ["Potato Chips (50g)", "Potato Chips (100g)", "Corn Chips (100g)", "Peanuts (100g)",
                "Cashew Nuts (100g)", "Almonds (100g)", "Chocolate Bar (50g)", "Chocolate Bar (100g)",
                "Candy (50g)", "Gum (10pcs)", "Biscuits (100g)", "Cookies (150g)", "Crackers (200g)",
                "Popcorn (100g)", "Dates (250g)", "Dried Fruit (100g)", "Pretzels (100g)", "Rice Cakes (100g)",
                "Granola Bar (40g)", "Trail Mix (200g)"],
            "Fruits & Vegetables": ["Apples (1kg)", "Bananas (1 bunch)", "Oranges (1kg)", "Mangoes (1kg)", "Grapes (500g)",
                "Pineapple (1pc)", "Watermelon (1kg)", "Avocado (1pc)", "Tomatoes (1kg)", "Onions (1kg)",
                "Potatoes (1kg)", "Cabbage (1pc)", "Spinach (250g)", "Carrots (1kg)", "Cucumber (1pc)",
                "Lettuce (1pc)", "Bell Peppers (3pcs)", "Broccoli (500g)", "Cauliflower (1pc)", "Zucchini (1kg)"],
            "Meat & Fish": ["Beef (1kg)", "Chicken Whole (1pc)", "Chicken Breast (500g)", "Pork (500g)", "Lamb (500g)",
                "Minced Meat (500g)", "Sausages (8pcs)", "Bacon (250g)", "Fish Fillet (500g)", "Fish Whole (1pc)",
                "Prawns (250g)", "Sardines (can)", "Tuna (can)", "Mackerel (1pc)", "Salmon Fillet (250g)",
                "Turkey Breast (500g)", "Duck (1pc)", "Rabbit (1pc)", "Goat Meat (1kg)", "Liver (500g)"],
            "Frozen Foods": ["Frozen Peas (500g)", "Frozen Mixed Veg (500g)", "Frozen Chips (1kg)", "Ice Cream (500ml)",
                "Ice Cream (1L)", "Frozen Chicken (1kg)", "Frozen Fish Fingers (300g)", "Pizza (400g)",
                "Spring Rolls (250g)", "Samosa (250g)", "Frozen Berries (500g)", "Frozen Spinach (400g)",
                "Frozen Broccoli (500g)", "Frozen Corn (500g)", "Frozen Prawns (500g)", "Frozen Burgers (4pcs)",
                "Frozen Waffles (6pcs)", "Frozen Pancakes (6pcs)", "Frozen Yogurt (500ml)", "Frozen Sorbet (500ml)"],
            "Household & Cleaning": ["Detergent (1kg)", "Detergent Liquid (1L)", "Dish Soap (500ml)", "Fabric Softener (1L)",
                "Bleach (1L)", "All-Purpose Cleaner (500ml)", "Glass Cleaner (500ml)", "Floor Cleaner (1L)",
                "Toilet Cleaner (500ml)", "Air Freshener (300ml)", "Paper Towels (2 rolls)", "Toilet Paper (4 rolls)",
                "Trash Bags (10pcs)", "Sponges (3pcs)", "Gloves (1 pair)", "Mop (1pc)", "Broom (1pc)",
                "Dustpan (1pc)", "Laundry Basket", "Storage Containers (3pcs)"],
            "Personal Care": ["Shampoo (250ml)", "Conditioner (250ml)", "Body Wash (500ml)", "Soap Bar (100g)",
                "Toothpaste (100g)", "Toothbrush (1pc)", "Deodorant (50ml)", "Perfume (50ml)", "Lotion (200ml)",
                "Face Cream (50g)", "Sunscreen (100ml)", "Razor (3pcs)", "Shaving Cream (150ml)",
                "Cotton Balls (100pcs)", "Tissues (100pcs)", "Hair Gel (150ml)", "Hair Spray (200ml)",
                "Lip Balm (5g)", "Nail Polish (10ml)", "Makeup Remover (200ml)"],
            "Baby Products": ["Diapers (S)", "Diapers (M)", "Diapers (L)", "Baby Wipes (80pcs)", "Baby Powder (200g)",
                "Baby Oil (200ml)", "Baby Shampoo (200ml)", "Baby Lotion (200ml)", "Baby Cereal (250g)",
                "Formula Milk (400g)", "Fruit Puree (100g)", "Teething Biscuits (100g)", "Baby Bottle (250ml)",
                "Pacifier (1pc)", "Baby Blanket", "Baby Onesie (0-3m)", "Baby Hat", "Baby Socks (3pairs)",
                "Bibs (2pcs)", "Burp Cloths (3pcs)"]
        }
        units = ["pcs", "kg", "L", "g", "ml", "pack"]
        product_count = 0
        for category, product_names in categories.items():
            for name in product_names:
                if product_count >= 520:
                    break
                buying_price = round(random.uniform(10, 800), 2)
                selling_price = round(buying_price * random.uniform(1.2, 1.8), 2)
                quantity = random.randint(20, 500)
                min_stock = random.randint(5, 30)
                unit = random.choice(units)
                barcode = f"890{random.randint(1000000000, 9999999999)}"
                supplier = random.choice(suppliers)
                self.cursor.execute('''INSERT INTO products 
                    (barcode, name, category, buying_price, selling_price, quantity, min_stock, unit, supplier)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (barcode, name, category, buying_price, selling_price, quantity, min_stock, unit, supplier))
                product_count += 1
                self.cursor.execute('''INSERT INTO stock_movements 
                    (product_id, movement_type, quantity, reason, user)
                    VALUES (?, 'stock_in', ?, 'Initial stock', 'system')''',
                                    (product_count, quantity))
        self.conn.commit()
        print(f"Successfully added {product_count} products to inventory!")

    def execute_query(self, query, params=()):
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor

    def fetch_all(self, query, params=()):
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetch_one(self, query, params=()):
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def log_action(self, user, action, table, rid, old="", new=""):
        self.execute_query(
            "INSERT INTO audit_log (user,action,table_name,record_id,old_value,new_value) VALUES (?,?,?,?,?,?)",
            (user, action, table, str(rid), str(old), str(new)))

    def close(self):
        self.conn.close()

db = Database()

# ==================== HELPER FUNCTIONS ====================
def login_required(allowed_roles=None):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if allowed_roles and session.get('role') not in allowed_roles:
                return "Access denied", 403
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

def generate_invoice_no():
    today = datetime.now().date()
    last = db.fetch_one("SELECT invoice_no FROM sales WHERE DATE(sale_date) = ? ORDER BY id DESC LIMIT 1", (today,))
    if last:
        parts = last[0].split('-')
        last_num = int(parts[-1])
        seq = last_num + 1
    else:
        seq = 1
    return f"INV-{today.strftime('%Y%m%d')}-{seq:04d}"

# ADDED: generate unique quotation number
def generate_quote_no():
    today = datetime.now().date()
    last = db.fetch_one("SELECT quote_no FROM quotations WHERE quote_date = ? ORDER BY id DESC LIMIT 1", (today,))
    if last:
        parts = last[0].split('-')
        last_num = int(parts[-1])
        seq = last_num + 1
    else:
        seq = 1
    return f"QT-{today.strftime('%Y%m%d')}-{seq:04d}"

def get_active_shift(user_id):
    """Return active shift for the user if any, else None."""
    return db.fetch_one("SELECT id, cashier_name FROM shifts WHERE user_id = ? AND status = 'active'", (user_id,))

def get_shift_cashier_name(shift_id):
    """Return cashier display name from shift."""
    if shift_id:
        res = db.fetch_one("SELECT cashier_name FROM shifts WHERE id = ?", (shift_id,))
        if res:
            return res[0]
    return session.get('full_name', 'Cashier')

# ==================== ROUTES ====================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed = hashlib.sha256(password.encode()).hexdigest()
        user = db.fetch_one("SELECT id, username, role, full_name FROM users WHERE username=? AND password=?",
                            (username, hashed))
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[2]
            session['full_name'] = user[3]
            db.log_action(username, "LOGIN", "users", user[0], "", "Success")
            return redirect(url_for('dashboard'))
        else:
            return render_template_string('''
                {% extends "base.html" %}
                {% block content %}
                <div class="row justify-content-center"><div class="col-md-4"><div class="card"><div class="card-header">Login</div><div class="card-body">
                <div class="alert alert-danger">Invalid credentials</div>
                <form method="post"><div class="mb-3"><label>Username</label><input type="text" name="username" class="form-control" required></div><div class="mb-3"><label>Password</label><input type="password" name="password" class="form-control"></div><button type="submit" class="btn btn-primary w-100">LOGIN</button></form>
                <div class="mt-3 text-center small">Demo: manuel/manuel (admin) | cashier/cashier (cashier)</div>
                </div></div></div></div>
                {% endblock %}
            ''', title="Login", company=config_manager.config['company_name'], session=session, year=datetime.now().year)
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <div class="row justify-content-center"><div class="col-md-4"><div class="card"><div class="card-header">Login</div><div class="card-body">
        <form method="post"><div class="mb-3"><label>Username</label><input type="text" name="username" class="form-control" required></div><div class="mb-3"><label>Password</label><input type="password" name="password" class="form-control"></div><button type="submit" class="btn btn-primary w-100">LOGIN</button></form>
        </div></div></div></div>
        {% endblock %}
    ''', title="Login", company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required()
def dashboard():
    today = datetime.now().date()
    total_products = db.fetch_one("SELECT COUNT(*) FROM products")[0]
    low_stock_items = db.fetch_all("SELECT name, quantity, min_stock FROM products WHERE quantity <= min_stock")
    low_stock_count = len(low_stock_items)
    today_sales = db.fetch_one("SELECT COALESCE(SUM(net_amount),0), COUNT(*) FROM sales WHERE DATE(sale_date)=?",
                               (today,))
    total_sales = db.fetch_one("SELECT COALESCE(SUM(net_amount),0) FROM sales")[0]

    top_products = db.fetch_all("""
        SELECT p.name, SUM(si.quantity) as qty, SUM(si.total) as revenue
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        GROUP BY si.product_id
        ORDER BY qty DESC
        LIMIT 5
    """)

    top_product_today = db.fetch_one("""
        SELECT p.name, SUM(si.quantity) 
        FROM sale_items si JOIN sales s ON si.invoice_no = s.invoice_no 
        JOIN products p ON si.product_id = p.id 
        WHERE DATE(s.sale_date)=? 
        GROUP BY si.product_id 
        ORDER BY SUM(si.quantity) DESC LIMIT 1
    """, (today,))
    top_product = (top_product_today[0], top_product_today[1]) if top_product_today else ('None', 0)

    month_start = today.replace(day=1)
    expenses_month = db.fetch_one("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
                                  (month_start, today))[0]
    pending_returns = db.fetch_one("SELECT COUNT(*) FROM returns WHERE DATE(return_date)=?", (today,))[0]

    # Shift info for cashier
    active_shift = None
    if session['role'] == 'cashier':
        active_shift = get_active_shift(session['user_id'])

    stats = {
        'total_products': total_products,
        'low_stock': low_stock_count,
        'low_stock_items': low_stock_items,
        'today_sales': today_sales[0],
        'today_transactions': today_sales[1],
        'total_sales': total_sales,
        'top_product': top_product,
        'top_products': top_products,
        'expenses_month': expenses_month,
        'pending_returns': pending_returns,
        'active_shift': active_shift
    }
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <div class="row mb-4">
            <div class="col-md-3"><div class="stat-card"><div>Total Products</div><div class="stat-number">{{ stats.total_products }}</div><div>{{ stats.low_stock }} low stock</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div>Today's Sales</div><div class="stat-number">{{ currency }} {{ "{:,.2f}".format(stats.today_sales) }}</div><div>{{ stats.today_transactions }} transactions</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div>Total Revenue</div><div class="stat-number">{{ currency }} {{ "{:,.2f}".format(stats.total_sales) }}</div><div>Lifetime</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div>Daily Target</div><div class="stat-number">{{ currency }} 100,000</div><div>Today's Goal</div></div></div>
        </div>
        <div class="row mb-4">
            <div class="col-md-6"><div class="stat-card"><div>Top Selling Products (All Time)</div><table class="table table-sm">{% for p in stats.top_products %}<tr><td>{{ p[0] }}</td><td>{{ p[1] }} units</td><td>{{ currency }} {{ p[2] }}</td></tr>{% endfor %}</table></div></div>
            <div class="col-md-6"><div class="stat-card"><div>Low Stock Alerts</div>{% if stats.low_stock_items %}<ul>{% for item in stats.low_stock_items %}<li>{{ item[0] }} - Stock: {{ item[1] }} (Min: {{ item[2] }})</li>{% endfor %}</ul>{% else %}<div class="alert alert-success">No low stock items</div>{% endif %}</div></div>
        </div>
        <div class="row">
            {% if session.role == 'admin' %}
            <div class="col-md-3 mb-3"><a href="/pos" class="btn btn-success w-100 py-3">Point of Sale</a></div>
            <div class="col-md-3 mb-3"><a href="/inventory" class="btn btn-primary w-100 py-3">Inventory</a></div>
            <div class="col-md-3 mb-3"><a href="/reports" class="btn btn-secondary w-100 py-3">Reports</a></div>
            <div class="col-md-3 mb-3"><a href="/customers" class="btn btn-warning w-100 py-3">Customers</a></div>
            <div class="col-md-3 mb-3"><a href="/suppliers" class="btn btn-info w-100 py-3">Suppliers</a></div>
            <div class="col-md-3 mb-3"><a href="/users" class="btn btn-danger w-100 py-3">Users</a></div>
            <div class="col-md-3 mb-3"><a href="/stock_alerts" class="btn btn-danger w-100 py-3">Stock Alerts {% if stats.low_stock > 0 %}<span class="badge bg-danger">{{ stats.low_stock }}</span>{% endif %}</a></div>
            <div class="col-md-3 mb-3"><a href="/returns" class="btn btn-secondary w-100 py-3">Returns</a></div>
            <div class="col-md-3 mb-3"><a href="/loyalty" class="btn btn-warning w-100 py-3">Loyalty</a></div>
            <div class="col-md-3 mb-3"><a href="/expenses" class="btn btn-info w-100 py-3">Expenses</a></div>
            <div class="col-md-3 mb-3"><a href="/backup" class="btn btn-dark w-100 py-3">Backup</a></div>
            <div class="col-md-3 mb-3"><a href="/charts" class="btn btn-success w-100 py-3">Advanced Charts</a></div>
            <div class="col-md-3 mb-3"><a href="/settings" class="btn btn-primary w-100 py-3">Settings</a></div>
            <div class="col-md-3 mb-3"><a href="/shift/report" class="btn btn-info w-100 py-3">Shift Report</a></div>
            <!-- ADDED: Invoice Panel Button -->
            <div class="col-md-3 mb-3"><a href="/invoice_panel" class="btn btn-dark w-100 py-3">📄 Invoice Panel</a></div>
            {% else %}
            <div class="col-md-12 mb-3">
                {% if stats.active_shift %}
                    <div class="alert alert-success">Active shift: {{ stats.active_shift[1] }} | <a href="/end_shift" class="btn btn-sm btn-danger">End Shift</a></div>
                {% else %}
                    <div class="alert alert-warning">No active shift. <a href="/start_shift" class="btn btn-sm btn-success">Start Shift</a></div>
                {% endif %}
            </div>
            <div class="col-md-4 mx-auto mb-3"><a href="/pos" class="btn btn-success w-100 py-3">Point of Sale</a></div>
            <div class="col-md-4 mx-auto mb-3"><a href="/returns" class="btn btn-secondary w-100 py-3">Returns</a></div>
            <div class="col-md-4 mx-auto mb-3"><a href="/loyalty" class="btn btn-warning w-100 py-3">Loyalty</a></div>
            <div class="col-md-4 mx-auto mb-3"><a href="/change_password" class="btn btn-info w-100 py-3">Change Password</a></div>
            <!-- ADDED: Invoice Panel Button for cashier -->
            <div class="col-md-4 mx-auto mb-3"><a href="/invoice_panel" class="btn btn-dark w-100 py-3">Invoice Panel</a></div>
            {% endif %}
        </div>
        {% endblock %}
    ''', stats=stats, company=config_manager.config['company_name'], currency=config_manager.config['currency'],
                                  session=session, year=datetime.now().year, month_start=month_start)

@app.route('/start_shift', methods=['GET', 'POST'])
@login_required(allowed_roles=['cashier', 'admin'])
def start_shift():
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        if not display_name:
            display_name = session['full_name']
        # End any open shift first
        db.execute_query("UPDATE shifts SET end_time = CURRENT_TIMESTAMP, status = 'ended' WHERE user_id = ? AND status = 'active'", (session['user_id'],))
        db.execute_query("INSERT INTO shifts (user_id, cashier_name, status) VALUES (?, ?, 'active')", (session['user_id'], display_name))
        return redirect(url_for('dashboard'))
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <div class="row justify-content-center"><div class="col-md-6"><div class="card"><div class="card-header">Start Shift</div><div class="card-body">
        <form method="post">
            <div class="mb-3"><label>Name to show on receipts</label><input type="text" name="display_name" class="form-control" value="{{ session.full_name }}" placeholder="e.g., John Doe"></div>
            <button type="submit" class="btn btn-primary">Start Shift</button>
            <a href="/dashboard" class="btn btn-secondary">Cancel</a>
        </form>
        </div></div></div></div>
        {% endblock %}
    ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/end_shift')
@login_required(allowed_roles=['cashier', 'admin'])
def end_shift():
    db.execute_query("UPDATE shifts SET end_time = CURRENT_TIMESTAMP, status = 'ended' WHERE user_id = ? AND status = 'active'", (session['user_id'],))
    return redirect(url_for('dashboard'))

@app.route('/shift/report')
@login_required(allowed_roles=['admin'])
def shift_report():
    shifts = db.fetch_all("""
        SELECT s.id, u.username, s.cashier_name, s.start_time, s.end_time, s.total_sales, s.status
        FROM shifts s JOIN users u ON s.user_id = u.id
        ORDER BY s.start_time DESC
    """)
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Shift Reports</h2>
        <table class="table bg-white">
            <thead><tr><th>ID</th><th>Cashier User</th><th>Display Name</th><th>Start</th><th>End</th><th>Total Sales ({{ currency }})</th><th>Status</th></tr></thead>
            <tbody>
                {% for s in shifts %}
                <tr>
                    <td>{{ s[0] }}</td><td>{{ s[1] }}</td><td>{{ s[2] }}</td>
                    <td>{{ s[3] }}</td><td>{{ s[4] if s[4] else 'Active' }}</td>
                    <td>{{ s[5] }}</td><td>{{ s[6] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endblock %}
    ''', shifts=shifts, currency=config_manager.config['currency'], company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/pos', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin', 'cashier'])
def pos():
    # Shift check for cashier (admin can bypass)
    if session['role'] == 'cashier':
        active_shift = get_active_shift(session['user_id'])
        if not active_shift:
            return redirect(url_for('start_shift'))
        current_shift_id = active_shift[0]
        shift_cashier_name = active_shift[1]
    else:
        current_shift_id = None
        shift_cashier_name = session['full_name']

    if request.method == 'POST':
        data = request.json
        cart = data['cart']
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')
        payment_method = data.get('payment_method', 'Cash')
        subtotal = sum(item['total'] for item in cart)
        discount = data.get('discount', 0)
        tax = subtotal * 0.16
        net_total = subtotal - discount + tax
        invoice_no = generate_invoice_no()
        try:
            db.execute_query(
                "INSERT INTO sales (invoice_no, customer_name, customer_phone, total_amount, discount, tax, net_amount, payment_method, cashier, shift_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (invoice_no, customer_name, customer_phone, subtotal, discount, tax, net_total, payment_method, shift_cashier_name, current_shift_id))
            for item in cart:
                db.execute_query(
                    "INSERT INTO sale_items (invoice_no, product_id, product_name, quantity, unit_price, total) VALUES (?,?,?,?,?,?)",
                    (invoice_no, item['id'], item['name'], item['quantity'], item['price'], item['total']))
                db.execute_query("UPDATE products SET quantity = quantity - ? WHERE id=?",
                                 (item['quantity'], item['id']))
            if customer_phone:
                points = int(subtotal * 0.01)
                existing = db.fetch_one("SELECT customer_phone FROM loyalty WHERE customer_phone=?", (customer_phone,))
                if not existing:
                    db.execute_query("INSERT INTO loyalty (customer_phone, customer_name, points) VALUES (?,?,?)",
                                     (customer_phone, customer_name if customer_name else "Guest", points))
                else:
                    db.execute_query(
                        "UPDATE loyalty SET points = points + ?, total_spent = total_spent + ? WHERE customer_phone=?",
                        (points, net_total, customer_phone))
            # Update shift total sales
            if current_shift_id:
                db.execute_query("UPDATE shifts SET total_sales = total_sales + ? WHERE id = ?", (net_total, current_shift_id))
            db.log_action(session['username'], "SALE", "sales", invoice_no, "", f"Total: {net_total}")
            return jsonify({'status': 'success', 'invoice': invoice_no, 'net_total': net_total, 'cashier': shift_cashier_name})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    else:
        products = db.fetch_all("SELECT id, name, selling_price, quantity, category FROM products WHERE quantity > 0 ORDER BY name")
        customers = db.fetch_all("SELECT customer_name, customer_phone FROM loyalty ORDER BY customer_name")
        return render_template_string('''
            {% extends "base.html" %}
            {% block extra_head %}
            <style>.cart-item{cursor:pointer;}</style>
            {% endblock %}
            {% block content %}
            <div class="row">
                <div class="col-md-7">
                    <div class="card">
                        <div class="card-header">Products</div>
                        <div class="card-body">
                            <div class="row mb-2">
                                <div class="col-md-6"><input type="text" id="barcodeInput" placeholder="Scan barcode" class="form-control"></div>
                                <div class="col-md-6"><select id="categoryFilter" class="form-select"><option value="all">All Categories</option>{% set cats = [] %}{% for p in products %}{% if p[4] not in cats %}{% set _ = cats.append(p[4]) %}<option value="{{ p[4] }}">{{ p[4] }}</option>{% endif %}{% endfor %}</select></div>
                            </div>
                            <input type="text" id="search" class="form-control mb-3" placeholder="Search product...">
                            <div style="height:500px; overflow-y:auto;">
                                <table class="table table-sm table-hover">
                                    <thead>
                                        <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Category</th><th></th></tr>
                                    </thead>
                                    <tbody id="product-list">
                                        {% for p in products %}
                                        <tr data-category="{{ p[4] }}">
                                            <td>{{ p[0] }}</td><td>{{ p[1] }}</td>
                                            <td>{{ currency }} {{ p[2] }}</td><td>{{ p[3] }}</td><td>{{ p[4] }}</td>
                                            <td><button class="btn btn-sm btn-success add-to-cart" data-id="{{ p[0] }}" data-name="{{ p[1] }}" data-price="{{ p[2] }}" data-stock="{{ p[3] }}">Add</button></td>
                                        </tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-5">
                    <div class="card">
                        <div class="card-header">Shopping Cart</div>
                        <div class="card-body">
                            <div style="height:300px; overflow-y:auto;">
                                <table class="table table-sm">
                                    <thead><tr><th>Name</th><th>Qty</th><th>Price</th><th>Total</th><th></th></tr></thead>
                                    <tbody id="cart-items"></tbody>
                                </table>
                            </div>
                            <hr>
                            <div class="mb-2"><label>Customer Name</label><input type="text" id="cust_name" class="form-control" list="customerList"></div>
                            <div class="mb-2"><label>Customer Phone</label><input type="text" id="cust_phone" class="form-control" list="customerList"></div>
                            <datalist id="customerList">
                                {% for c in customers %}
                                <option value="{{ c[1] }}">{{ c[0] }} - {{ c[1] }}</option>
                                {% endfor %}
                            </datalist>
                            <div class="mb-2"><label>Discount (%)</label><input type="number" id="discount" class="form-control" value="0"></div>
                            <div class="mb-2"><label>Payment Method</label><select id="paymentMethod" class="form-select"><option>Cash</option><option>Card</option><option>MPESA</option><option>Bank Transfer</option></select></div>
                            <h4>Total: <span id="total">{{ currency }} 0.00</span></h4>
                            <button id="checkout-btn" class="btn btn-success w-100">Checkout</button>
                        </div>
                    </div>
                </div>
            </div>
            <script>
                let cart = [];
                function updateCartUI() {
                    let tbody = document.getElementById('cart-items');
                    tbody.innerHTML = '';
                    let total = 0;
                    cart.forEach((item, idx) => {
                        let row = tbody.insertRow();
                        row.insertCell(0).innerText = item.name;
                        row.insertCell(1).innerText = item.qty;
                        row.insertCell(2).innerText = '{{ currency }} ' + item.price.toFixed(2);
                        row.insertCell(3).innerText = '{{ currency }} ' + (item.price * item.qty).toFixed(2);
                        let delCell = row.insertCell(4);
                        let delBtn = document.createElement('button');
                        delBtn.innerText = 'X';
                        delBtn.className = 'btn btn-sm btn-danger';
                        delBtn.onclick = () => { cart.splice(idx,1); updateCartUI(); };
                        delCell.appendChild(delBtn);
                        total += item.price * item.qty;
                    });
                    document.getElementById('total').innerText = '{{ currency }} ' + total.toFixed(2);
                }
                function addToCart(id, name, price, stock) {
                    let qty = prompt('Enter quantity', '1');
                    if(qty && !isNaN(qty) && parseInt(qty) > 0 && parseInt(qty) <= stock) {
                        let existing = cart.find(i => i.id == id);
                        if(existing) existing.qty += parseInt(qty);
                        else cart.push({id: id, name: name, price: price, qty: parseInt(qty)});
                        updateCartUI();
                    } else alert('Invalid quantity or out of stock');
                }
                document.querySelectorAll('.add-to-cart').forEach(btn => {
                    btn.addEventListener('click', () => {
                        let id = btn.dataset.id;
                        let name = btn.dataset.name;
                        let price = parseFloat(btn.dataset.price);
                        let stock = parseInt(btn.dataset.stock);
                        addToCart(id, name, price, stock);
                    });
                });
                document.getElementById('barcodeInput').addEventListener('change', function() {
                    let barcode = this.value;
                    fetch(`/product_by_barcode/${barcode}`)
                        .then(res => res.json())
                        .then(product => {
                            if(product && product.id) {
                                addToCart(product.id, product.name, product.price, product.stock);
                            } else {
                                alert('Product not found');
                            }
                            this.value = '';
                        });
                });
                document.getElementById('categoryFilter').addEventListener('change', function() {
                    let selected = this.value;
                    let rows = document.querySelectorAll('#product-list tr');
                    rows.forEach(row => {
                        let category = row.dataset.category;
                        if(selected === 'all' || category === selected) {
                            row.style.display = '';
                        } else {
                            row.style.display = 'none';
                        }
                    });
                });
                document.getElementById('search').addEventListener('keyup', function() {
                    let term = this.value.toLowerCase();
                    let rows = document.querySelectorAll('#product-list tr');
                    rows.forEach(row => {
                        let name = row.cells[1].innerText.toLowerCase();
                        if(name.includes(term)) row.style.display = '';
                        else row.style.display = 'none';
                    });
                });
                document.getElementById('cust_phone').addEventListener('change', function() {
                    let phone = this.value;
                    let customerList = document.getElementById('customerList').options;
                    for(let opt of customerList) {
                        if(opt.value === phone) {
                            document.getElementById('cust_name').value = opt.text.split(' - ')[0];
                            break;
                        }
                    }
                });
                document.getElementById('checkout-btn').addEventListener('click', () => {
                    if(cart.length === 0) { alert('Cart empty'); return; }
                    let paymentMethod = document.getElementById('paymentMethod').value;
                    let mpesaPhone = '';
                    if(paymentMethod === 'MPESA') {
                        mpesaPhone = prompt("Enter MPESA phone number (e.g., 0712345678):");
                        if(!mpesaPhone || mpesaPhone.trim() === '') {
                            alert("MPESA phone number is required!");
                            return;
                        }
                        if(!confirm(`Simulating MPESA payment of ${document.getElementById('total').innerText} from ${mpesaPhone}. Proceed?`)) {
                            return;
                        }
                        document.getElementById('cust_phone').value = mpesaPhone;
                    }
                    let customerPhone = document.getElementById('cust_phone').value;
                    if (!customerPhone && paymentMethod !== 'MPESA') {
                        let phoneInput = prompt("Enter customer phone number for loyalty points (or cancel to skip):");
                        if (phoneInput !== null && phoneInput.trim() !== "") {
                            customerPhone = phoneInput.trim();
                            document.getElementById('cust_phone').value = customerPhone;
                            let customerList = document.getElementById('customerList').options;
                            let foundName = "";
                            for(let opt of customerList) {
                                if(opt.value === customerPhone) {
                                    foundName = opt.text.split(' - ')[0];
                                    break;
                                }
                            }
                            if (foundName) {
                                document.getElementById('cust_name').value = foundName;
                            } else {
                                let nameInput = prompt("New customer! Enter customer name:", "Walk-in Customer");
                                if (nameInput) document.getElementById('cust_name').value = nameInput;
                            }
                        }
                    }
                    let discount = parseFloat(document.getElementById('discount').value) || 0;
                    let subtotal = cart.reduce((s,i)=> s + i.price * i.qty, 0);
                    let discountAmount = subtotal * discount / 100;
                    let net = subtotal - discountAmount + (subtotal - discountAmount) * 0.16;
                    fetch('/pos', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            cart: cart.map(i => ({id: i.id, name: i.name, quantity: i.qty, price: i.price, total: i.price * i.qty})),
                            customer_name: document.getElementById('cust_name').value,
                            customer_phone: document.getElementById('cust_phone').value,
                            payment_method: paymentMethod,
                            discount: discountAmount
                        })
                    }).then(res => res.json()).then(data => {
                        if(data.status === 'success') {
                            if(confirm('Sale complete! Print receipt?')) {
                                let receipt = `{{ config_manager.config['receipt_header'] }}\\nInvoice: ${data.invoice}\\nCashier: ${data.cashier}\\nTotal: {{ currency }} ${data.net_total.toFixed(2)}\\n{{ receipt_footer }}`;
                                let printWindow = window.open('', '_blank');
                                printWindow.document.write(`<pre>${receipt}</pre>`);
                                printWindow.print();
                            }
                            cart = [];
                            updateCartUI();
                            location.reload();
                        } else alert('Error: '+data.message);
                    });
                });
            </script>
            {% endblock %}
        ''', products=products, customers=customers, company=config_manager.config['company_name'],
                                      currency=config_manager.config['currency'],
                                      receipt_footer=config_manager.config['receipt_footer'], session=session,
                                      year=datetime.now().year, config_manager=config_manager)

@app.route('/product_by_barcode/<barcode>')
@login_required(allowed_roles=['admin', 'cashier'])
def product_by_barcode(barcode):
    prod = db.fetch_one("SELECT id, name, selling_price, quantity FROM products WHERE barcode=? AND quantity>0", (barcode,))
    if prod:
        return jsonify({'id': prod[0], 'name': prod[1], 'price': prod[2], 'stock': prod[3]})
    return jsonify({}), 404

@app.route('/update_stock/<int:pid>', methods=['POST'])
@login_required(allowed_roles=['admin'])
def update_stock(pid):
    try:
        qty = int(request.form.get('quantity'))
        if qty < 0:
            return "Quantity cannot be negative", 400
        db.execute_query("UPDATE products SET quantity = ? WHERE id=?", (qty, pid))
        db.log_action(session['username'], "UPDATE_STOCK", "products", pid, "", f"New quantity: {qty}")
        return '', 204
    except (TypeError, ValueError):
        return "Invalid quantity", 400

@app.route('/inventory')
@login_required(allowed_roles=['admin'])
def inventory():
    products = db.fetch_all("SELECT id, barcode, name, category, buying_price, selling_price, quantity, min_stock, unit, supplier FROM products")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Inventory Management</h2>
        <div class="mb-3">
            <button class="btn btn-success" data-bs-toggle="modal" data-bs-target="#addModal">+ Add Product</button>
            <!-- ADDED: Toggle between Table and Grid View -->
            <button class="btn btn-secondary" id="toggleViewBtn">Switch to Grid View</button>
        </div>
        <div id="tableView">
            <table class="table table-bordered bg-white">
                <thead>
                    <tr><th>ID</th><th>Barcode</th><th>Name</th><th>Category</th><th>Buying</th><th>Selling</th><th>Stock</th><th>Min</th><th>Unit</th><th>Supplier</th><th>Action</th></tr>
                </thead>
                <tbody>
                    {% for p in products %}
                    <tr>
                        <td>{{ p[0] }}</td><td>{{ p[1] }}</td><td>{{ p[2] }}</td><td>{{ p[3] }}</td>
                        <td>{{ currency }} {{ p[4] }}</td><td>{{ currency }} {{ p[5] }}</td>
                        <td id="stock-{{ p[0] }}">{{ p[6] }}</td><td>{{ p[7] }}</td><td>{{ p[8] }}</td><td>{{ p[9] }}</td>
                        <td>
                            <a href="/inventory/delete/{{ p[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">Delete</a>
                            <button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#stockModal{{ p[0] }}">Update Stock</button>
                        </td>
                    </tr>
                    <!-- Stock Update Modal -->
                    <div class="modal fade" id="stockModal{{ p[0] }}" tabindex="-1">
                        <div class="modal-dialog">
                            <div class="modal-content">
                                <form method="post" action="/update_stock/{{ p[0] }}">
                                    <div class="modal-header"><h5 class="modal-title">Update Stock for {{ p[2] }}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                                    <div class="modal-body"><label>New Quantity:</label><input type="number" name="quantity" class="form-control" value="{{ p[6] }}" min="0" required></div>
                                    <div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>
                                </form>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <!-- ADDED: Grid view (hidden initially) -->
        <div id="gridView" style="display:none;">
            <div class="row">
                {% for p in products %}
                <div class="col-md-3">
                    <div class="card product-card">
                        <div class="card-body">
                            <h5 class="card-title">{{ p[2] }}</h5>
                            <p class="card-text">Category: {{ p[3] }}<br>Price: {{ currency }} {{ p[5] }}<br>Stock: {{ p[6] }} {{ p[8] }}<br>Supplier: {{ p[9] }}</p>
                            <button class="btn btn-sm btn-warning" data-bs-toggle="modal" data-bs-target="#stockModal{{ p[0] }}">Update Stock</button>
                            <a href="/inventory/delete/{{ p[0] }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="modal fade" id="addModal"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/inventory/add"><div class="modal-header"><h5 class="modal-title">Add Product</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-2"><label>Name</label><input type="text" name="name" class="form-control" required></div><div class="mb-2"><label>Barcode (optional)</label><input type="text" name="barcode" class="form-control"></div><div class="mb-2"><label>Category</label><input type="text" name="category" class="form-control"></div><div class="mb-2"><label>Buying Price</label><input type="number" step="0.01" name="buying_price" class="form-control" min="0"></div><div class="mb-2"><label>Selling Price</label><input type="number" step="0.01" name="selling_price" class="form-control" required min="0"></div><div class="mb-2"><label>Quantity</label><input type="number" name="quantity" class="form-control" min="0"></div><div class="mb-2"><label>Min Stock</label><input type="number" name="min_stock" class="form-control" value="5" min="0"></div><div class="mb-2"><label>Unit</label><input type="text" name="unit" class="form-control" value="pcs"></div><div class="mb-2"><label>Supplier</label><input type="text" name="supplier" class="form-control"></div></div><div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div></form></div></div></div>
        <script>
            const toggleBtn = document.getElementById('toggleViewBtn');
            const tableView = document.getElementById('tableView');
            const gridView = document.getElementById('gridView');
            toggleBtn.addEventListener('click', () => {
                if (tableView.style.display !== 'none') {
                    tableView.style.display = 'none';
                    gridView.style.display = 'block';
                    toggleBtn.innerText = 'Switch to Table View';
                } else {
                    tableView.style.display = 'block';
                    gridView.style.display = 'none';
                    toggleBtn.innerText = 'Switch to Grid View';
                }
            });
        </script>
        {% endblock %}
    ''', products=products, currency=config_manager.config['currency'], company=config_manager.config['company_name'],
                                  session=session, year=datetime.now().year)

@app.route('/inventory/add', methods=['POST'])
@login_required(allowed_roles=['admin'])
def add_product():
    data = request.form
    name = data['name']
    barcode = data.get('barcode') or f"890{random.randint(1000000000, 9999999999)}"
    category = data.get('category', '')
    try:
        buying_price = float(data.get('buying_price', 0))
        if buying_price < 0:
            return "Buying price cannot be negative", 400
        selling_price = float(data['selling_price'])
        if selling_price < 0:
            return "Selling price cannot be negative", 400
        quantity = int(data.get('quantity', 0))
        if quantity < 0:
            return "Quantity cannot be negative", 400
        min_stock = int(data.get('min_stock', 5))
        if min_stock < 0:
            return "Minimum stock cannot be negative", 400
    except ValueError:
        return "Invalid numeric value", 400
    unit = data.get('unit', 'pcs')
    supplier = data.get('supplier', '')
    db.execute_query(
        "INSERT INTO products (barcode,name,category,buying_price,selling_price,quantity,min_stock,unit,supplier) VALUES (?,?,?,?,?,?,?,?,?)",
        (barcode, name, category, buying_price, selling_price, quantity, min_stock, unit, supplier))
    db.log_action(session['username'], "INSERT", "products", name, "", f"Added product {name}")
    return redirect(url_for('inventory'))

@app.route('/inventory/delete/<int:pid>')
@login_required(allowed_roles=['admin'])
def delete_product(pid):
    db.execute_query("DELETE FROM products WHERE id=?", (pid,))
    return redirect(url_for('inventory'))

@app.route('/reports')
@login_required()
def reports():
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    sales = db.fetch_all(
        '''SELECT DATE(sale_date), COUNT(*), SUM(net_amount) FROM sales WHERE DATE(sale_date) BETWEEN ? AND ? GROUP BY DATE(sale_date) ORDER BY sale_date''',
        (from_date, to_date))
    top_products = db.fetch_all(
        '''SELECT p.name, SUM(si.quantity), SUM(si.total) FROM sale_items si JOIN products p ON si.product_id=p.id JOIN sales s ON si.invoice_no=s.invoice_no WHERE DATE(s.sale_date) BETWEEN ? AND ? GROUP BY si.product_id ORDER BY SUM(si.quantity) DESC LIMIT 10''',
        (from_date, to_date))
    payments = db.fetch_all(
        '''SELECT payment_method, COUNT(*), SUM(net_amount) FROM sales WHERE DATE(sale_date) BETWEEN ? AND ? GROUP BY payment_method''',
        (from_date, to_date))
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Sales Reports</h2>
        <form method="get" class="row g-3 mb-4"><div class="col-auto"><input type="date" name="from_date" value="{{ from_date }}" class="form-control"></div><div class="col-auto"><input type="date" name="to_date" value="{{ to_date }}" class="form-control"></div><div class="col-auto"><button type="submit" class="btn btn-primary">Generate</button></div></form>
        <h4>Daily Sales</h4><table class="table table-bordered bg-white"><thead><tr><th>Date</th><th>Transactions</th><th>Total ({{ currency }})</th></tr></thead><tbody>{% for s in sales %}<tr><td>{{ s[0] }}</td><td>{{ s[1] }}</td><td>{{ s[2] }}</td></tr>{% endfor %}</tbody></table>
        <h4>Top Products</h4><table class="table bg-white"><thead><tr><th>Product</th><th>Quantity</th><th>Revenue</th></tr></thead><tbody>{% for p in top_products %}<tr><td>{{ p[0] }}</td><td>{{ p[1] }}</td><td>{{ currency }} {{ p[2] }}</td></tr>{% endfor %}</tbody></table>
        <h4>Payment Methods</h4><table class="table bg-white"><thead><tr><th>Method</th><th>Count</th><th>Amount</th></tr></thead><tbody>{% for pm in payments %}<tr><td>{{ pm[0] }}</td><td>{{ pm[1] }}</td><td>{{ currency }} {{ pm[2] }}</td></tr>{% endfor %}</tbody></table>
        {% endblock %}
    ''', sales=sales, top_products=top_products, payments=payments, from_date=from_date, to_date=to_date,
                                  currency=config_manager.config['currency'],
                                  company=config_manager.config['company_name'], session=session,
                                  year=datetime.now().year)

@app.route('/customers')
@login_required()
def customers():
    rows = db.fetch_all(
        '''SELECT DISTINCT customer_name, customer_phone, COUNT(*) as visits, SUM(net_amount) as total_spent FROM sales WHERE customer_name IS NOT NULL AND customer_name != '' GROUP BY customer_name, customer_phone ORDER BY total_spent DESC''')
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Customer Management</h2>
        <table class="table bg-white"><thead><tr><th>Name</th><th>Phone</th><th>Visits</th><th>Total Spent ({{ currency }})</th></tr></thead><tbody>{% for c in customers %}<tr><td>{{ c[0] }}</td><td>{{ c[1] }}</td><td>{{ c[2] }}</td><td>{{ c[3] }}</td></tr>{% endfor %}</tbody></table>
        {% endblock %}
    ''', customers=rows, currency=config_manager.config['currency'], company=config_manager.config['company_name'],
                                  session=session, year=datetime.now().year)

# MODIFIED: Added edit capability for suppliers
@app.route('/suppliers')
@login_required(allowed_roles=['admin'])
def suppliers():
    rows = db.fetch_all("SELECT id, name, contact_person, phone, email, address FROM suppliers")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Supplier Management</h2>
        <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#addSupplierModal">+ Add Supplier</button>
        <table class="table bg-white">
            <thead><tr><th>ID</th><th>Name</th><th>Contact Person</th><th>Phone</th><th>Email</th><th>Address</th><th>Actions</th></tr></thead>
            <tbody>
                {% for s in suppliers %}
                <tr>
                    <td>{{ s[0] }}</td><td>{{ s[1] }}</td><td>{{ s[2] }}</td><td>{{ s[3] }}</td><td>{{ s[4] }}</td><td>{{ s[5] }}</td>
                    <td>
                        <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#editSupplierModal{{ s[0] }}">Edit</button>
                        <a href="/suppliers/delete/{{ s[0] }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete supplier?')">Delete</a>
                    </td>
                </tr>
                <!-- Edit Modal -->
                <div class="modal fade" id="editSupplierModal{{ s[0] }}" tabindex="-1">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <form method="post" action="/suppliers/edit/{{ s[0] }}">
                                <div class="modal-header"><h5>Edit Supplier</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                                <div class="modal-body">
                                    <div class="mb-2"><label>Name</label><input type="text" name="name" class="form-control" value="{{ s[1] }}" required></div>
                                    <div class="mb-2"><label>Contact Person</label><input type="text" name="contact_person" class="form-control" value="{{ s[2] }}"></div>
                                    <div class="mb-2"><label>Phone</label><input type="text" name="phone" class="form-control" value="{{ s[3] }}"></div>
                                    <div class="mb-2"><label>Email</label><input type="email" name="email" class="form-control" value="{{ s[4] }}"></div>
                                    <div class="mb-2"><label>Address</label><input type="text" name="address" class="form-control" value="{{ s[5] }}"></div>
                                </div>
                                <div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>
                            </form>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </tbody>
        </table>
        <!-- Add Supplier Modal -->
        <div class="modal fade" id="addSupplierModal" tabindex="-1">
            <div class="modal-dialog"><div class="modal-content"><form method="post" action="/suppliers/add"><div class="modal-header"><h5>Add Supplier</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-2"><label>Name</label><input type="text" name="name" class="form-control" required></div><div class="mb-2"><label>Contact Person</label><input type="text" name="contact_person" class="form-control"></div><div class="mb-2"><label>Phone</label><input type="text" name="phone" class="form-control"></div><div class="mb-2"><label>Email</label><input type="email" name="email" class="form-control"></div><div class="mb-2"><label>Address</label><input type="text" name="address" class="form-control"></div></div><div class="modal-footer"><button type="submit" class="btn btn-primary">Add</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div></form></div></div></div>
        {% endblock %}
    ''', suppliers=rows, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/suppliers/add', methods=['POST'])
@login_required(allowed_roles=['admin'])
def add_supplier():
    name = request.form['name']
    contact_person = request.form.get('contact_person', '')
    phone = request.form.get('phone', '')
    email = request.form.get('email', '')
    address = request.form.get('address', '')
    db.execute_query("INSERT INTO suppliers (name, contact_person, phone, email, address) VALUES (?,?,?,?,?)",
                     (name, contact_person, phone, email, address))
    return redirect(url_for('suppliers'))

@app.route('/suppliers/edit/<int:sid>', methods=['POST'])
@login_required(allowed_roles=['admin'])
def edit_supplier(sid):
    name = request.form['name']
    contact_person = request.form.get('contact_person', '')
    phone = request.form.get('phone', '')
    email = request.form.get('email', '')
    address = request.form.get('address', '')
    db.execute_query("UPDATE suppliers SET name=?, contact_person=?, phone=?, email=?, address=? WHERE id=?",
                     (name, contact_person, phone, email, address, sid))
    return redirect(url_for('suppliers'))

@app.route('/suppliers/delete/<int:sid>')
@login_required(allowed_roles=['admin'])
def delete_supplier(sid):
    db.execute_query("DELETE FROM suppliers WHERE id=?", (sid,))
    return redirect(url_for('suppliers'))

@app.route('/users', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin'])
def users():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password', '')
        if not password:
            return "Password is required", 400
        hashed = hashlib.sha256(password.encode()).hexdigest()
        role = request.form['role']
        full_name = request.form['full_name']
        if not db.fetch_one("SELECT id FROM users WHERE username=?", (username,)):
            db.execute_query("INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
                             (username, hashed, role, full_name))
            db.log_action(session['username'], "INSERT", "users", username, "", f"Added user {username}")
        else:
            return "Username already exists", 400
        return redirect(url_for('users'))
    rows = db.fetch_all("SELECT id, username, role, full_name FROM users")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>User Management</h2>
        <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#addModal">+ Add User</button>
        <table class="table bg-white"><thead><tr><th>ID</th><th>Username</th><th>Role</th><th>Full Name</th><th>Action</th></tr></thead><tbody>{% for u in users %}<tr><td>{{ u[0] }}</td><td>{{ u[1] }}</td><td>{{ u[2] }}</td><td>{{ u[3] }}</td><td><a href="/change_password/{{ u[0] }}" class="btn btn-sm btn-info">Change Password</a></td></tr>{% endfor %}</tbody></tr>
        <div class="modal fade" id="addModal"><div class="modal-dialog"><div class="modal-content"><form method="post"><div class="modal-header"><h5 class="modal-title">Add User</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-2"><label>Username</label><input type="text" name="username" class="form-control" required></div><div class="mb-2"><label>Password</label><input type="password" name="password" class="form-control" required></div><div class="mb-2"><label>Role</label><select name="role" class="form-select"><option>admin</option><option>cashier</option></select></div><div class="mb-2"><label>Full Name</label><input type="text" name="full_name" class="form-control" required></div></div><div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div></form></div></div></div>
        {% endblock %}
    ''', users=rows, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/change_password/<int:user_id>', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin'])
def change_password_admin(user_id):
    if request.method == 'POST':
        new_password = request.form['new_password']
        if not new_password:
            return "Password cannot be empty", 400
        hashed = hashlib.sha256(new_password.encode()).hexdigest()
        db.execute_query("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
        db.log_action(session['username'], "CHANGE_PASSWORD", "users", user_id, "", "Password changed")
        return redirect(url_for('users'))
    user = db.fetch_one("SELECT username FROM users WHERE id = ?", (user_id,))
    if not user:
        return "User not found", 404
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Change Password for {{ user[0] }}</h2>
        <form method="post">
            <div class="mb-3"><label>New Password</label><input type="password" name="new_password" class="form-control" required></div>
            <button type="submit" class="btn btn-primary">Update Password</button>
            <a href="/users" class="btn btn-secondary">Cancel</a>
        </form>
        {% endblock %}
    ''', user=user, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required()
def change_password_self():
    if request.method == 'POST':
        old = request.form['old_password']
        new = request.form['new_password']
        user = db.fetch_one("SELECT password FROM users WHERE id = ?", (session['user_id'],))
        if not user or user[0] != hashlib.sha256(old.encode()).hexdigest():
            return "Old password incorrect", 400
        if not new:
            return "New password cannot be empty", 400
        hashed = hashlib.sha256(new.encode()).hexdigest()
        db.execute_query("UPDATE users SET password = ? WHERE id = ?", (hashed, session['user_id']))
        db.log_action(session['username'], "CHANGE_PASSWORD", "users", session['user_id'], "", "Self password change")
        return redirect(url_for('dashboard'))
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Change Your Password</h2>
        <form method="post">
            <div class="mb-3"><label>Old Password</label><input type="password" name="old_password" class="form-control" required></div>
            <div class="mb-3"><label>New Password</label><input type="password" name="new_password" class="form-control" required></div>
            <button type="submit" class="btn btn-primary">Update Password</button>
            <a href="/dashboard" class="btn btn-secondary">Cancel</a>
        </form>
        {% endblock %}
    ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/stock_alerts')
@login_required()
def stock_alerts():
    low = db.fetch_all("SELECT name, quantity, min_stock FROM products WHERE quantity <= min_stock")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Low Stock Alerts</h2>
        {% if low %}
        <table class="table bg-white"><thead><tr><th>Product</th><th>Current Stock</th><th>Min Stock</th></tr></thead><tbody>{% for l in low %}<tr><td>{{ l[0] }}</td><td>{{ l[1] }}</td><td>{{ l[2] }}</td></tr>{% endfor %}</tbody></table>
        {% else %}<div class="alert alert-success">No low stock items</div>{% endif %}
        {% endblock %}
    ''', low=low, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/returns', methods=['GET', 'POST'])
@login_required()
def returns():
    if request.method == 'POST':
        invoice = request.form['invoice']
        reason = request.form['reason']
        sale = db.fetch_one("SELECT invoice_no, net_amount FROM sales WHERE invoice_no=?", (invoice,))
        if sale:
            refund = sale[1] * 0.95
            ret_inv = f"RET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            db.execute_query(
                "INSERT INTO returns (original_invoice, return_invoice, refund_amount, reason, cashier) VALUES (?,?,?,?,?)",
                (invoice, ret_inv, refund, reason, session['username']))
            items = db.fetch_all("SELECT product_id, quantity FROM sale_items WHERE invoice_no=?", (invoice,))
            for it in items:
                db.execute_query("UPDATE products SET quantity = quantity + ? WHERE id=?", (it[1], it[0]))
            return render_template_string('''
                {% extends "base.html" %}
                {% block content %}
                <h2>Returns Management</h2>
                <div class="alert alert-success">Return processed, refund: {{ currency }} {{ refund }}</div>
                <a href="/returns" class="btn btn-secondary">Back</a>
                {% endblock %}
            ''', refund=refund, currency=config_manager.config['currency'],
                                          company=config_manager.config['company_name'], session=session,
                                          year=datetime.now().year)
        else:
            return render_template_string('''
                {% extends "base.html" %}
                {% block content %}
                <h2>Returns Management</h2>
                <div class="alert alert-danger">Invoice not found</div>
                <form method="post"><div class="mb-3"><label>Invoice Number</label><input type="text" name="invoice" class="form-control" required></div><div class="mb-3"><label>Reason</label><select name="reason" class="form-select"><option>Damaged</option><option>Wrong item</option><option>Expired</option><option>Other</option></select></div><button type="submit" class="btn btn-warning">Process Return</button></form>
                {% endblock %}
            ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Returns Management</h2>
        <form method="post"><div class="mb-3"><label>Invoice Number</label><input type="text" name="invoice" class="form-control" required></div><div class="mb-3"><label>Reason</label><select name="reason" class="form-select"><option>Damaged</option><option>Wrong item</option><option>Expired</option><option>Other</option></select></div><button type="submit" class="btn btn-warning">Process Return</button></form>
        {% endblock %}
    ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/loyalty')
@login_required()
def loyalty():
    rows = db.fetch_all("SELECT customer_name, customer_phone, points, tier, total_spent FROM loyalty ORDER BY points DESC")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Loyalty Program</h2>
        {% if session.role == 'admin' %}
        <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#addModal">+ Register Customer</button>
        <div class="modal fade" id="addModal"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/loyalty/add"><div class="modal-header"><h5 class="modal-title">Register Customer</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-2"><label>Name</label><input type="text" name="name" class="form-control" required></div><div class="mb-2"><label>Phone</label><input type="text" name="phone" class="form-control" required></div></div><div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div></form></div></div></div>
        {% endif %}
        <table class="table bg-white"><thead><tr><th>Customer</th><th>Phone</th><th>Points</th><th>Tier</th><th>Total Spent ({{ currency }})</th></tr></thead><tbody>{% for l in rows %}<tr><td>{{ l[0] }}</td><td>{{ l[1] }}</td><td>{{ l[2] }}</td><td>{{ l[3] }}</td><td>{{ l[4] }}</td></tr>{% endfor %}</tbody></table>
        {% endblock %}
    ''', rows=rows, currency=config_manager.config['currency'], company=config_manager.config['company_name'],
                                  session=session, year=datetime.now().year)

@app.route('/loyalty/add', methods=['POST'])
@login_required(allowed_roles=['admin'])
def add_loyalty():
    name = request.form['name']
    phone = request.form['phone']
    db.execute_query("INSERT OR REPLACE INTO loyalty (customer_name, customer_phone) VALUES (?,?)", (name, phone))
    return redirect(url_for('loyalty'))

@app.route('/expenses', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin'])
def expenses():
    if request.method == 'POST':
        category = request.form['category']
        try:
            amount = float(request.form['amount'])
            if amount < 0:
                return "Amount cannot be negative", 400
        except ValueError:
            return "Invalid amount", 400
        description = request.form['description']
        db.execute_query("INSERT INTO expenses (category, amount, description, expense_date, user) VALUES (?,?,?,?,?)",
                         (category, amount, description, datetime.now().date(), session['username']))
        return redirect(url_for('expenses'))
    rows = db.fetch_all("SELECT expense_date, category, amount, description, user FROM expenses ORDER BY expense_date DESC")
    total = sum(r[2] for r in rows)
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Expense Tracking</h2>
        <form method="post" class="row g-3 mb-4"><div class="col-auto"><input type="text" name="category" placeholder="Category" class="form-control" required></div><div class="col-auto"><input type="number" step="0.01" name="amount" placeholder="Amount" class="form-control" required min="0"></div><div class="col-auto"><input type="text" name="description" placeholder="Description" class="form-control"></div><div class="col-auto"><button type="submit" class="btn btn-primary">Add Expense</button></div></form>
        <table class="table bg-white"><thead><tr><th>Date</th><th>Category</th><th>Amount ({{ currency }})</th><th>Description</th><th>User</th></tr></thead><tbody>{% for e in expenses %}<td><td>{{ e[0] }}</td><td>{{ e[1] }}</td><td>{{ e[2] }}</td><td>{{ e[3] }}</td><td>{{ e[4] }}</td></tr>{% endfor %}</tbody></table>
        <h4>Total: {{ currency }} {{ total }}</h4>
        {% endblock %}
    ''', expenses=rows, total=total, currency=config_manager.config['currency'],
                                  company=config_manager.config['company_name'], session=session,
                                  year=datetime.now().year)

@app.route('/backup')
@login_required(allowed_roles=['admin'])
def backup():
    try:
        os.makedirs("backups", exist_ok=True)
        fn = f"backups/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2("supermarket.db", fn)
        return f"Backup saved to {fn}"
    except Exception as e:
        return f"Backup failed: {str(e)}"

@app.route('/settings', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin'])
def settings():
    if request.method == 'POST':
        config_manager.config['receipt_header'] = request.form['receipt_header']
        config_manager.config['receipt_footer'] = request.form['receipt_footer']
        config_manager.config['company_name'] = request.form['company_name']
        config_manager.config['currency'] = request.form['currency']
        # ADDED: Invoice settings
        config_manager.config['invoice_terms'] = request.form.get('invoice_terms', config_manager.DEFAULT_CONFIG['invoice_terms'])
        config_manager.config['quotation_valid_days'] = int(request.form.get('quotation_valid_days', 7))
        config_manager.save_config()
        return redirect(url_for('settings'))
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>System Settings</h2>
        <form method="post">
            <div class="mb-3"><label>Company Name</label><input type="text" name="company_name" class="form-control" value="{{ config.company_name }}"></div>
            <div class="mb-3"><label>Currency Symbol</label><input type="text" name="currency" class="form-control" value="{{ config.currency }}"></div>
            <div class="mb-3"><label>Receipt Header</label><textarea name="receipt_header" class="form-control" rows="3">{{ config.receipt_header }}</textarea></div>
            <div class="mb-3"><label>Receipt Footer</label><textarea name="receipt_footer" class="form-control" rows="3">{{ config.receipt_footer }}</textarea></div>
            <div class="mb-3"><label>Invoice Terms & Conditions</label><textarea name="invoice_terms" class="form-control" rows="2">{{ config.invoice_terms }}</textarea></div>
            <div class="mb-3"><label>Quotation Validity (days)</label><input type="number" name="quotation_valid_days" class="form-control" value="{{ config.quotation_valid_days }}" min="1"></div>
            <button type="submit" class="btn btn-primary">Save Settings</button>
        </form>
        {% endblock %}
    ''', config=config_manager.config, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/charts')
@login_required()
def charts():
    return render_template_string('''
        {% extends "base.html" %}
        {% block extra_head %}
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        {% endblock %}
        {% block content %}
        <h2>Sales Analytics</h2>
        <canvas id="salesChart" width="800" height="400"></canvas>
        <canvas id="categoryChart" width="800" height="400"></canvas>
        <script>
            fetch('/api/sales_trend')
                .then(res => res.json())
                .then(data => {
                    new Chart(document.getElementById('salesChart'), {
                        type: 'line',
                        data: { labels: data.dates, datasets: [{ label: 'Revenue ({{ currency }})', data: data.amounts, borderColor: '#2e7d32', fill: false }] },
                        options: { responsive: true, maintainAspectRatio: false }
                    });
                });
            fetch('/api/category_sales')
                .then(res => res.json())
                .then(data => {
                    new Chart(document.getElementById('categoryChart'), {
                        type: 'pie',
                        data: { labels: data.categories, datasets: [{ data: data.sales, backgroundColor: ['#2e7d32','#43a047','#66bb6a','#81c784','#a5d6a7'] }] }
                    });
                });
        </script>
        {% endblock %}
    ''', company=config_manager.config['company_name'], currency=config_manager.config['currency'], session=session, year=datetime.now().year)

@app.route('/api/sales_trend')
@login_required()
def api_sales_trend():
    data = db.fetch_all(
        "SELECT DATE(sale_date), SUM(net_amount) FROM sales WHERE sale_date >= date('now', '-30 days') GROUP BY DATE(sale_date) ORDER BY sale_date")
    dates = [d[0] for d in data]
    amounts = [d[1] for d in data]
    return jsonify({'dates': dates, 'amounts': amounts})

@app.route('/api/category_sales')
@login_required()
def api_category_sales():
    cat_data = db.fetch_all(
        "SELECT p.category, SUM(si.total) FROM sale_items si JOIN products p ON si.product_id=p.id GROUP BY p.category ORDER BY SUM(si.total) DESC LIMIT 5")
    categories = [c[0] for c in cat_data]
    sales_by_cat = [c[1] for c in cat_data]
    return jsonify({'categories': categories, 'sales': sales_by_cat})

# ==================== ADDED: INVOICE PANEL MODULE ====================
@app.route('/invoice_panel')
@login_required()
def invoice_panel():
    """Main invoice panel dashboard with links to sub-modules"""
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Invoice Panel</h2>
        <div class="row">
            <div class="col-md-4 mb-3"><a href="/quotation" class="btn btn-primary w-100 py-3">📄 Quotations</a></div>
            <div class="col-md-4 mb-3"><a href="/receipts" class="btn btn-success w-100 py-3">🧾 Receipts</a></div>
            <div class="col-md-4 mb-3"><a href="/invoice_records" class="btn btn-secondary w-100 py-3">📑 Invoice Records</a></div>
            <div class="col-md-4 mb-3"><a href="/invoice_settings" class="btn btn-info w-100 py-3">⚙️ Invoice Settings</a></div>
            <div class="col-md-4 mb-3"><a href="/delivery" class="btn btn-warning w-100 py-3">🚚 Delivery Management</a></div>
            <div class="col-md-4 mb-3"><a href="/expenses" class="btn btn-danger w-100 py-3">💰 Expenses</a></div>
        </div>
        {% endblock %}
    ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)

# -------------------- Quotations --------------------
@app.route('/quotation', methods=['GET', 'POST'])
@login_required()
def quotation():
    if request.method == 'POST':
        # Create a new quotation
        data = request.form
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')
        items_json = data.get('items_json', '[]')
        subtotal = float(data.get('subtotal', 0))
        tax = float(data.get('tax', 0))
        total = float(data.get('total', 0))
        quote_no = generate_quote_no()
        expiry_date = (datetime.now() + timedelta(days=config_manager.config['quotation_valid_days'])).date()
        db.execute_query(
            "INSERT INTO quotations (quote_no, customer_name, customer_phone, quote_date, expiry_date, items_json, subtotal, tax, total, status, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, customer_name, customer_phone, datetime.now().date(), expiry_date, items_json, subtotal, tax, total, 'draft', session['username']))
        return redirect(url_for('quotation'))
    quotes = db.fetch_all("SELECT id, quote_no, customer_name, quote_date, expiry_date, total, status FROM quotations ORDER BY id DESC")
    # Fetch products for the quote builder modal
    products = db.fetch_all("SELECT id, name, selling_price FROM products")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Quotations</h2>
        <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#quoteModal">+ New Quotation</button>
        <table class="table bg-white">
            <thead><tr><th>Quote No</th><th>Customer</th><th>Date</th><th>Expiry</th><th>Total ({{ currency }})</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
                {% for q in quotes %}
                <tr>
                    <td>{{ q[1] }}</td><td>{{ q[2] }}</td><td>{{ q[3] }}</td><td>{{ q[4] }}</td><td>{{ q[5] }}</td><td>{{ q[6] }}</td>
                    <td>
                        <a href="/quotation/view/{{ q[0] }}" class="btn btn-sm btn-info">View</a>
                        <a href="/quotation/convert/{{ q[0] }}" class="btn btn-sm btn-primary">Convert to Sale</a>
                        <a href="/quotation/delete/{{ q[0] }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <!-- Modal for creating quotation -->
        <div class="modal fade" id="quoteModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header"><h5>Create Quotation</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                    <div class="modal-body">
                        <div class="mb-2"><label>Customer Name</label><input type="text" id="quote_customer" class="form-control"></div>
                        <div class="mb-2"><label>Customer Phone</label><input type="text" id="quote_phone" class="form-control"></div>
                        <h6>Products</h6>
                        <div class="row">
                            <div class="col-md-8"><input type="text" id="searchProduct" class="form-control" placeholder="Search product"></div>
                            <div class="col-md-4"><select id="productSelect" class="form-select"><option>Select Product</option>{% for p in products %}<option value="{{ p[0] }}" data-price="{{ p[2] }}" data-name="{{ p[1] }}">{{ p[1] }} - {{ currency }} {{ p[2] }}</option>{% endfor %}</select></div>
                        </div>
                        <button class="btn btn-secondary btn-sm mt-2" id="addProductBtn">Add Selected Product</button>
                        <table class="table table-sm mt-3" id="quoteItemsTable">
                            <thead><tr><th>Product</th><th>Price</th><th>Qty</th><th>Total</th><th></th></tr></thead>
                            <tbody></tbody>
                        </table>
                        <hr>
                        <div class="text-end">Subtotal: <span id="quoteSubtotal">0.00</span><br>Tax (16%): <span id="quoteTax">0.00</span><br><strong>Total: <span id="quoteTotal">0.00</span></strong></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-primary" id="saveQuoteBtn">Save Quotation</button>
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    </div>
                </div>
            </div>
        </div>
        <script>
            let quoteItems = [];
            function updateQuoteSummary() {
                let subtotal = quoteItems.reduce((s,i)=> s + i.price*i.qty, 0);
                let tax = subtotal * 0.16;
                let total = subtotal + tax;
                document.getElementById('quoteSubtotal').innerText = subtotal.toFixed(2);
                document.getElementById('quoteTax').innerText = tax.toFixed(2);
                document.getElementById('quoteTotal').innerText = total.toFixed(2);
                let tbody = document.querySelector('#quoteItemsTable tbody');
                tbody.innerHTML = '';
                quoteItems.forEach((item, idx) => {
                    let row = tbody.insertRow();
                    row.insertCell(0).innerText = item.name;
                    row.insertCell(1).innerText = '{{ currency }} ' + item.price.toFixed(2);
                    row.insertCell(2).innerHTML = `<input type="number" value="${item.qty}" min="1" class="form-control form-control-sm" style="width:80px" data-idx="${idx}">`;
                    row.insertCell(3).innerText = (item.price * item.qty).toFixed(2);
                    let delCell = row.insertCell(4);
                    let delBtn = document.createElement('button');
                    delBtn.innerText = 'X';
                    delBtn.className = 'btn btn-sm btn-danger';
                    delBtn.onclick = () => { quoteItems.splice(idx,1); updateQuoteSummary(); };
                    delCell.appendChild(delBtn);
                });
                document.querySelectorAll('#quoteItemsTable tbody input').forEach(inp => {
                    inp.addEventListener('change', (e) => {
                        let idx = parseInt(e.target.dataset.idx);
                        quoteItems[idx].qty = parseInt(e.target.value);
                        updateQuoteSummary();
                    });
                });
            }
            document.getElementById('addProductBtn').addEventListener('click', () => {
                let select = document.getElementById('productSelect');
                let option = select.options[select.selectedIndex];
                if(option.value && option.value !== 'Select Product') {
                    let id = option.value;
                    let name = option.dataset.name;
                    let price = parseFloat(option.dataset.price);
                    let existing = quoteItems.find(i => i.id == id);
                    if(existing) existing.qty += 1;
                    else quoteItems.push({id: id, name: name, price: price, qty: 1});
                    updateQuoteSummary();
                }
            });
            document.getElementById('saveQuoteBtn').addEventListener('click', () => {
                if(quoteItems.length === 0) { alert('Add at least one product'); return; }
                let subtotal = quoteItems.reduce((s,i)=> s + i.price*i.qty, 0);
                let tax = subtotal * 0.16;
                let total = subtotal + tax;
                let form = document.createElement('form');
                form.method = 'POST';
                form.action = '/quotation';
                let csrf = document.createElement('input');
                csrf.type = 'hidden';
                csrf.name = 'customer_name';
                csrf.value = document.getElementById('quote_customer').value;
                form.appendChild(csrf);
                let phone = document.createElement('input');
                phone.type = 'hidden';
                phone.name = 'customer_phone';
                phone.value = document.getElementById('quote_phone').value;
                form.appendChild(phone);
                let itemsField = document.createElement('input');
                itemsField.type = 'hidden';
                itemsField.name = 'items_json';
                itemsField.value = JSON.stringify(quoteItems);
                form.appendChild(itemsField);
                let sub = document.createElement('input');
                sub.type = 'hidden'; sub.name = 'subtotal'; sub.value = subtotal;
                form.appendChild(sub);
                let tx = document.createElement('input');
                tx.type = 'hidden'; tx.name = 'tax'; tx.value = tax;
                form.appendChild(tx);
                let tot = document.createElement('input');
                tot.type = 'hidden'; tot.name = 'total'; tot.value = total;
                form.appendChild(tot);
                document.body.appendChild(form);
                form.submit();
            });
            document.getElementById('searchProduct').addEventListener('keyup', function() {
                let term = this.value.toLowerCase();
                let options = document.getElementById('productSelect').options;
                for(let i=0; i<options.length; i++) {
                    let txt = options[i].text.toLowerCase();
                    if(txt.includes(term)) options[i].style.display = '';
                    else options[i].style.display = 'none';
                }
            });
        </script>
        {% endblock %}
    ''', quotes=quotes, products=products, currency=config_manager.config['currency'], company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/quotation/view/<int:qid>')
@login_required()
def view_quotation(qid):
    quote = db.fetch_one("SELECT * FROM quotations WHERE id=?", (qid,))
    if not quote:
        return "Quotation not found", 404
    items = json.loads(quote[6])  # items_json column
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Quotation Details</h2>
        <div class="card"><div class="card-body">
            <p><strong>Quote No:</strong> {{ quote[1] }}</p>
            <p><strong>Customer:</strong> {{ quote[2] }} ({{ quote[3] }})</p>
            <p><strong>Date:</strong> {{ quote[4] }} | <strong>Expiry:</strong> {{ quote[5] }}</p>
            <p><strong>Status:</strong> {{ quote[10] }}</p>
            <table class="table"><thead><tr><th>Product</th><th>Price</th><th>Qty</th><th>Total</th></tr></thead><tbody>
                {% for item in items %}
                <tr><td>{{ item.name }}</td><td>{{ currency }} {{ item.price }}</td><td>{{ item.qty }}</td><td>{{ currency }} {{ item.price * item.qty }}</td></tr>
                {% endfor %}
            </tbody></table>
            <h5>Subtotal: {{ currency }} {{ quote[7] }} | Tax: {{ currency }} {{ quote[8] }} | Total: {{ currency }} {{ quote[9] }}</h5>
            <a href="/quotation/convert/{{ quote[0] }}" class="btn btn-primary">Convert to Sale</a>
            <a href="/quotation" class="btn btn-secondary">Back</a>
        </div></div>
        {% endblock %}
    ''', quote=quote, items=items, currency=config_manager.config['currency'], company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/quotation/convert/<int:qid>')
@login_required()
def convert_quote_to_sale(qid):
    quote = db.fetch_one("SELECT * FROM quotations WHERE id=?", (qid,))
    if not quote:
        return "Quotation not found", 404
    items = json.loads(quote[6])
    # Create sale from quotation
    customer_name = quote[2]
    customer_phone = quote[3]
    subtotal = quote[7]
    tax = quote[8]
    net_total = quote[9]
    invoice_no = generate_invoice_no()
    try:
        db.execute_query(
            "INSERT INTO sales (invoice_no, customer_name, customer_phone, total_amount, discount, tax, net_amount, payment_method, cashier) VALUES (?,?,?,?,?,?,?,?,?)",
            (invoice_no, customer_name, customer_phone, subtotal, 0, tax, net_total, 'Quote Conversion', session['username']))
        for item in items:
            prod = db.fetch_one("SELECT id, selling_price, quantity FROM products WHERE name=?", (item['name'],))
            if not prod:
                continue
            db.execute_query(
                "INSERT INTO sale_items (invoice_no, product_id, product_name, quantity, unit_price, total) VALUES (?,?,?,?,?,?)",
                (invoice_no, prod[0], item['name'], item['qty'], item['price'], item['price']*item['qty']))
            db.execute_query("UPDATE products SET quantity = quantity - ? WHERE id=?", (item['qty'], prod[0]))
        # Update quotation status
        db.execute_query("UPDATE quotations SET status='converted' WHERE id=?", (qid,))
        return render_template_string('''
            {% extends "base.html" %}
            {% block content %}
            <div class="alert alert-success">Quotation converted to sale. Invoice: {{ invoice_no }}</div>
            <a href="/invoice_records" class="btn btn-primary">View Records</a>
            {% endblock %}
        ''', invoice_no=invoice_no, company=config_manager.config['company_name'], session=session, year=datetime.now().year)
    except Exception as e:
        return f"Error converting: {str(e)}", 500

@app.route('/quotation/delete/<int:qid>')
@login_required(allowed_roles=['admin'])
def delete_quotation(qid):
    db.execute_query("DELETE FROM quotations WHERE id=?", (qid,))
    return redirect(url_for('quotation'))

# -------------------- Receipts --------------------
@app.route('/receipts', methods=['GET', 'POST'])
@login_required()
def receipts():
    if request.method == 'POST':
        invoice_no = request.form['invoice_no']
        sale = db.fetch_one("SELECT * FROM sales WHERE invoice_no=?", (invoice_no,))
        if sale:
            items = db.fetch_all("SELECT product_name, quantity, unit_price, total FROM sale_items WHERE invoice_no=?", (invoice_no,))
            return render_template_string('''
                {% extends "base.html" %}
                {% block content %}
                <h2>Receipt</h2>
                <div class="card"><div class="card-body">
                    <pre>{{ config_manager.config['receipt_header'] }}
Invoice: {{ sale[1] }}
Customer: {{ sale[2] }} ({{ sale[3] }})
Date: {{ sale[13] }}
Cashier: {{ sale[11] }}
--------------------------------
{% for item in items %}{{ item[0] }} x{{ item[1] }} @ {{ currency }} {{ item[2] }} = {{ currency }} {{ item[3] }}
{% endfor %}
--------------------------------
Subtotal: {{ currency }} {{ sale[4] }}
Discount: {{ currency }} {{ sale[5] }}
Tax: {{ currency }} {{ sale[6] }}
Total: {{ currency }} {{ sale[7] }}
Payment: {{ sale[8] }}
{{ config_manager.config['receipt_footer'] }}
                    </pre>
                    <button onclick="window.print()" class="btn btn-primary">Print Receipt</button>
                    <a href="/receipts" class="btn btn-secondary">Back</a>
                </div></div>
                {% endblock %}
            ''', sale=sale, items=items, currency=config_manager.config['currency'], config_manager=config_manager)
        else:
            return render_template_string('''
                {% extends "base.html" %}
                {% block content %}
                <div class="alert alert-danger">Invoice not found</div>
                <a href="/receipts" class="btn btn-secondary">Back</a>
                {% endblock %}
            ''')
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Receipt Reprint</h2>
        <form method="post">
            <div class="mb-3"><label>Invoice Number</label><input type="text" name="invoice_no" class="form-control" required></div>
            <button type="submit" class="btn btn-primary">Get Receipt</button>
        </form>
        {% endblock %}
    ''', company=config_manager.config['company_name'], session=session, year=datetime.now().year)

# -------------------- Invoice Records --------------------
@app.route('/invoice_records')
@login_required()
def invoice_records():
    search = request.args.get('search', '')
    if search:
        records = db.fetch_all("SELECT invoice_no, customer_name, net_amount, payment_method, sale_date FROM sales WHERE invoice_no LIKE ? OR customer_name LIKE ? ORDER BY sale_date DESC", (f'%{search}%', f'%{search}%'))
    else:
        records = db.fetch_all("SELECT invoice_no, customer_name, net_amount, payment_method, sale_date FROM sales ORDER BY sale_date DESC LIMIT 100")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Invoice Records</h2>
        <form method="get" class="mb-3">
            <div class="input-group"><input type="text" name="search" class="form-control" placeholder="Search by invoice or customer" value="{{ search }}"><button type="submit" class="btn btn-primary">Search</button></div>
        </form>
        <table class="table bg-white">
            <thead><tr><th>Invoice No</th><th>Customer</th><th>Total ({{ currency }})</th><th>Payment</th><th>Date</th><th>Action</th></tr></thead>
            <tbody>
                {% for r in records %}
                <tr>
                    <td>{{ r[0] }}</td><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td>
                    <td><a href="/receipts?invoice_no={{ r[0] }}" class="btn btn-sm btn-info">View Receipt</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endblock %}
    ''', records=records, search=search, currency=config_manager.config['currency'], company=config_manager.config['company_name'], session=session, year=datetime.now().year)

# -------------------- Invoice Settings (handled in general settings, but dedicated page) --------------------
@app.route('/invoice_settings', methods=['GET', 'POST'])
@login_required(allowed_roles=['admin'])
def invoice_settings():
    if request.method == 'POST':
        config_manager.config['invoice_terms'] = request.form['invoice_terms']
        config_manager.config['quotation_valid_days'] = int(request.form['quotation_valid_days'])
        config_manager.save_config()
        return redirect(url_for('invoice_settings'))
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Invoice Specific Settings</h2>
        <form method="post">
            <div class="mb-3"><label>Invoice Terms & Conditions</label><textarea name="invoice_terms" class="form-control" rows="4">{{ config.invoice_terms }}</textarea></div>
            <div class="mb-3"><label>Quotation Validity (days)</label><input type="number" name="quotation_valid_days" class="form-control" value="{{ config.quotation_valid_days }}" min="1"></div>
            <button type="submit" class="btn btn-primary">Save Settings</button>
            <a href="/settings" class="btn btn-secondary">General Settings</a>
        </form>
        {% endblock %}
    ''', config=config_manager.config, company=config_manager.config['company_name'], session=session, year=datetime.now().year)

# -------------------- Delivery Management --------------------
@app.route('/delivery', methods=['GET', 'POST'])
@login_required()
def delivery():
    if request.method == 'POST':
        invoice_no = request.form['invoice_no']
        address = request.form['address']
        driver = request.form.get('driver', '')
        tracking = request.form.get('tracking', '')
        delivery_date = request.form.get('delivery_date', datetime.now().date())
        # Check if delivery already exists
        existing = db.fetch_one("SELECT id FROM deliveries WHERE invoice_no=?", (invoice_no,))
        if existing:
            db.execute_query("UPDATE deliveries SET delivery_address=?, delivery_date=?, driver_name=?, tracking_info=?, status='pending' WHERE invoice_no=?", (address, delivery_date, driver, tracking, invoice_no))
        else:
            db.execute_query("INSERT INTO deliveries (invoice_no, delivery_address, delivery_date, driver_name, tracking_info, status) VALUES (?,?,?,?,?,?)", (invoice_no, address, delivery_date, driver, tracking, 'pending'))
        return redirect(url_for('delivery'))
    deliveries = db.fetch_all("SELECT d.id, d.invoice_no, d.delivery_address, d.delivery_date, d.status, d.driver_name, d.tracking_info, s.customer_name FROM deliveries d LEFT JOIN sales s ON d.invoice_no=s.invoice_no ORDER BY d.delivery_date DESC")
    return render_template_string('''
        {% extends "base.html" %}
        {% block content %}
        <h2>Delivery Management</h2>
        <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#addDeliveryModal">+ Create Delivery</button>
        <table class="table bg-white">
            <thead><tr><th>Invoice No</th><th>Customer</th><th>Address</th><th>Delivery Date</th><th>Driver</th><th>Tracking</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
                {% for d in deliveries %}
                <tr>
                    <td>{{ d[1] }}</td><td>{{ d[7] }}</td><td>{{ d[2] }}</td><td>{{ d[3] }}</td><td>{{ d[5] }}</td><td>{{ d[6] }}</td><td>{{ d[4] }}</td>
                    <td>
                        <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#updateDeliveryModal{{ d[0] }}">Update</button>
                        <a href="/delivery/delete/{{ d[0] }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>
                    </td>
                </tr>
                <!-- Update Modal -->
                <div class="modal fade" id="updateDeliveryModal{{ d[0] }}" tabindex="-1">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <form method="post" action="/delivery/update/{{ d[0] }}">
                                <div class="modal-header"><h5>Update Delivery</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                                <div class="modal-body">
                                    <div class="mb-2"><label>Address</label><input type="text" name="address" class="form-control" value="{{ d[2] }}" required></div>
                                    <div class="mb-2"><label>Delivery Date</label><input type="date" name="delivery_date" class="form-control" value="{{ d[3] }}"></div>
                                    <div class="mb-2"><label>Driver Name</label><input type="text" name="driver" class="form-control" value="{{ d[5] }}"></div>
                                    <div class="mb-2"><label>Tracking Info</label><input type="text" name="tracking" class="form-control" value="{{ d[6] }}"></div>
                                    <div class="mb-2"><label>Status</label><select name="status" class="form-select"><option>pending</option><option>shipped</option><option>delivered</option><option>cancelled</option></select></div>
                                </div>
                                <div class="modal-footer"><button type="submit" class="btn btn-primary">Save</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>
                            </form>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </tbody>
        </table>
        <!-- Add Delivery Modal -->
        <div class="modal fade" id="addDeliveryModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <form method="post">
                        <div class="modal-header"><h5>Assign Delivery to Invoice</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                        <div class="modal-body">
                            <div class="mb-2"><label>Invoice Number</label><input type="text" name="invoice_no" class="form-control" required></div>
                            <div class="mb-2"><label>Delivery Address</label><textarea name="address" class="form-control" required></textarea></div>
                            <div class="mb-2"><label>Delivery Date</label><input type="date" name="delivery_date" class="form-control" value="{{ today }}"></div>
                            <div class="mb-2"><label>Driver Name (optional)</label><input type="text" name="driver" class="form-control"></div>
                            <div class="mb-2"><label>Tracking Info (optional)</label><input type="text" name="tracking" class="form-control"></div>
                        </div>
                        <div class="modal-footer"><button type="submit" class="btn btn-primary">Create</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>
                    </form>
                </div>
            </div>
        </div>
        {% endblock %}
    ''', deliveries=deliveries, today=datetime.now().date().isoformat(), company=config_manager.config['company_name'], session=session, year=datetime.now().year)

@app.route('/delivery/update/<int:did>', methods=['POST'])
@login_required(allowed_roles=['admin'])
def update_delivery(did):
    address = request.form['address']
    delivery_date = request.form['delivery_date']
    driver = request.form.get('driver', '')
    tracking = request.form.get('tracking', '')
    status = request.form.get('status', 'pending')
    db.execute_query("UPDATE deliveries SET delivery_address=?, delivery_date=?, driver_name=?, tracking_info=?, status=? WHERE id=?", (address, delivery_date, driver, tracking, status, did))
    return redirect(url_for('delivery'))

@app.route('/delivery/delete/<int:did>')
@login_required(allowed_roles=['admin'])
def delete_delivery(did):
    db.execute_query("DELETE FROM deliveries WHERE id=?", (did,))
    return redirect(url_for('delivery'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
