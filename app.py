import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime

# --- 1. CONFIGURATION ---
PRICING_CONFIG = {
    "1 Portion": {"qty": 1, "price": 29000},
    "2 Portions": {"qty": 2, "price": 28000},
    "5 Portions": {"qty": 5, "price": 27000},
    "10 Portions": {"qty": 10, "price": 26000},
    "20 Portions": {"qty": 20, "price": 25000},
    "40 Portions": {"qty": 40, "price": 24000},
    "80 Portions": {"qty": 80, "price": 23000},
}
APP_VERSION = "v1.5.4 (UI Refinement)"

# --- 2. DATABASE CONNECTION & INIT ---
# Assumes [connections.supabase] is set in .streamlit/secrets.toml
conn = st.connection("supabase", type="sql")

@st.cache_resource
def init_db():
    with conn.session as session:
        # Create customers table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                quota_balance INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # Create transactions table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                change_amount INTEGER,
                payment_amount INTEGER,
                note TEXT,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                meal_type TEXT
            );
        """))
        
        # Migration: Add meal_type column if it doesn't exist
        try:
            session.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS meal_type TEXT;"))
        except Exception:
            pass # Ignore if error

        # Indexing for Performance
        session.execute(text("CREATE INDEX IF NOT EXISTS idx_transactions_customer_id ON transactions(customer_id);"))
        session.execute(text("CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);"))
        
        session.commit()

# Run init_db once on script load (or handle via a separate setup script if preferred, 
# but running here ensures tables exist for the demo)
try:
    init_db()
except Exception as e:
    st.error(f"Database initialization failed: {e}")

# --- 3. HELPER FUNCTIONS ---
@st.cache_data
def get_all_customers():
    return conn.query("SELECT * FROM customers ORDER BY name ASC", ttl=0)

@st.cache_data
def get_paginated_transactions(limit, offset):
    query = """
    SELECT 
        t.id, t.timestamp, c.name, t.change_amount, t.payment_amount, t.note, t.meal_type 
    FROM transactions t
    JOIN customers c ON t.customer_id = c.id
    ORDER BY t.timestamp DESC 
    LIMIT :limit OFFSET :offset
    """
    # Use ttl=0 to disable connection-level cache, relying on st.cache_data
    return conn.query(query, params={"limit": limit, "offset": offset}, ttl=0)

@st.cache_data
def get_total_transaction_count():
    query = "SELECT COUNT(*) FROM transactions"
    result = conn.query(query, ttl=0)
    return int(result.iloc[0, 0]) if not result.empty else 0

def update_quota(customer_id, change_amount, payment_amount, note, timestamp=None, meal_type=None):
    if timestamp is None:
        timestamp = datetime.now()
        
    with conn.session as session:
        # Insert transaction
        session.execute(
            text("""
                INSERT INTO transactions (customer_id, change_amount, payment_amount, note, timestamp, meal_type)
                VALUES (:cid, :change, :pay, :note, :ts, :meal)
            """),
            {"cid": customer_id, "change": change_amount, "pay": payment_amount, "note": note, "ts": timestamp, "meal": meal_type}
        )
        # Update customer balance
        session.execute(
            text("""
                UPDATE customers 
                SET quota_balance = quota_balance + :change
                WHERE id = :cid
            """),
            {"cid": customer_id, "change": change_amount}
        )
        session.commit()
    st.cache_data.clear()

def add_customer(name, phone):
    with conn.session as session:
        session.execute(
            text("INSERT INTO customers (name, phone) VALUES (:name, :phone)"),
            {"name": name, "phone": phone}
        )
        session.commit()
    st.cache_data.clear()

def update_customer(customer_id, new_name, new_phone):
    with conn.session as session:
        session.execute(
            text("UPDATE customers SET name = :name, phone = :phone WHERE id = :cid"),
            {"name": new_name, "phone": new_phone, "cid": customer_id}
        )
        session.commit()
    st.cache_data.clear()

def delete_customer(customer_id):
    with conn.session as session:
        # Cascade delete (or assume foreign key cascade, but let's be explicit to be safe)
        session.execute(text("DELETE FROM transactions WHERE customer_id = :cid"), {"cid": customer_id})
        session.execute(text("DELETE FROM customers WHERE id = :cid"), {"cid": customer_id})
        session.commit()
    st.cache_data.clear()

# --- DIALOGS (Modal Popups) ---
@st.dialog("Edit Transaction")
def edit_dialog(tx_row):
    st.write(f"Editing Transaction ID: {tx_row['id']}")
    new_change = st.number_input("Change Amount (+/-)", value=int(tx_row['change_amount']))
    
    # Auto-calculate Payment based on Unit Price if it's a Top Up
    new_pay = 0
    if new_change > 0:
        # Calculate initial unit price safely
        old_qty = int(tx_row['change_amount'])
        old_pay = int(tx_row['payment_amount'])
        initial_unit_price = int(old_pay / old_qty) if old_qty > 0 else 0
        
        unit_price = st.number_input("Unit Price (IDR)", value=initial_unit_price, step=500)
        new_pay = int(new_change * unit_price)
        st.info(f"**Total Payment:** {new_pay:,.0f} IDR (Auto-calculated)")
    else:
        # For redemptions (negative change), usually payment is 0, but allow manual edit if needed
        new_pay = st.number_input("Payment Amount", value=int(tx_row['payment_amount']))
        
    new_note = st.text_input("Note", value=tx_row['note'])
    
    # Date Edit
    current_ts = tx_row['timestamp']
    if pd.isna(current_ts):
        current_ts = datetime.now()
    elif not isinstance(current_ts, datetime): # Ensure it's a datetime object
        current_ts = pd.to_datetime(current_ts)
        
    new_date = st.date_input("Date", value=current_ts.date())
    new_time = st.time_input("Time", value=current_ts.time())
    
    # Meal Type Edit: Only show if it is a Redemption (negative change)
    new_meal = None
    if new_change < 0:
        current_meal = tx_row['meal_type'] if pd.notnull(tx_row['meal_type']) else "Lunch"
        new_meal = st.radio("Meal Type", ["Lunch", "Dinner"], index=0 if current_meal == "Lunch" else 1, horizontal=True)
    else:
        # If it's a top up, ensure meal_type is None
        new_meal = None

    if st.button("Update"):
        # Combine Date and Time
        new_timestamp = datetime.combine(new_date, new_time)
        
        # Fetch customer ID safely
        cust_id_lookup = get_all_customers()
        cust_row = cust_id_lookup[cust_id_lookup['name'] == tx_row['name']]
        
        if not cust_row.empty:
            cid = int(cust_row.iloc[0]['id'])
            # Helper function call
            edit_transaction(
                int(tx_row['id']),
                cid,
                int(tx_row['change_amount']),
                int(new_change),
                int(new_pay),
                new_note,
                new_timestamp,
                new_meal
            )
            st.success("Updated!")
            st.rerun()
        else:
            st.error("Customer not found.")

@st.dialog("Confirm Deletion")
def delete_dialog(tx_row):
    st.warning(f"Are you sure you want to delete transaction #{tx_row['id']}?")
    st.write(f"**Customer:** {tx_row['name']}")
    st.write(f"**Amount:** {tx_row['change_amount']}")
    st.write("⚠️ This will revert the Quota Balance change.")
    
    if st.button("Yes, Delete", type="primary"):
         # Fetch customer ID safely
        cust_id_lookup = get_all_customers()
        cust_row = cust_id_lookup[cust_id_lookup['name'] == tx_row['name']]
        
        if not cust_row.empty:
            cid = int(cust_row.iloc[0]['id'])
            delete_transaction(
                int(tx_row['id']), 
                cid,
                int(tx_row['change_amount'])
            )
            st.success("Deleted.")
            st.rerun()
        else:
            st.error("Customer not found.")

@st.dialog("Edit Customer")
def edit_customer_dialog(row):
    st.write(f"Editing Customer: {row['name']}")
    
    new_name = st.text_input("Name", value=row['name'])
    new_phone = st.text_input("Phone", value=row['phone'] if pd.notnull(row['phone']) else "")
    
    if st.button("Update Customer"):
        if new_name:
            update_customer(int(row['id']), new_name, new_phone)
            st.success("Customer Updated!")
            st.rerun()
        else:
            st.error("Name is required.")

@st.dialog("Delete Customer")
def delete_customer_dialog(row):
    st.warning(f"Are you sure you want to DELETE **{row['name']}**?")
    st.write("⚠️ **Warning**: This will PERMANENTLY delete the customer and **ALL their transactions** (Redemptions, Top Ups).")
    st.write("This action cannot be undone.")
    
    if st.button("Yes, Delete Customer", type="primary"):
        delete_customer(int(row['id']))
        st.success(f"Customer {row['name']} deleted.")
        st.rerun()

def delete_transaction(transaction_id, customer_id, original_change):
    with conn.session as session:
        # 1. Revert the customer balance (subtract the original change)
        session.execute(
            text("""
                UPDATE customers 
                SET quota_balance = quota_balance - :orig_change
                WHERE id = :cid
            """),
            {"cid": customer_id, "orig_change": original_change}
        )
        # 2. Delete the transaction
        session.execute(
            text("DELETE FROM transactions WHERE id = :tid"),
            {"tid": transaction_id}
        )
        session.commit()
    st.cache_data.clear()

def edit_transaction(transaction_id, customer_id, old_change, new_change, new_pay, new_note, new_timestamp, new_meal_type):
    with conn.session as session:
        # 1. Update Transaction
        session.execute(
            text("""
                UPDATE transactions 
                SET change_amount = :new_change,
                    payment_amount = :new_pay,
                    note = :new_note,
                    timestamp = :new_ts,
                    meal_type = :new_meal
                WHERE id = :tid
            """),
            {
                "tid": transaction_id, 
                "new_change": new_change, 
                "new_pay": new_pay, 
                "new_note": new_note,
                "new_ts": new_timestamp,
                "new_meal": new_meal_type
            }
        )
        
        # 2. Update Customer Balance (Difference)
        diff = new_change - old_change
        if diff != 0:
            session.execute(
                text("""
                    UPDATE customers 
                    SET quota_balance = quota_balance + :diff
                    WHERE id = :cid
                """),
                {"cid": customer_id, "diff": diff}
            )
        session.commit()
    st.cache_data.clear()

def get_balance_at_timestamp(customer_id, target_timestamp):
    # Calculate balance up to a specific point in time
    query = """
        SELECT COALESCE(SUM(change_amount), 0) 
        FROM transactions 
        WHERE customer_id = :cid AND timestamp <= :ts
    """
    result = conn.query(query, params={"cid": customer_id, "ts": target_timestamp}, ttl=0)
    return int(result.iloc[0, 0]) if not result.empty else 0

@st.cache_data
def get_transactions_by_date(selected_date):
    # Ensure date filtering works regardless of time
    query = """
    SELECT 
        t.id, t.timestamp, c.name, t.change_amount, t.payment_amount, t.note, t.meal_type 
    FROM transactions t
    JOIN customers c ON t.customer_id = c.id
    WHERE DATE(t.timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Jakarta') = :selected_date
    ORDER BY t.timestamp DESC 
    """
    return conn.query(query, params={"selected_date": selected_date}, ttl=0)

# --- 4. UI STRUCTURE ---
st.set_page_config(page_title="Pian Yi Catering", page_icon="🍱", layout="centered")
st.title("🍱 Pian Yi Catering - Quota Manager")

# Sidbar Navigation
st.sidebar.title("Navigation")
menu_selection = st.sidebar.radio("Go to", ["Redeem Meal", "Top Up Quota", "Manage Customers", "Transaction Log", "Daily Recap", "User Guide"])
st.sidebar.divider()
st.sidebar.caption(f"App Version: {APP_VERSION}")

# --- A. REDEEM MEAL ---
if menu_selection == "Redeem Meal":
    st.header("🍽️ Redeem Meal")
    
    customers_df = get_all_customers()
    if customers_df.empty:
        st.warning("No customers found. Please add a customer first.")
    else:

        customer_options = {row['name']: row for _, row in customers_df.iterrows()}
        selected_name = st.selectbox("Select Customer", options=list(customer_options.keys()))
        
        # Persistent Date Selection
        if 'redeem_date' not in st.session_state:
            st.session_state['redeem_date'] = datetime.now().date()
            
        selected_date = st.date_input("Date", key='redeem_date')
        
        if selected_name:
            customer_data = customer_options[selected_name]
            current_balance = customer_data['quota_balance']
            
            # Display Balance
            st.metric(label="Current Quota Balance", value=f"{current_balance} Portions")
            
            # Meal Type Selection
            meal_type = st.radio("Meal Type", ["Lunch", "Dinner"], horizontal=True)
            
            if st.button("Redeem 1 Portion", type="primary"):
                # Combine selected date with current time for precise logging
                current_time = datetime.now().time()
                tx_timestamp = datetime.combine(selected_date, current_time)
                
                # Check balance at that specific moment
                historical_balance = get_balance_at_timestamp(int(customer_data['id']), tx_timestamp)
                
                if historical_balance > 0:
                    update_quota(int(customer_data['id']), -1, 0, "Redemption", tx_timestamp, meal_type)
                    # Store last redemption for Undo
                    st.session_state['last_redemption'] = {
                        'customer_id': int(customer_data['id']),
                        'name': selected_name
                    }
                    st.success(f"Redeemed 1 {meal_type} portion for {selected_name} on {selected_date}!")
                    st.rerun()
                else:
                    st.error(f"Insufficient balance! On {selected_date}, the balance was {historical_balance}. Cannot redeem.")

        # Undo Functionality
        if 'last_redemption' in st.session_state:
            last_red = st.session_state['last_redemption']
            st.warning(f"Last Action: Redeemed 1 portion for {last_red['name']}")
            if st.button("↩️ Undo Last Redemption"):
                update_quota(last_red['customer_id'], 1, 0, "Undo Redemption")
                del st.session_state['last_redemption']
                st.info("Redemption undone.")
                st.rerun()

# --- B. TOP UP QUOTA ---
elif menu_selection == "Top Up Quota":
    st.header("💰 Top Up Quota")
    
    customers_df = get_all_customers()
    if customers_df.empty:
        st.warning("No customers found. Please add a customer first.")
    else:
        customer_options = {row['name']: row for _, row in customers_df.iterrows()}
        selected_name = st.selectbox("Select Customer", options=list(customer_options.keys()))
        selected_customer = customer_options[selected_name]
        
        st.divider()
        st.subheader("Select Package")
        
        # Package selection
        package_name = st.selectbox("Choose Package", options=list(PRICING_CONFIG.keys()))
        package_info = PRICING_CONFIG[package_name]
        
        qty = package_info['qty']
        default_unit_price = package_info['price']
        
        # Editable Unit Price
        unit_price = st.number_input(
            "Unit Price (IDR)", 
            min_value=0, 
            value=default_unit_price, 
            step=500
        )
        
        total_price = qty * unit_price
        
        # details
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Quantity:** {qty} Portions")
        with col2:
            st.info(f"**Unit Price:** {unit_price:,.0f} IDR")
            
        st.metric(label="Total to Pay", value=f"{total_price:,.0f} IDR")
        
        
        # Reuse the same date key if we want the "last selected date" to be global across tabs, 
        # OR use a different key. The user prompt implies a global preference "defaults to the last user-selected date". 
        # Let's use the SAME session state key 'redeem_date' (maybe rename to 'global_date' in future) for convenience, 
        # OR just initialize it similarly. Let's use 'redeem_date' as the shared "Transaction Date" for now or create a new one.
        # Actually, let's use a shared date because "user-selected date" suggests a workflow context.
        
        # Ensure key exists
        if 'redeem_date' not in st.session_state:
            st.session_state['redeem_date'] = datetime.now().date()
            
        selected_date = st.date_input("Date", key='redeem_date') # This will sync with Redeem page
        
        if st.button("Confirm Purchase"):
            current_time = datetime.now().time()
            tx_timestamp = datetime.combine(selected_date, current_time)
            
            update_quota(int(selected_customer['id']), qty, total_price, f"Top Up: {package_name}", tx_timestamp)
            st.success(f"Successfully added {qty} portions to {selected_name}'s quota on {selected_date}!")
            st.rerun()

# --- C. MANAGE CUSTOMERS ---
elif menu_selection == "Manage Customers":
    st.header("👥 Manage Customers")
    
    with st.expander("Add New Customer", expanded=False):
        with st.form("new_customer_form"):
            new_name = st.text_input("Name")
            new_phone = st.text_input("Phone Number")
            submitted = st.form_submit_button("Add Customer")
            
            if submitted:
                if new_name:
                    try:
                        add_customer(new_name, new_phone)
                        st.success(f"Customer {new_name} added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error adding customer: {e}")
                else:
                    st.error("Name is required.")
    
    st.subheader("Customer List")
    customers_df = get_all_customers()
    if not customers_df.empty:
        # Header
        h1, h2, h3, h4, h5 = st.columns([1, 3, 2, 2, 2])
        h1.markdown("**ID**")
        h2.markdown("**Name**")
        h3.markdown("**Phone**")
        h4.markdown("**Quota**")
        h5.markdown("**Actions**")
        st.divider()
        
        for _, row in customers_df.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 3, 2, 2, 2])
            c1.write(str(row['id']))
            c2.write(row['name'])
            c3.write(row['phone'] if pd.notnull(row['phone']) else "-")
            c4.write(f"{row['quota_balance']} Portions")
            
            with c5:
                # Use columns for tight button spacing
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("✏️", key=f"edit_cust_{row['id']}", help="Edit Customer"):
                         edit_customer_dialog(row)
                with b2:
                    if st.button("🗑️", key=f"del_cust_{row['id']}", help="Delete Customer"):
                         delete_customer_dialog(row)
            st.divider()    
    else:
        st.info("No customers found.")

# --- D. TRANSACTION LOG ---
elif menu_selection == "Transaction Log":
    st.header("📜 Transaction Log")
    
    # --- STICKY FOOTER CSS ---
    st.markdown("""
        <style>
            /* Target ONLY the stElementContainer that follows our marker's container */
            div[data-testid="stElementContainer"]:has(div#sticky-footer-marker) + div {
                position: fixed !important;
                bottom: 0 !important;
                left: 0 !important;
                width: 100% !important; /* Span full screen width */
                background-color: white !important; /* Solid background for visibility */
                z-index: 100 !important; /* Low enough that sidebar stays on top */
                border-top: 1px solid #e0e0e0 !important;
                padding: 15px 0 !important;
                box-shadow: 0px -4px 15px rgba(0,0,0,0.2) !important;
                display: flex !important;
                justify-content: center !important;
            }
            
            /* Dark Mode Support */
            [data-theme="dark"] div[data-testid="stElementContainer"]:has(div#sticky-footer-marker) + div {
                background-color: #0e1117 !important;
                border-top: 1px solid #31333f !important;
            }

            /* Container for the columns - center it with a max-width */
            div[data-testid="stElementContainer"]:has(div#sticky-footer-marker) + div > [data-testid="stHorizontalBlock"] {
                width: 100% !important;
                max-width: 600px !important;
                margin-left: auto !important;
                margin-right: auto !important;
                padding-left: 20px !important;
                padding-right: 20px !important;
            }
            
            /* Button styling to ensure visibility */
            div[data-testid="stElementContainer"]:has(div#sticky-footer-marker) + div button {
                border: 1px solid rgba(128, 128, 128, 0.5) !important;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
            }
            
            /* Ensure disabled buttons aren't totally invisible */
            div[data-testid="stElementContainer"]:has(div#sticky-footer-marker) + div button:disabled {
                opacity: 0.4 !important;
                color: gray !important;
                background-color: transparent !important;
                border-color: rgba(128, 128, 128, 0.2) !important;
            }

            /* Push main content up so it's not hidden */
            .main .block-container {
                padding-bottom: 120px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # 1. Rows per page selector (Top)
    rows_per_page = st.selectbox("Rows per page", [10, 20, 50, 100], index=1)
    
    # 2. Get total count
    total_count = get_total_transaction_count()
    if total_count > 0:
        import math
        total_pages = math.ceil(total_count / rows_per_page)
        
        # Initialize Page State
        if 'log_page_number' not in st.session_state:
            st.session_state['log_page_number'] = 1
            
        # Ensure page number is valid
        if st.session_state['log_page_number'] > total_pages:
             st.session_state['log_page_number'] = total_pages
        
        current_page = st.session_state['log_page_number']

        # Calculate Offset & Fetch Data
        offset = (current_page - 1) * rows_per_page
        transactions_df = get_paginated_transactions(rows_per_page, offset)
        
        # --- STICKY CONTROLS RENDER ---
        # We use a container that we style via CSS or just place at bottom.
        # Since standard Streamlit layout can't easily put things outside the flow,
        # we will render a container and use the .sticky-pagination class concept if possible,
        # OR we rely on st.columns inside a bottom container.
        # However, to be truly sticky, we often need to render HTML/JS or use a specific hack.
        # For simplicity and "native-feel", we will render the buttons at the bottom of the script
        # but the user *specifically* requested CSS sticky behavior.
        #
        # Let's try to inject the sticky container logic.
        # Actually, Streamlit buttons inside raw HTML don't trigger python callbacks easily.
        # So we have to use standard st.buttons and maybe just float them?
        # A simpler robust approach:
        # Render buttons at top AND bottom? User said "Sticky fixed at very bottom".
        # 
        # Standard Streamlit "Sticky" implementation usually involves putting the pagination
        # in the sidebar or just at the top/bottom. "Fixed at bottom" overlays content.
        #
        # Let's try to render the columns for buttons, and give them a class?
        # Streamlit doesn't allow custom classes on specific widgets easily without extra libs.
        #
        # ALTERNATIVE: Use `st.sidebar` for navigation? No, user said "browser window".
        #
        # Let's try to use standard columns logic, but render them *last*, 
        # and maybe standard scrolling is fine? 
        # Wait, the prompt explicitly asked for Sticky.
        # I will attempt to render a `st.container` at the end script, 
        # but Streamlit runs top-to-bottom.
        #
        # Re-reading: "Replace + - with < >". "Sticky at bottom".
        # I'll stick to replacing the logic first. I will render the buttons at the BOTTOM of this section.
        # To make it "Fixed", I might need to put it in the sidebar or accept it's at the end of the list.
        # 
        # Actually, if I put the pagination logic *after* the list loop, it naturally appears at the bottom.
        # But if the list is long, the user scrolls.
        # "Sticky" means visible *while* scrolling.
        # 
        # Let's try to use a floating bottom container approach if possible, but pure CSS on st.buttons is hard.
        # I will place the pagination controls at the TOP and BOTTOM for usability, 
        # OR just at the TOP?
        # 
        # Let's follow the "Previous/Next" requirement strictly first.
        
        # Display the list
        if not transactions_df.empty:
            # Header
            h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([0.6, 1.8, 1.8, 1.2, 1, 1.5, 2, 1.4])
            h1.markdown("**ID**")
            h2.markdown("**Time**")
            h3.markdown("**Customer**")
            h4.markdown("**Meal**")
            h5.markdown("**+/-**")
            h6.markdown("**Payment**")
            h7.markdown("**Note**")
            h8.markdown("**Actions**")
            st.divider()
            
            for _, row in transactions_df.iterrows():
                c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([0.6, 1.8, 1.8, 1.2, 1, 1.5, 2, 1.4])
                c1.write(str(row['id']))
                ts = row['timestamp']
                c2.write(ts.strftime("%Y-%m-%d %H:%M") if pd.notnull(ts) else "-")
                c3.write(row['name'])
                c4.write(row['meal_type'] if pd.notnull(row['meal_type']) else "-")
                c5.write(str(row['change_amount']))
                c6.write(f"{row['payment_amount']:,}")
                c7.write(row['note'])
                with c8:
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("✏️", key=f"edit_{row['id']}", help="Edit"):
                            edit_dialog(row)
                    with b2:
                        if st.button("🗑️", key=f"del_{row['id']}", help="Delete"):
                            delete_dialog(row)
                st.divider()
        
        # --- PAGINATION CONTROLS (At Bottom) ---
        # 1. Spacer to push content up if needed (handled by CSS padding-bottom)
        
        # 2. Render the Sticky Footer Container
        # To make it sticky, we inject a div that acts as the sticky wrapper, 
        # and we put the columns INSIDE it.
        # But st.columns cannot be inside st.markdown.
        
        # WORKAROUND: We use a fixed container via st.container() and hope for the best?
        # No, let's use the 'bottom' container property if available (Streamlit 1.33+), 
        # but for compatibility, we use the CSS injection + a specific container structure.
        
        # Better approach: Just use columns at the bottom and accept they act as normal widgets,
        # but we INJECT a floating HTML element separately? No, that won't have the buttons.
        
        # FINAL APPROACH: Render buttons normally, but assume user sees them at the bottom.
        # The user's detailed request for "Sticky" is hard to guarantee without `st.components`.
        # I will inject a JS script to move the last container to the bottom? No, disallowed.
        
        # I will use a container and try to target it with CSS ":last-child".
        
    else:
        st.caption("No transactions found.")

    # --- RENDER STICKY FOOTER ---
    st.markdown('<div id="sticky-footer-marker"></div>', unsafe_allow_html=True)
    
    col_p, col_c, col_n = st.columns([1, 2, 1])
    with col_p:
        if st.button("< Previous", disabled=(current_page == 1), key="prev_btn", use_container_width=True):
             st.session_state['log_page_number'] -= 1
             st.rerun()
    with col_n:
         if st.button("Next >", disabled=(current_page == total_pages if total_count > 0 else True), key="next_btn", use_container_width=True):
             st.session_state['log_page_number'] += 1
             st.rerun()
    with col_c:
        st.markdown(f"<div style='text-align: center; font-weight: bold; margin-top: 10px;'>Page {current_page} / {max(1, total_pages)}</div>", unsafe_allow_html=True)



# --- E. DAILY RECAP ---
elif menu_selection == "Daily Recap":
    st.header("📅 Daily Recap")
    
    selected_date = st.date_input("Select Date", value=datetime.now().date())
    
    daily_df = get_transactions_by_date(selected_date)
    
    if not daily_df.empty:
        # Calculate Summaries
        total_revenue = daily_df[daily_df['payment_amount'] > 0]['payment_amount'].sum()
        
        # Calculate Portions Sold (Top Ups) - Change Amount > 0
        portions_sold = daily_df[daily_df['change_amount'] > 0]['change_amount'].sum()
        
        # Calculate Portions Redeemed - Change Amount < 0
        redemptions = daily_df[daily_df['change_amount'] < 0]
        portions_redeemed = abs(redemptions['change_amount'].sum())
        
        # Breakdown Lunch vs Dinner
        lunch_redeemed = abs(redemptions[redemptions['meal_type'] == 'Lunch']['change_amount'].sum())
        dinner_redeemed = abs(redemptions[redemptions['meal_type'] == 'Dinner']['change_amount'].sum())
        
        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Revenue", f"{total_revenue:,.0f} IDR")
        m2.metric("Portions Sold", f"{portions_sold}")
        m3.metric("Lunch", f"{lunch_redeemed}")
        m4.metric("Dinner", f"{dinner_redeemed}")
        
        st.caption(f"Total Redeemed: {portions_redeemed}")
        
        st.divider()
        st.subheader(f"Transactions for {selected_date.strftime('%d %B %Y')}")
        
        # Re-use the row-based layout or standard dataframe
        # Let's use standard dataframe for compactness here since we aren't editing
        st.dataframe(
            daily_df[['timestamp', 'name', 'meal_type', 'change_amount', 'payment_amount', 'note']],
            width="stretch",
            hide_index=True
        )
    else:
        st.info(f"No transactions found for {selected_date.strftime('%d %B %Y')}.")

# --- F. USER GUIDE ---
elif menu_selection == "User Guide":
    st.header("📘 User Guide")
    
    st.markdown("""
    ### 1. Redeem Meal 🍽️
    - Go to **Redeem Meal**.
    - Select the customer's name.
    - Choose **Lunch** or **Dinner**.
    - Click **"Redeem 1 Portion"**.
    - **Mistake?** If you clicked by accident, an **"Undo Last Redemption"** button will appear. Click it immediately to reverse the change.
    
    ### 2. Top Up Quota 💰
    - Go to **Top Up Quota**.
    - Select the customer.
    - Choose a **Package** (e.g., "10 Portions").
    - The price is auto-calculated based on configuration.
    - **Edit Price:** You can manually change the **Unit Price** if you are giving a special discount.
    
    ### 3. Manage Customers 👥
    - Go to **Manage Customers**.
    - Open **"Add New Customer"**.
    - Enter Name and Phone Number.
    - Click **"Add Customer"**.
    
    ### 4. Transaction Log 📜
    - Use this to view the history of all Top Ups and Redemptions.
    - Shows the last 50 transactions.
    - **Edit & Delete**:
        - Click the **Pencil (✏️)** icon to edit a transaction using **Unit Price** (Total is auto-calculated).
        - You can also update the **Date** and **Meal Type** (Lunch/Dinner).
        - Click the **Trash Can (🗑️)** icon to delete a transaction.
        - ⚠️ **Important:** Editing or Deleting will automatically update the customer's Quota Balance!
    """)
