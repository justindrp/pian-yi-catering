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

def update_quota(customer_id, change_amount, payment_amount, note):
    with conn.session as session:
        # Insert transaction
        session.execute(
            text("""
                INSERT INTO transactions (customer_id, change_amount, payment_amount, note)
                VALUES (:cid, :change, :pay, :note)
            """),
            {"cid": customer_id, "change": change_amount, "pay": payment_amount, "note": note}
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

def edit_transaction(transaction_id, customer_id, old_change, new_change, new_pay, new_note):
    with conn.session as session:
        # 1. Update Transaction
        session.execute(
            text("""
                UPDATE transactions 
                SET change_amount = :new_change,
                    payment_amount = :new_pay,
                    note = :new_note
                WHERE id = :tid
            """),
            {"tid": transaction_id, "new_change": new_change, "new_pay": new_pay, "new_note": new_note}
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

# --- 4. UI STRUCTURE ---
st.set_page_config(page_title="Pian Yi Catering", page_icon="🍱", layout="centered")
st.title("🍱 Pian Yi Catering - Quota Manager")

# Sidbar Navigation
st.sidebar.title("Navigation")
menu_selection = st.sidebar.radio("Go to", ["Redeem Meal", "Top Up Quota", "Manage Customers", "Transaction Log", "User Guide"])

# --- A. REDEEM MEAL ---
if menu_selection == "Redeem Meal":
    st.header("🍽️ Redeem Meal")
    
    customers_df = get_all_customers()
    if customers_df.empty:
        st.warning("No customers found. Please add a customer first.")
    else:
        customer_options = {row['name']: row for _, row in customers_df.iterrows()}
        selected_name = st.selectbox("Select Customer", options=list(customer_options.keys()))
        
        if selected_name:
            customer_data = customer_options[selected_name]
            current_balance = customer_data['quota_balance']
            
            # Display Balance
            st.metric(label="Current Quota Balance", value=f"{current_balance} Portions")
            
            if st.button("Redeem 1 Portion", type="primary"):
                if current_balance > 0:
                    update_quota(int(customer_data['id']), -1, 0, "Redemption")
                    # Store last redemption for Undo
                    st.session_state['last_redemption'] = {
                        'customer_id': int(customer_data['id']),
                        'name': selected_name
                    }
                    st.success(f"Redeemed 1 portion for {selected_name}!")
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
        
        if st.button("Confirm Purchase"):
            update_quota(int(selected_customer['id']), qty, total_price, f"Top Up: {package_name}")
            st.success(f"Successfully added {qty} portions to {selected_name}'s quota!")
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
        st.dataframe(
            transactions_df,
            width="stretch",
            hide_index=True
        )
    else:
        st.info("No transactions found.")

    st.divider()
    st.subheader("Manage Transaction")
    
    # Reload to ensure we have data for the selectbox
    tx_df = get_recent_transactions()
    
    if not tx_df.empty:
        # Create a mapping for the selectbox
        tx_options = {f"ID {row['id']} - {row['name']} ({row['change_amount']})": row for _, row in tx_df.iterrows()}
        selected_tx_label = st.selectbox("Select Transaction to Edit/Delete", options=list(tx_options.keys()))
        
        if selected_tx_label:
            selected_tx = tx_options[selected_tx_label]
            
            with st.expander("Edit / Delete Transaction", expanded=True):
                st.write(f"**Selected:** {selected_tx_label}")
                st.write(f"**Current Note:** {selected_tx['note']}")
                
                action = st.radio("Action", ["Edit", "Delete"], horizontal=True)
                
                if action == "Delete":
                    st.warning("⚠️ Deleting this transaction will revert the Quota Balance change!")
                    if st.button("Confirm Delete", type="primary"):
                        delete_transaction(
                            int(selected_tx['id']), 
                            int(get_all_customers().set_index('name').loc[selected_tx['name']]['id']), # Need customer ID, looking up by name is safe-ish for small scale or we join it in query
                            int(selected_tx['change_amount'])
                        )
                        st.success("Transaction deleted.")
                        st.rerun()
                        
                elif action == "Edit":
                    new_change = st.number_input("Change Amount (+/-)", value=int(selected_tx['change_amount']))
                    new_pay = st.number_input("Payment Amount", value=int(selected_tx['payment_amount']))
                    new_note = st.text_input("Note", value=selected_tx['note'])
                    
                    if st.button("Update Transaction"):
                        # Get Customer ID again (improving the query usually better, but hacky fix for now)
                        # To be safe, let's fetch customer_id properly in the get_recent_transactions query
                        # For now, we will assume unique names or fetch via helper
                        cust_id_lookup = get_all_customers()
                        cust_row = cust_id_lookup[cust_id_lookup['name'] == selected_tx['name']]
                        
                        if not cust_row.empty:
                            cid = int(cust_row.iloc[0]['id'])
                            edit_transaction(
                                int(selected_tx['id']),
                                cid,
                                int(selected_tx['change_amount']),
                                int(new_change),
                                int(new_pay),
                                new_note
                            )
                            st.success("Transaction updated.")
                            st.rerun()
                        else:
                            st.error("Could not find associated customer ID.")

# --- E. USER GUIDE ---
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
    """)
