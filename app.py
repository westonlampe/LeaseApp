import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
import requests

############################
# 1. ORACLE APEX CONFIG
############################
APEX_BASE_URL = "https://g382f1e4d487358-taxproprototype.adb.us-phoenix-1.oraclecloudapps.com/ords/txp/leasedata/"

############################
# 2. APEX PUSH-ONLY FUNCTIONS
############################

def post_lease_to_apex(lease_name, schedule_df, journal_df):
    """
    Always POST /leasedata/ with the new record.
    (Assumes your APEX REST service can handle either inserting 
     or upserting the record if it already exists.)
    """
    payload = {
        "lease_name": lease_name,
        "schedule_json": schedule_df.to_json(),
        "journal_json": journal_df.to_json()
    }
    try:
        resp = requests.post(APEX_BASE_URL, json=payload)
        resp.raise_for_status()  # Raise error if not 2xx
        st.success(f"Lease '{lease_name}' pushed to APEX (POST).")
    except Exception as e:
        st.warning(f"Unable to POST lease '{lease_name}' to APEX: {e}")

def put_lease_to_apex(lease_name, schedule_df, journal_df):
    """
    PUT /leasedata/{lease_name}
    Only works if your APEX endpoint is configured for PUT, 
    otherwise you'll get 405 Method Not Allowed.
    """
    payload = {
        "lease_name": lease_name,
        "schedule_json": schedule_df.to_json(),
        "journal_json": journal_df.to_json()
    }
    try:
        url = APEX_BASE_URL + lease_name
        resp = requests.put(url, json=payload)
        resp.raise_for_status()
        st.success(f"Lease '{lease_name}' updated via PUT.")
    except Exception as e:
        st.warning(f"Unable to PUT lease '{lease_name}' to APEX: {e}")

def delete_lease_in_apex(lease_name):
    """
    DELETE /leasedata/{lease_name}
    Only if your APEX REST allows DELETE.
    """
    try:
        url = APEX_BASE_URL + lease_name
        resp = requests.delete(url)
        resp.raise_for_status()
        st.success(f"Deleted lease '{lease_name}' from APEX.")
    except Exception as e:
        st.warning(f"Unable to delete lease '{lease_name}' from APEX: {e}")

############################
# 3. HELPER FUNCTIONS (same as your original code)
############################

def generate_monthly_payments(base_payment, lease_term, annual_escalation_rate, payment_timing="end"):
    payments = []
    for month in range(1, lease_term + 1):
        years_elapsed = (month - 1) // 12
        pay = base_payment * (1 + annual_escalation_rate) ** years_elapsed
        payments.append(pay)
    return payments

def present_value_of_varied_payments(payments, monthly_rate, payment_timing="end"):
    pv = 0.0
    for i, pmt in enumerate(payments, start=1):
        if payment_timing == "end":
            pv += pmt / ((1 + monthly_rate) ** i)
        else:
            pv += pmt / ((1 + monthly_rate) ** (i - 1))
    return pv

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
    rows = []
    liability_balance = lease_liability
    
    if lease_type == "Operating":
        total_expense_per_month = sum(monthly_payments) / lease_term
    
    for period in range(1, lease_term + 1):
        payment = monthly_payments[period - 1]
        interest = liability_balance * monthly_rate
        
        if payment_timing == "end":
            principal = payment - interest
        else:
            principal = payment
            interest = (liability_balance - principal) * monthly_rate
        
        new_balance = liability_balance - principal
        
        if lease_type == "Operating":
            total_expense = total_expense_per_month
            rou_amort = total_expense - interest
            rou_asset -= rou_amort
        else:
            rou_amort = rou_asset / lease_term
        
        rows.append({
            "Period": period,
            "Date": pd.to_datetime(start_date) + pd.DateOffset(months=period - 1),
            "Payment": payment,
            "Interest_Expense": interest,
            "Principal": principal,
            "Lease_Liability_Balance": new_balance,
            "ROU_Asset_Amortization": rou_amort,
            "ROU_Asset_Balance": max(rou_asset, 0),
        })
        
        liability_balance = new_balance
    
    return pd.DataFrame(rows)

def generate_monthly_journal_entries(schedule_df, lease_type="Operating"):
    entries = []
    for _, row in schedule_df.iterrows():
        period = row["Period"]
        date_val = row["Date"]
        pay = row["Payment"]
        interest = row["Interest_Expense"]
        principal = row["Principal"]
        rou_amort = row["ROU_Asset_Amortization"]
        
        if lease_type == "Operating":
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Lease Expense",
                "Debit": round(pay, 2),
                "Credit": 0.0
            })
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Cash",
                "Debit": 0.0,
                "Credit": round(pay, 2)
            })
            if rou_amort != 0:
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
            entries.append({
                "Date": date_val,
                "Period": period,
                "Account": "Interest Expense",
                "Debit": round(interest, 2),
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
                "Credit": round(pay, 2)
            })
            if rou_amort != 0:
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
# 6. STREAMLIT APP (No GET from APEX)
############################
def main():
    st.title("ASC 842 LEASE MODULE (Push-Only to Oracle APEX)")

    # We won't load from APEX at all. 
    # We'll just keep an in-memory store for the session.
    if "saved_leases" not in st.session_state:
        st.session_state["saved_leases"] = {}

    st.sidebar.header("Lease Input")
    lease_name = st.sidebar.text_input("Lease Name", value="MyLease")
    lease_type = st.sidebar.selectbox("Lease Classification", ["Operating", "Finance"])
    start_date_val = st.sidebar.date_input("Lease Start Date", value=date.today())
    term = st.sidebar.number_input("Lease Term (months)", min_value=1, value=36)
    discount_rate = st.sidebar.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
    base_payment = st.sidebar.number_input("Base Monthly Payment", min_value=0.0, value=1000.0)
    esc_rate = st.sidebar.number_input("Annual Escalation Rate (%)", min_value=0.0, value=5.0)
    pay_timing = st.sidebar.selectbox("Payment Timing", ["end", "begin"])

    # Push to APEX with POST or PUT
    push_method = st.sidebar.radio("APEX Method", ["POST Only", "PUT Only"])

    # Generate & Save
    if st.sidebar.button("Generate Sched + Push to APEX"):
        # 1) Generate local schedule + journal
        df_schedule = generate_amortization_schedule(
            lease_term=term,
            base_payment=base_payment,
            annual_discount_rate=discount_rate/100.0,
            annual_escalation_rate=esc_rate/100.0,
            start_date=start_date_val,
            payment_timing=pay_timing,
            lease_type=lease_type
        )
        df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)

        # 2) Store in session
        st.session_state["saved_leases"][lease_name] = {
            "schedule": df_schedule,
            "journal": df_journal
        }

        # 3) Push to APEX
        if push_method == "POST Only":
            post_lease_to_apex(lease_name, df_schedule, df_journal)
        else:
            put_lease_to_apex(lease_name, df_schedule, df_journal)

    st.write("---")
    st.header("Leases in This Session (Not from APEX)")

    saved_names = list(st.session_state["saved_leases"].keys())
    if saved_names:
        selected_lease = st.selectbox("Select a lease to view:", saved_names)
        if selected_lease:
            df_sch = st.session_state["saved_leases"][selected_lease]["schedule"]
            st.subheader(f"Amort Schedule: {selected_lease}")
            st.dataframe(df_sch.style.format({
                "Payment": "{:,.2f}",
                "Interest_Expense": "{:,.2f}",
                "Principal": "{:,.2f}",
                "Lease_Liability_Balance": "{:,.2f}",
                "ROU_Asset_Amortization": "{:,.2f}",
                "ROU_Asset_Balance": "{:,.2f}",
            }))

            df_j = st.session_state["saved_leases"][selected_lease]["journal"]
            st.subheader("Monthly Journal Entries")
            st.dataframe(df_j.style.format({"Debit": "{:,.2f}", "Credit": "{:,.2f}"}))

            if st.button(f"Delete '{selected_lease}' in APEX?"):
                delete_lease_in_apex(selected_lease)
                # (Optionally) also remove from local session
                del st.session_state["saved_leases"][selected_lease]
                st.experimental_rerun()
    else:
        st.info("No leases have been created this session.")

if __name__ == "__main__":
    main()
