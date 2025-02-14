import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
import requests  # For REST calls to Oracle APEX

############################
# 1. ORACLE APEX CONFIG
############################
APEX_BASE_URL = "https://g382f1e4d487358-taxproprototype.adb.us-phoenix-1.oraclecloudapps.com/ords/txp/leasedata/"

def load_leases_from_apex():
    """
    Reads existing rows from Oracle APEX REST endpoint and reconstructs
    your saved lease data: { leaseName: {"schedule": df, "journal": df}, ... }
    Expects APEX to return JSON like:
      {
        "items": [
          {
            "lease_name": "MyLease",
            "schedule_json": "...",
            "journal_json": "..."
          },
          ...
        ],
        ...
      }
    """
    saved_leases = {}
    try:
        resp = requests.get(APEX_BASE_URL)  # e.g. GET /leasedata/
        resp.raise_for_status()
        data = resp.json()

        # 'items' is where ORDS typically puts rows
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

def save_lease_to_apex(lease_name, schedule_df, journal_df):
    """
    Upserts a single lease record to Oracle APEX by:
    1) Checking if GET /leasedata/{lease_name} is found
    2) If found: do a PUT to update
    3) If not found: do a POST to insert
    Body JSON = { "lease_name": "...", "schedule_json": "...", "journal_json": "..." }
    """
    # Convert DataFrames to JSON strings
    schedule_json = schedule_df.to_json()
    journal_json = journal_df.to_json()

    try:
        # 1) Attempt GET /leasedata/{lease_name}
        check_url = f"{APEX_BASE_URL}{lease_name}"
        check_resp = requests.get(check_url)
        # We'll do a naive check: if 200 => it exists
        if check_resp.status_code == 200:
            # 2) Do a PUT to update
            put_payload = {
                "lease_name": lease_name,
                "schedule_json": schedule_json,
                "journal_json": journal_json
            }
            put_resp = requests.put(check_url, json=put_payload)
            put_resp.raise_for_status()
        else:
            # 3) Do a POST to create a new record
            post_payload = {
                "lease_name": lease_name,
                "schedule_json": schedule_json,
                "journal_json": journal_json
            }
            post_resp = requests.post(APEX_BASE_URL, json=post_payload)
            post_resp.raise_for_status()
    except Exception as e:
        st.warning(f"Unable to save lease '{lease_name}' to APEX: {e}")

def delete_lease_in_apex(lease_name):
    """
    Deletes a single lease record from APEX by calling
    DELETE /leasedata/{lease_name}
    """
    try:
        del_url = f"{APEX_BASE_URL}{lease_name}"
        resp = requests.delete(del_url)
        resp.raise_for_status()
    except Exception as e:
        st.warning(f"Unable to delete lease '{lease_name}' from APEX: {e}")


############################
# 2. HELPER FUNCTIONS (Same as your original code)
############################

def generate_monthly_payments(base_payment, lease_term, annual_escalation_rate, payment_timing="end"):
    payments = []
    for month in range(1, lease_term + 1):
        years_elapsed = (month - 1) // 12
        payment_for_month = base_payment * (1 + annual_escalation_rate) ** years_elapsed
        payments.append(payment_for_month)
    return payments

def present_value_of_varied_payments(payments, monthly_rate, payment_timing="end"):
    pv = 0.0
    for i, pmt in enumerate(payments, start=1):
        if payment_timing == "end":
            pv += pmt / ((1 + monthly_rate) ** i)
        else:
            pv += pmt / ((1 + monthly_rate) ** (i - 1))
    return pv

############################
# 3. MAIN AMORTIZATION FUNCTION (Same as original)
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
            total_lease_expense = sum(monthly_payments) / lease_term
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
# 4. JOURNAL ENTRY CREATION (Same as original)
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
# 5. PORTFOLIO & JOURNAL CONSOLIDATION
############################

def portfolio_liab_by_period(all_leases: dict, start_date: date, end_date: date):
    frames = []
    for lease_name, data in all_leases.items():
        df = data["schedule"].copy()
        df["LeaseName"] = lease_name
        frames.append(df)
    
    if not frames:
        return pd.DataFrame()  # no data
    
    big_df = pd.concat(frames, ignore_index=True)
    mask = (big_df["Date"] >= pd.to_datetime(start_date)) & (big_df["Date"] <= pd.to_datetime(end_date))
    big_df = big_df[mask]
    
    if big_df.empty:
        return pd.DataFrame()
    
    sum_cols = ["Payment", "Interest_Expense", "Principal", "Lease_Liability_Balance"]
    grouped = big_df.groupby("Period")[sum_cols].sum().reset_index().sort_values("Period")

    grouped.rename(columns={
        "Payment": "Total Payment",
        "Interest_Expense": "Total Interest",
        "Principal": "Total Principal",
        "Lease_Liability_Balance": "Ending Liability"
    }, inplace=True)
    
    # Compute "Beginning Liability"
    beginning_liabilities = []
    prev_end = 0.0
    for i, row in grouped.iterrows():
        beginning_liabilities.append(prev_end)
        prev_end = row["Ending Liability"]
    grouped.insert(1, "Beginning Liability", beginning_liabilities)
    
    return grouped

def portfolio_rou_by_period(all_leases: dict, start_date: date, end_date: date):
    frames = []
    for lease_name, data in all_leases.items():
        df = data["schedule"].copy()
        df["LeaseName"] = lease_name
        frames.append(df)
    
    if not frames:
        return pd.DataFrame()
    
    big_df = pd.concat(frames, ignore_index=True)
    mask = (big_df["Date"] >= pd.to_datetime(start_date)) & (big_df["Date"] <= pd.to_datetime(end_date))
    big_df = big_df[mask]
    
    if big_df.empty:
        return pd.DataFrame()
    
    sum_cols = ["ROU_Asset_Amortization", "ROU_Asset_Balance"]
    grouped = big_df.groupby("Period")[sum_cols].sum().reset_index().sort_values("Period")

    grouped.rename(columns={
        "ROU_Asset_Amortization": "Total Amortization",
        "ROU_Asset_Balance": "Ending ROU Asset"
    }, inplace=True)
    
    # Compute "Beginning ROU Asset"
    beginnings = []
    prev_end = 0.0
    for i, row in grouped.iterrows():
        beginnings.append(prev_end)
        prev_end = row["Ending ROU Asset"]
    grouped.insert(1, "Beginning ROU Asset", beginnings)
    
    return grouped

def get_all_journal_entries(saved_leases: dict) -> pd.DataFrame:
    frames = []
    for lease_name, data in saved_leases.items():
        jdf = data["journal"].copy()
        jdf["LeaseName"] = lease_name
        frames.append(jdf)
    if not frames:
        return pd.DataFrame()
    big_df = pd.concat(frames, ignore_index=True)
    big_df.sort_values(by=["Date", "LeaseName"], inplace=True)
    return big_df

############################
# 6. STREAMLIT APP
############################
def main():
    st.title("ASC 842 LEASE MODULE (Using Oracle APEX)")

    # 1) Initialize session_state with leases from APEX
    if "saved_leases" not in st.session_state:
        st.session_state["saved_leases"] = load_leases_from_apex()

    # TABS
    tab1, tab2, tab3 = st.tabs(["Manage Leases", "Journal Entries", "Portfolio Reports"])

    # --- TAB 1: Manage Leases ---
    with tab1:
        st.subheader("Add/Update Single Lease")
        lease_name = st.text_input("Lease Name/ID", value="My Lease")
        lease_type = st.selectbox("Lease Classification", ["Operating", "Finance"])
        start_date_val = st.date_input("Lease Start Date", value=date.today())
        lease_term = st.number_input("Lease Term (months)", min_value=1, value=36)
        annual_discount_rate = st.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
        base_payment_amount = st.number_input("Base Monthly Payment (initial year)", min_value=0.0, value=1000.0)
        annual_escalation_pct = st.number_input("Annual Payment Escalation Rate (%)", min_value=0.0, value=5.0)
        payment_timing = st.selectbox("Payment Timing", ["end", "begin"])

        if st.button("Generate & Save Lease Schedule"):
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
            
            # Save in session
            st.session_state["saved_leases"][lease_name] = {
                "schedule": df_schedule,
                "journal": df_journal
            }
            # Save to APEX
            save_lease_to_apex(lease_name, df_schedule, df_journal)
            
            st.success(f"Lease schedule for '{lease_name}' generated and saved!")
            # Reload from APEX
            st.session_state["saved_leases"] = load_leases_from_apex()

        st.write("---")
        st.subheader("View / Edit Saved Lease")
        saved_lease_names = list(st.session_state["saved_leases"].keys())
        if saved_lease_names:
            selected_lease = st.selectbox("Select a saved lease to view:", options=saved_lease_names)
            if selected_lease:
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
                csv_schedule = df_schedule.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Amortization Schedule (CSV)",
                    data=csv_schedule,
                    file_name=f"{selected_lease}_amortization_schedule.csv",
                    mime="text/csv"
                )

                st.write("---")
                st.subheader("Manage This Lease Record")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Delete Lease"):
                        delete_lease_in_apex(selected_lease)
                        del st.session_state["saved_leases"][selected_lease]
                        st.success(f"Deleted lease '{selected_lease}'!")
                        st.session_state["saved_leases"] = load_leases_from_apex()
                with col2:
                    if st.button("Overwrite with Current Inputs"):
                        updated_schedule = generate_amortization_schedule(
                            lease_term=lease_term,
                            base_payment=base_payment_amount,
                            annual_discount_rate=annual_discount_rate / 100.0,
                            annual_escalation_rate=annual_escalation_pct / 100.0,
                            start_date=start_date_val,
                            payment_timing=payment_timing,
                            lease_type=lease_type
                        )
                        updated_journal = generate_monthly_journal_entries(updated_schedule, lease_type=lease_type)
                        
                        # Upsert in APEX
                        save_lease_to_apex(selected_lease, updated_schedule, updated_journal)
                        
                        st.session_state["saved_leases"][selected_lease] = {
                            "schedule": updated_schedule,
                            "journal": updated_journal
                        }
                        st.success(f"Lease '{selected_lease}' updated with current sidebar inputs!")
                        st.session_state["saved_leases"] = load_leases_from_apex()
        else:
            st.info("No leases saved yet. Generate one above or import them via some other method.")

    # --- TAB 2: Journal Entries ---
    with tab2:
        st.header("Journal Entries")
        if not st.session_state["saved_leases"]:
            st.info("No lease records found.")
        else:
            df_all_journals = get_all_journal_entries(st.session_state["saved_leases"])
            if df_all_journals.empty:
                st.info("No journal entries yet.")
            else:
                lease_choices = ["All Leases"] + list(st.session_state["saved_leases"].keys())
                selected_journal_lease = st.selectbox("Choose Lease for Journal Entries:", options=lease_choices)
                if selected_journal_lease == "All Leases":
                    df_show = df_all_journals
                else:
                    df_show = df_all_journals[df_all_journals["LeaseName"] == selected_journal_lease]

                st.dataframe(
                    df_show.style.format({"Debit": "{:,.2f}", "Credit": "{:,.2f}"})
                )
                csv_journals = df_show.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Journal Entries (CSV)",
                    data=csv_journals,
                    file_name="journal_entries.csv",
                    mime="text/csv"
                )

    # --- TAB 3: Portfolio Reports ---
    with tab3:
        st.header("Portfolio-Level Reports (By Period)")
        if not st.session_state["saved_leases"]:
            st.info("No lease records found.")
        else:
            st.write("Use the date range to filter which periods/dates are included in the sum.")
            report_start = st.date_input("Report Start Date", value=date.today() - timedelta(days=365))
            report_end = st.date_input("Report End Date", value=date.today() + timedelta(days=365))

            st.subheader("Consolidated Liability (Period-Level)")
            df_liab = portfolio_liab_by_period(st.session_state["saved_leases"], report_start, report_end)
            if df_liab.empty:
                st.write("No data in the selected date range.")
            else:
                st.dataframe(
                    df_liab.style.format({
                        "Beginning Liability": "{:,.2f}",
                        "Total Payment": "{:,.2f}",
                        "Total Interest": "{:,.2f}",
                        "Total Principal": "{:,.2f}",
                        "Ending Liability": "{:,.2f}"
                    })
                )
                csv_liab = df_liab.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Portfolio Liability Rollforward (CSV)",
                    data=csv_liab,
                    file_name="portfolio_liability_rollforward_by_period.csv",
                    mime="text/csv"
                )

            st.subheader("Consolidated ROU Asset (Period-Level)")
            df_rou = portfolio_rou_by_period(st.session_state["saved_leases"], report_start, report_end)
            if df_rou.empty:
                st.write("No data in the selected date range.")
            else:
                st.dataframe(
                    df_rou.style.format({
                        "Beginning ROU Asset": "{:,.2f}",
                        "Total Amortization": "{:,.2f}",
                        "Ending ROU Asset": "{:,.2f}"
                    })
                )
                csv_rou = df_rou.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Portfolio ROU Asset Rollforward (CSV)",
                    data=csv_rou,
                    file_name="portfolio_rou_asset_rollforward_by_period.csv",
                    mime="text/csv"
                )

if __name__ == "__main__":
    main()
