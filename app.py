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

# --- 2. DATABASE CONNECTION & INIT ---
# Assumes [connections.supabase] is set in .streamlit/secrets.toml
conn = st.connection("supabase", type="sql")

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
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        session.commit()

# Run init_db once on script load (or handle via a separate setup script if preferred, 
# but running here ensures tables exist for the demo)
try:
    init_db()
except Exception as e:
    st.error(f"Database initialization failed: {e}")

# --- 3. HELPER FUNCTIONS ---
def get_all_customers():
    return conn.query("SELECT * FROM customers ORDER BY name ASC", ttl=0)

def get_recent_transactions():
    query = """
    SELECT 
        t.id, t.timestamp, c.name, t.change_amount, t.payment_amount, t.note 
    FROM transactions t
    JOIN customers c ON t.customer_id = c.id
    ORDER BY t.timestamp DESC 
    LIMIT 50
    """
    return conn.query(query, ttl=0)

def update_quota(customer_id, change_amount, payment_amount, note, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now()
        
    with conn.session as session:
        # Insert transaction
        session.execute(
            text("""
                INSERT INTO transactions (customer_id, change_amount, payment_amount, note, timestamp)
                VALUES (:cid, :change, :pay, :note, :ts)
            """),
            {"cid": customer_id, "change": change_amount, "pay": payment_amount, "note": note, "ts": timestamp}
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

def add_customer(name, phone):
    with conn.session as session:
        session.execute(
            text("INSERT INTO customers (name, phone) VALUES (:name, :phone)"),
            {"name": name, "phone": phone}
        )
        session.commit()

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
                new_timestamp
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

def edit_transaction(transaction_id, customer_id, old_change, new_change, new_pay, new_note, new_timestamp):
    with conn.session as session:
        # 1. Update Transaction
        session.execute(
            text("""
                UPDATE transactions 
                SET change_amount = :new_change,
                    payment_amount = :new_pay,
                    note = :new_note,
                    timestamp = :new_ts
                WHERE id = :tid
            """),
            {
                "tid": transaction_id, 
                "new_change": new_change, 
                "new_pay": new_pay, 
                "new_note": new_note,
                "new_ts": new_timestamp
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

def get_transactions_by_date(selected_date):
    # Ensure date filtering works regardless of time
    query = """
    SELECT 
        t.id, t.timestamp, c.name, t.change_amount, t.payment_amount, t.note 
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
            
            if st.button("Redeem 1 Portion", type="primary"):
                if current_balance > 0:
                    # Combine selected date with current time for precise logging
                    current_time = datetime.now().time()
                    tx_timestamp = datetime.combine(selected_date, current_time)
                    
                    update_quota(int(customer_data['id']), -1, 0, "Redemption", tx_timestamp)
                    # Store last redemption for Undo
                    st.session_state['last_redemption'] = {
                        'customer_id': int(customer_data['id']),
                        'name': selected_name
                    }
                    st.success(f"Redeemed 1 portion for {selected_name} on {selected_date}!")
                    st.rerun()
                else:
                    st.error("Insufficient balance! Please Top Up.")

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
        st.dataframe(
            customers_df[['name', 'phone', 'quota_balance', 'created_at']],
            width="stretch",
            hide_index=True
        )
    else:
        st.info("No customers found.")

# --- D. TRANSACTION LOG ---
elif menu_selection == "Transaction Log":
    st.header("📜 Transaction Log")
    st.caption("Showing last 50 transactions")
    
    transactions_df = get_recent_transactions()
    if not transactions_df.empty:
        # Header Row
        h1, h2, h3, h4, h5, h6, h7 = st.columns([1, 2, 2, 2, 2, 3, 2])
        h1.markdown("**ID**")
        h2.markdown("**Time**")
        h3.markdown("**Customer**")
        h4.markdown("**Change**")
        h5.markdown("**Payment**")
        h6.markdown("**Note**")
        h7.markdown("**Actions**")
        
        st.divider()
        
        for _, row in transactions_df.iterrows():
            c1, c2, c3, c4, c5, c6, c7 = st.columns([1, 2, 2, 2, 2, 3, 2])
            
            c1.write(str(row['id']))
            # Format timestamp if valid
            ts = row['timestamp']
            c2.write(ts.strftime("%Y-%m-%d %H:%M") if pd.notnull(ts) else "-")
            c3.write(row['name'])
            c4.write(str(row['change_amount']))
            c5.write(f"{row['payment_amount']:,}")
            c6.write(row['note'])
            
            with c7:
                # Use columns for tight button spacing
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("✏️", key=f"edit_{row['id']}", help="Edit"):
                        edit_dialog(row)
                with b2:
                    if st.button("🗑️", key=f"del_{row['id']}", help="Delete"):
                        delete_dialog(row)
            
            st.divider()

    else:
        st.info("No transactions found.")



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
        portions_redeemed = abs(daily_df[daily_df['change_amount'] < 0]['change_amount'].sum())
        
        # Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Revenue", f"{total_revenue:,.0f} IDR")
        m2.metric("Portions Sold", f"{portions_sold}")
        m3.metric("Portions Redeemed", f"{portions_redeemed}")
        
        st.divider()
        st.subheader(f"Transactions for {selected_date.strftime('%d %B %Y')}")
        
        # Re-use the row-based layout or standard dataframe
        # Let's use standard dataframe for compactness here since we aren't editing
        st.dataframe(
            daily_df[['timestamp', 'name', 'change_amount', 'payment_amount', 'note']],
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
        - Click the **Trash Can (🗑️)** icon to delete a transaction.
        - ⚠️ **Important:** Editing or Deleting will automatically update the customer's Quota Balance!
    """)
