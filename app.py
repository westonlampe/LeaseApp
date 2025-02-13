import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

############################
# 1. HELPER FUNCTIONS (same as yours)
############################
def generate_monthly_payments(base_payment, lease_term, annual_escalation_rate, payment_timing="end"):
    monthly_payments = []
    for month in range(1, lease_term + 1):
        years_elapsed = (month - 1) // 12
        payment_for_month = base_payment * (1 + annual_escalation_rate) ** years_elapsed
        monthly_payments.append(payment_for_month)
    return monthly_payments

def present_value_of_varied_payments(payments, monthly_rate, payment_timing="end"):
    pv = 0.0
    for i, pmt in enumerate(payments, start=1):
        if payment_timing == "end":
            pv += pmt / ((1 + monthly_rate) ** i)
        else:
            pv += pmt / ((1 + monthly_rate) ** (i - 1))
    return pv

############################
# 2. MAIN AMORTIZATION FUNCTION (same as yours)
############################
def generate_amortization_schedule(
    lease_term,
    base_payment,
    annual_discount_rate,
    annual_escalation_rate,
    start_date,
    payment_timing="end",
    lease_type="Operating"
):
    monthly_payments = generate_monthly_payments(
        base_payment, lease_term, annual_escalation_rate, payment_timing
    )
    
    monthly_rate = annual_discount_rate / 12.0
    lease_liability = present_value_of_varied_payments(monthly_payments, monthly_rate, payment_timing)
    rou_asset = lease_liability
    schedule_rows = []
    liability_balance = lease_liability
    
    if lease_type == "Operating":
        total_lease_expense_per_month = sum(monthly_payments) / lease_term
    
    for period in range(1, lease_term + 1):
        current_payment = monthly_payments[period - 1]
        interest_expense = liability_balance * monthly_rate
        
        if payment_timing == "end":
            principal = current_payment - interest_expense
        else:
            principal = current_payment
            interest_expense = (liability_balance - principal) * monthly_rate
        
        new_liability_balance = liability_balance - principal
        
        if lease_type == "Operating":
            total_lease_expense = total_lease_expense_per_month
            rou_amortization = total_lease_expense - interest_expense
            rou_asset -= rou_amortization
        else:
            rou_amortization = rou_asset / lease_term
        
        schedule_rows.append({
            "Period": period,
            "Date": pd.to_datetime(start_date) + pd.DateOffset(months=period - 1),
            "Payment": current_payment,
            "Interest_Expense": interest_expense,
            "Principal": principal,
            "Lease_Liability_Balance": new_liability_balance,
            "ROU_Asset_Amortization": rou_amortization,
            "ROU_Asset_Balance": max(rou_asset, 0),
        })
        
        liability_balance = new_liability_balance
    
    return pd.DataFrame(schedule_rows)

############################
# 3. JOURNAL ENTRY CREATION (same as yours)
############################
def generate_monthly_journal_entries(schedule_df, lease_type="Operating"):
    entries = []
    for _, row in schedule_df.iterrows():
        period = row["Period"]
        date_val = row["Date"]
        payment = row["Payment"]
        interest_expense = row["Interest_Expense"]
        principal = row["Principal"]
        rou_amort = row["ROU_Asset_Amortization"]
        
        if lease_type == "Operating":
            # DR Lease Expense, CR Cash
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Lease Expense",
                "Debit": round(payment, 2),
                "Credit": 0.0
            })
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Cash",
                "Debit": 0.0,
                "Credit": round(payment, 2)
            })
            if rou_amort != 0.0:
                entries.append({
                    "Date": date_val,
                    "Period": period,
                    "Account": "ROU Asset Amortization Expense",
                    "Debit": round(rou_amort, 2),
                    "Credit": 0.0
                })
                entries.append({
                    "Date": date_val,
                    "Period": period,
                    "Account": "Accumulated Amortization - ROU Asset",
                    "Debit": 0.0,
                    "Credit": round(rou_amort, 2)
                })
        else:
            # Finance Lease
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Interest Expense",
                "Debit": round(interest_expense, 2),
                "Credit": 0.0
            })
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Lease Liability",
                "Debit": round(principal, 2),
                "Credit": 0.0
            })
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Cash",
                "Debit": 0.0,
                "Credit": round(payment, 2)
            })
            if rou_amort != 0.0:
                entries.append({
                    "Date": date_val,
                    "Period": period,
                    "Account": "Amortization Expense - ROU Asset",
                    "Debit": round(rou_amort, 2),
                    "Credit": 0.0
                })
                entries.append({
                    "Date": date_val,
                    "Period": period,
                    "Account": "Accumulated Amortization - ROU Asset",
                    "Debit": 0.0,
                    "Credit": round(rou_amort, 2)
                })
    
    return pd.DataFrame(entries)

############################
# 4. GOOGLE SHEETS HELPER
############################
def get_gsheet_connection():
    # 1) Put your credentials JSON file in a secure place (or store in st.secrets)
    # 2) Reference that location below, or build Credentials object from st.secrets
    # Example using a credentials file "my_creds.json" in the current directory:
    creds = Credentials.from_service_account_file("my_creds.json", scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    client = gspread.authorize(creds)
    return client

def load_leases_from_gsheet(sheet_name="LeaseData"):
    """
    Reads existing rows from a tab in Google Sheets and reconstructs the 
    saved lease data (amortization schedule + journal) if present.
    In reality, you might store each lease row separately or store just 
    summary data. This is a simplistic approach.
    """
    try:
        client = get_gsheet_connection()
        sheet = client.open(sheet_name).sheet1  # open first worksheet
        data = sheet.get_all_records()
        
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(data)
        
        # Example assumption:
        # We have columns like ["LeaseName", "SerializedSchedule", "SerializedJournal"]
        
        saved_leases = {}
        for _, row in df.iterrows():
            lease_name = row["LeaseName"]
            # If you stored schedule/journal as JSON strings, un-serialize them
            schedule_df = pd.read_json(row["SerializedSchedule"])
            journal_df = pd.read_json(row["SerializedJournal"])
            saved_leases[lease_name] = {
                "schedule": schedule_df,
                "journal": journal_df
            }
            
        return saved_leases
    except Exception as e:
        st.warning(f"Unable to load from Google Sheets: {e}")
        return {}

def save_lease_to_gsheet(lease_name, schedule_df, journal_df, sheet_name="LeaseData"):
    """
    Appends a new row with the lease data. A more advanced approach would 
    upsert rows instead of always appending.
    """
    try:
        client = get_gsheet_connection()
        sheet = client.open(sheet_name).sheet1
        
        # Convert DataFrames to JSON strings or CSV
        schedule_json = schedule_df.to_json()
        journal_json = journal_df.to_json()
        
        new_row = [lease_name, schedule_json, journal_json]
        # Append a new row at the bottom
        sheet.append_row(new_row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.warning(f"Unable to save to Google Sheets: {e}")

############################
# 5. STREAMLIT APP
############################
def main():
    st.title("ASC 842 LEASE MODULE")
    
    # 1) Initialize session state
    if "saved_leases" not in st.session_state:
        # Attempt to load from Google Sheets on first run
        st.session_state["saved_leases"] = load_leases_from_gsheet(sheet_name="LeaseData")
    
    st.sidebar.header("Lease Inputs")
    
    lease_name = st.sidebar.text_input("Lease Name/ID", value="My Lease")
    lease_type = st.sidebar.selectbox("Lease Classification", ["Operating", "Finance"])
    start_date = st.sidebar.date_input("Lease Start Date", value=date.today())
    lease_term = st.sidebar.number_input("Lease Term (months)", min_value=1, value=36)
    annual_discount_rate = st.sidebar.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
    base_payment_amount = st.sidebar.number_input("Base Monthly Payment (initial year)",
                                                  min_value=0.0,
                                                  value=1000.0)
    annual_escalation_pct = st.sidebar.number_input("Annual Payment Escalation Rate (%)",
                                                    min_value=0.0,
                                                    value=5.0)
    payment_timing = st.sidebar.selectbox("Payment Timing", ["end", "begin"])
    
    # 2) Generate schedule, save to session and Google Sheets
    if st.sidebar.button("Generate & Save Lease Schedule"):
        df_schedule = generate_amortization_schedule(
            lease_term=lease_term,
            base_payment=base_payment_amount,
            annual_discount_rate=annual_discount_rate / 100.0,
            annual_escalation_rate=annual_escalation_pct / 100.0,
            start_date=start_date,
            payment_timing=payment_timing,
            lease_type=lease_type
        )
        df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)
        
        # Save in session state
        st.session_state["saved_leases"][lease_name] = {
            "schedule": df_schedule,
            "journal": df_journal
        }
        
        # Also persist to Google Sheets
        save_lease_to_gsheet(lease_name, df_schedule, df_journal, sheet_name="LeaseData")
        
        st.success(f"Lease schedule for '{lease_name}' generated and saved!")
    
    # 3) Display all saved leases
    st.write("---")
    st.header("View Saved Lease")
    
    saved_lease_names = list(st.session_state["saved_leases"].keys())
    if saved_lease_names:
        selected_lease = st.selectbox("Select a saved lease to view:", options=saved_lease_names)
        
        if selected_lease:
            st.subheader(f"Lease Amortization Schedule: {selected_lease}")
            df_schedule = st.session_state["saved_leases"][selected_lease]["schedule"]
            st.dataframe(
                df_schedule.style.format({
                    "Payment": "{:,.2f}",
                    "Interest_Expense": "{:,.2f}",
                    "Principal": "{:,.2f}",
                    "Lease_Liability_Balance": "{:,.2f}",
                    "ROU_Asset_Amortization": "{:,.2f}",
                    "ROU_Asset_Balance": "{:,.2f}",
                })
            )
            
            csv_schedule = df_schedule.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Amortization Schedule (CSV)",
                data=csv_schedule,
                file_name=f"{selected_lease}_amortization_schedule.csv",
                mime="text/csv"
            )
            
            st.subheader(f"Monthly Journal Entries: {selected_lease}")
            df_journal = st.session_state["saved_leases"][selected_lease]["journal"]
            st.dataframe(
                df_journal.style.format({"Debit": "{:,.2f}", "Credit": "{:,.2f}"})
            )
            
            csv_journal = df_journal.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Journal Entries (CSV)",
                data=csv_journal,
                file_name=f"{selected_lease}_monthly_journal_entries.csv",
                mime="text/csv"
            )
    else:
        st.info("No leases saved yet. Generate a lease schedule to save and display it here.")

if __name__ == "__main__":
    main()
