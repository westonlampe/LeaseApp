import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
import requests

############################
# 1. ORACLE APEX CONFIG
############################
APEX_BASE_URL = "https://g382f1e4d487358-taxproprototype.adb.us-phoenix-1.oraclecloudapps.com/ords/txp/leasedata/"

def load_leases_from_apex():
    """
    GET /leasedata/
    Expects APEX to return JSON with "items": [ { "lease_name":..., "schedule_json":..., "journal_json":... }, ... ]
    """
    saved_leases = {}
    try:
        resp = requests.get(APEX_BASE_URL)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        for row in items:
            lease_name = row["lease_name"]
            schedule_df = pd.read_json(row["schedule_json"])
            journal_df = pd.read_json(row["journal_json"])
            saved_leases[lease_name] = {
                "schedule": schedule_df,
                "journal": journal_df
            }
    except Exception as e:
        st.warning(f"Unable to load from Oracle APEX: {e}")
    return saved_leases

############################
# 2A. If You Do NOT Want PUT (Always POST)
############################
def save_lease_to_apex_post_only(lease_name, schedule_df, journal_df):
    """
    Always POST /leasedata/ with the full record.
    On the APEX side, your PL/SQL or database logic must handle
    whether it's a new record vs. existing (i.e., do an UPDATE if lease_name already exists).
    """
    schedule_json = schedule_df.to_json()
    journal_json = journal_df.to_json()

    try:
        payload = {
            "lease_name": lease_name,
            "schedule_json": schedule_json,
            "journal_json": journal_json
        }
        # Always POST
        r = requests.post(APEX_BASE_URL, json=payload)
        r.raise_for_status()  # Will raise an exception if 4xx/5xx
    except Exception as e:
        st.warning(f"Unable to save lease '{lease_name}' via POST to APEX: {e}")

############################
# 2B. If You WANT PUT (Explicitly)
############################
def save_lease_to_apex_put(lease_name, schedule_df, journal_df):
    """
    Tries to do a GET /leasedata/{lease_name} first to see if record exists.
    If found (200), do PUT. If not found (404), do POST.
    Requires APEX to allow PUT on /leasedata/{lease_name}.
    """
    schedule_json = schedule_df.to_json()
    journal_json = journal_df.to_json()

    try:
        check_url = f"{APEX_BASE_URL}{lease_name}"
        # 1) GET to see if record exists
        check_resp = requests.get(check_url)

        payload = {
            "lease_name": lease_name,
            "schedule_json": schedule_json,
            "journal_json": journal_json
        }

        if check_resp.status_code == 200:
            # 2) Do PUT if found
            put_resp = requests.put(check_url, json=payload)
            put_resp.raise_for_status()
        elif check_resp.status_code == 404:
            # 3) If 404, do POST
            post_resp = requests.post(APEX_BASE_URL, json=payload)
            post_resp.raise_for_status()
        else:
            # Possibly 405 or something else
            st.warning(f"Unexpected status code {check_resp.status_code} from GET {check_url}. Could not upsert.")
    except Exception as e:
        st.warning(f"Unable to save lease '{lease_name}' to APEX (PUT logic): {e}")

############################
# 3. DELETE
############################
def delete_lease_in_apex(lease_name):
    """
    DELETE /leasedata/{lease_name} (assuming APEX has enabled DELETE).
    """
    try:
        del_url = f"{APEX_BASE_URL}{lease_name}"
        resp = requests.delete(del_url)
        resp.raise_for_status()
    except Exception as e:
        st.warning(f"Unable to delete lease '{lease_name}' from APEX: {e}")

############################
# 4. The rest of your code (generate_schedules, journals, portfolio reports, etc.)
############################

def generate_monthly_payments(base_payment, lease_term, annual_escalation_rate, payment_timing="end"):
    # same as your original
    ...

def present_value_of_varied_payments(payments, monthly_rate, payment_timing="end"):
    # same as your original
    ...

def generate_amortization_schedule(...):
    # same as your original
    ...

def generate_monthly_journal_entries(...):
    # same as your original
    ...

def portfolio_liab_by_period(...):
    # same as your original
    ...

def portfolio_rou_by_period(...):
    # same as your original
    ...

def get_all_journal_entries(...):
    # same as your original
    ...

############################
# 5. STREAMLIT APP
############################
def main():
    st.title("ASC 842 LEASE MODULE (Oracle APEX)")

    # Load existing leases once
    if "saved_leases" not in st.session_state:
        st.session_state["saved_leases"] = load_leases_from_apex()

    # TABS: Manage Leases, Journal Entries, Portfolio
    tab1, tab2, tab3 = st.tabs(["Manage Leases", "Journal Entries", "Portfolio Reports"])

    with tab1:
        # Single lease create
        lease_name = st.text_input("Lease Name/ID", value="My Lease")
        lease_type = st.selectbox("Lease Classification", ["Operating", "Finance"])
        start_date_val = st.date_input("Lease Start Date", value=date.today())
        lease_term = st.number_input("Lease Term (months)", min_value=1, value=36)
        annual_discount_rate = st.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
        base_payment_amount = st.number_input("Base Monthly Payment (initial year)", min_value=0.0, value=1000.0)
        annual_escalation_pct = st.number_input("Annual Payment Escalation Rate (%)", min_value=0.0, value=5.0)
        payment_timing = st.selectbox("Payment Timing", ["end", "begin"])

        # Example: Using single POST approach
        if st.button("Generate & Save (POST Only)"):
            df_schedule = generate_amortization_schedule(
                lease_term=lease_term,
                base_payment=base_payment_amount,
                annual_discount_rate=annual_discount_rate / 100.0,
                annual_escalation_rate=annual_escalation_pct / 100.0,
                start_date=start_date_val,
                payment_timing=payment_timing,
                lease_type=lease_type
            )
            df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)

            st.session_state["saved_leases"][lease_name] = {
                "schedule": df_schedule,
                "journal": df_journal
            }
            # Use the single POST approach
            save_lease_to_apex_post_only(lease_name, df_schedule, df_journal)

            st.success(f"Lease '{lease_name}' saved via POST!")
            # Reload
            st.session_state["saved_leases"] = load_leases_from_apex()

        st.write("---")
        # If you prefer the upsert with GET->PUT->POST logic, you could do:
        if st.button("Generate & Upsert (GET->PUT->POST)"):
            df_schedule = generate_amortization_schedule(...)
            df_journal = generate_monthly_journal_entries(...)

            st.session_state["saved_leases"][lease_name] = {
                "schedule": df_schedule,
                "journal": df_journal
            }
            save_lease_to_apex_put(lease_name, df_schedule, df_journal)

            st.success(f"Lease '{lease_name}' upserted with PUT if found, else POST.")
            st.session_state["saved_leases"] = load_leases_from_apex()

        st.header("View / Edit Saved Lease")
        if st.session_state["saved_leases"]:
            selected_lease = st.selectbox("Select a saved lease", list(st.session_state["saved_leases"].keys()))
            ...
            if st.button("Delete Lease"):
                delete_lease_in_apex(selected_lease)
                ...
        else:
            st.info("No leases found from APEX so far...")

    # Tab 2: Journal Entries
    # Tab 3: Portfolio Reports
    # same logic as your original

if __name__ == "__main__":
    main()
