import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
import gspread
from google.oauth2 import service_account

############################
# 1. GOOGLE SHEETS HELPERS
############################
def get_gsheet_connection():
    creds_dict = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    return client

def load_leases_from_gsheet(sheet_name="LeaseData"):
    try:
        client = get_gsheet_connection()
        sheet = client.open(sheet_name).sheet1
        data = sheet.get_all_records()

        df = pd.DataFrame(data)
        # Expecting: ["LeaseName", "SerializedSchedule", "SerializedJournal"]
        
        saved_leases = {}
        for _, row in df.iterrows():
            lease_name = row["LeaseName"]
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
    try:
        client = get_gsheet_connection()
        sheet = client.open(sheet_name).sheet1
        
        schedule_json = schedule_df.to_json()
        journal_json = journal_df.to_json()
        
        new_row = [lease_name, schedule_json, journal_json]
        sheet.append_row(new_row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.warning(f"Unable to save to Google Sheets: {e}")

def delete_lease_in_gsheet(lease_name, sheet_name="LeaseData"):
    try:
        client = get_gsheet_connection()
        sheet = client.open(sheet_name).sheet1
        records = sheet.get_all_records()
        
        for i, row in enumerate(records, start=2):
            if row.get("LeaseName") == lease_name:
                sheet.delete_rows(i)
                break
    except Exception as e:
        st.warning(f"Unable to delete lease '{lease_name}' from Google Sheets: {e}")

def update_lease_in_gsheet(lease_name, schedule_df, journal_df, sheet_name="LeaseData"):
    delete_lease_in_gsheet(lease_name, sheet_name)
    save_lease_to_gsheet(lease_name, schedule_df, journal_df, sheet_name)

############################
# 2. HELPER FUNCTIONS
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
# 3. MAIN AMORTIZATION FUNCTION
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
# 4. JOURNAL ENTRY CREATION
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
# 5. CONSOLIDATED REPORTS (PORTFOLIO-LEVEL)
############################
def portfolio_liability_rollforward(all_leases: dict):
    """
    Naive approach:
    1) Concatenate all lease schedules into one DataFrame (add a 'LeaseName' column).
    2) Group by Date (summation).
    3) Use the sum of 'Lease_Liability_Balance' as the 'Ending Liability' for that date.
    4) The 'Beginning Liability' is the prior date's 'Ending Liability' (for the entire portfolio).
    """
    # Step 1: gather all schedule rows
    frames = []
    for lease_name, data in all_leases.items():
        df = data["schedule"].copy()
        df["LeaseName"] = lease_name
        frames.append(df)
    if not frames:
        return pd.DataFrame()  # No data
    
    big_df = pd.concat(frames, ignore_index=True)
    
    # Step 2: group by Date
    # Summation of Payment, Interest_Expense, Principal, ROU_Asset_Amortization
    # For Liability_Balance, we'll treat it as the "Ending Liability" for that lease
    # We'll sum across leases for a total "Ending Liability"
    group_cols = ["Date"]
    sum_cols = ["Payment", "Interest_Expense", "Principal", "Lease_Liability_Balance"]
    grouped = big_df.groupby(group_cols)[sum_cols].sum().reset_index()
    grouped = grouped.sort_values(by="Date")
    
    # Step 3: For each date in ascending order, "Ending Liability" is sum(Lease_Liability_Balance).
    # We'll rename "Lease_Liability_Balance" -> "Ending Liability"
    grouped.rename(columns={"Lease_Liability_Balance": "Ending Liability"}, inplace=True)
    
    # Step 4: Compute Beginning Liability = previous row's "Ending Liability"
    # For the first row, we have no prior row, so we can set it to the same or 0
    beginning_liabilities = []
    prev_ending = 0.0
    for i, row in grouped.iterrows():
        beginning_liabilities.append(prev_ending)
        prev_ending = row["Ending Liability"]
    grouped.insert(1, "Beginning Liability", beginning_liabilities)
    
    # Tidy columns
    # 'Payment', 'Interest_Expense', 'Principal' are totals across leases for that date
    grouped.rename(columns={
        "Payment": "Total Payment",
        "Interest_Expense": "Total Interest",
        "Principal": "Total Principal"
    }, inplace=True)
    
    return grouped

def portfolio_rou_asset_rollforward(all_leases: dict):
    """
    Similar naive approach:
    1) Gather all schedules, sum 'ROU_Asset_Balance' each date as total "Ending ROU Asset".
    2) Summation of 'ROU_Asset_Amortization' as total "Amortization".
    3) 'Beginning ROU' is prior date's "Ending ROU".
    """
    frames = []
    for lease_name, data in all_leases.items():
        df = data["schedule"].copy()
        df["LeaseName"] = lease_name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    
    big_df = pd.concat(frames, ignore_index=True)
    sum_cols = ["ROU_Asset_Amortization", "ROU_Asset_Balance"]
    
    grouped = big_df.groupby(["Date"])[sum_cols].sum().reset_index()
    grouped = grouped.sort_values(by="Date")
    
    # rename columns
    grouped.rename(columns={
        "ROU_Asset_Amortization": "Total Amortization",
        "ROU_Asset_Balance": "Ending ROU Asset"
    }, inplace=True)
    
    # compute "Beginning ROU Asset"
    beginnings = []
    prev_ending = 0.0
    for i, row in grouped.iterrows():
        beginnings.append(prev_ending)
        prev_ending = row["Ending ROU Asset"]
    grouped.insert(1, "Beginning ROU Asset", beginnings)
    
    return grouped


############################
# 6. STREAMLIT APP (TABS)
############################
def main():
    st.title("ASC 842 LEASE MODULE")

    # Load existing leases on first run
    if "saved_leases" not in st.session_state:
        st.session_state["saved_leases"] = load_leases_from_gsheet(sheet_name="LeaseData")

    # Create two tabs: "Manage Leases" and "Portfolio Reports"
    tab1, tab2 = st.tabs(["Manage Leases", "Portfolio Reports"])

    with tab1:
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

        # Generate & Save new lease
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
            
            st.session_state["saved_leases"][lease_name] = {
                "schedule": df_schedule,
                "journal": df_journal
            }
            save_lease_to_gsheet(lease_name, df_schedule, df_journal, sheet_name="LeaseData")
            
            st.success(f"Lease schedule for '{lease_name}' generated and saved!")
            # Refresh from GSheets
            st.session_state["saved_leases"] = load_leases_from_gsheet(sheet_name="LeaseData")

        st.write("---")
        st.header("View / Edit Saved Lease")

        saved_lease_names = list(st.session_state["saved_leases"].keys())
        if saved_lease_names:
            selected_lease = st.selectbox("Select a saved lease to view:", options=saved_lease_names)
            if selected_lease:
                df_schedule = st.session_state["saved_leases"][selected_lease]["schedule"]
                df_journal = st.session_state["saved_leases"][selected_lease]["journal"]

                # Display schedule
                st.subheader(f"Lease Amortization Schedule: {selected_lease}")
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

                # Display journal
                st.subheader(f"Monthly Journal Entries: {selected_lease}")
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

                st.write("---")
                st.subheader("Manage This Lease Record")
                col1, col2 = st.columns([1,1])
                with col1:
                    if st.button("Delete Lease"):
                        delete_lease_in_gsheet(selected_lease, sheet_name="LeaseData")
                        del st.session_state["saved_leases"][selected_lease]
                        st.success(f"Deleted lease '{selected_lease}'!")
                        # Reload
                        st.session_state["saved_leases"] = load_leases_from_gsheet(sheet_name="LeaseData")
                with col2:
                    if st.button("Overwrite with Current Inputs"):
                        updated_schedule = generate_amortization_schedule(
                            lease_term=lease_term,
                            base_payment=base_payment_amount,
                            annual_discount_rate=annual_discount_rate / 100.0,
                            annual_escalation_rate=annual_escalation_pct / 100.0,
                            start_date=start_date,
                            payment_timing=payment_timing,
                            lease_type=lease_type
                        )
                        updated_journal = generate_monthly_journal_entries(updated_schedule, lease_type=lease_type)
                        
                        update_lease_in_gsheet(selected_lease, updated_schedule, updated_journal, sheet_name="LeaseData")
                        
                        st.session_state["saved_leases"][selected_lease] = {
                            "schedule": updated_schedule,
                            "journal": updated_journal
                        }
                        st.success(f"Lease '{selected_lease}' updated with current sidebar inputs!")
                        st.session_state["saved_leases"] = load_leases_from_gsheet(sheet_name="LeaseData")
        else:
            st.info("No leases saved yet. Generate a lease schedule to save and display it here.")

    with tab2:
        st.header("Portfolio-Level Reports")

        # If no leases saved, show message
        if not st.session_state["saved_leases"]:
            st.info("No lease records found. Go to 'Manage Leases' tab to add some!")
        else:
            st.subheader("Consolidated Liability Rollforward")
            df_port_liab = portfolio_liability_rollforward(st.session_state["saved_leases"])
            if df_port_liab.empty:
                st.write("No schedules found or no data to summarize.")
            else:
                st.dataframe(
                    df_port_liab.style.format({
                        "Beginning Liability": "{:,.2f}",
                        "Total Payment": "{:,.2f}",
                        "Total Interest": "{:,.2f}",
                        "Total Principal": "{:,.2f}",
                        "Ending Liability": "{:,.2f}"
                    })
                )
                csv_liab = df_port_liab.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Portfolio Liability Rollforward (CSV)",
                    data=csv_liab,
                    file_name="portfolio_liability_rollforward.csv",
                    mime="text/csv"
                )
            
            st.subheader("Consolidated ROU Asset Rollforward")
            df_port_rou = portfolio_rou_asset_rollforward(st.session_state["saved_leases"])
            if df_port_rou.empty:
                st.write("No schedules found or no data to summarize.")
            else:
                st.dataframe(
                    df_port_rou.style.format({
                        "Beginning ROU Asset": "{:,.2f}",
                        "Total Amortization": "{:,.2f}",
                        "Ending ROU Asset": "{:,.2f}"
                    })
                )
                csv_rou = df_port_rou.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Portfolio ROU Asset Rollforward (CSV)",
                    data=csv_rou,
                    file_name="portfolio_rou_asset_rollforward.csv",
                    mime="text/csv"
                )

if __name__ == "__main__":
    main()


