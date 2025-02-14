import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
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
    # Helper: delete + re-append
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
# 5. CONSOLIDATED REPORTS (PORTFOLIO-LEVEL), GROUP BY "PERIOD"
############################
def portfolio_liab_by_period(all_leases: dict, start_date: date, end_date: date):
    frames = []
    for lease_name, data in all_leases.items():
        df = data["schedule"].copy()
        df["LeaseName"] = lease_name
        frames.append(df)
    
    if not frames:
        return pd.DataFrame()  # no data at all
    
    big_df = pd.concat(frames, ignore_index=True)
    
    mask = (big_df["Date"] >= pd.to_datetime(start_date)) & (big_df["Date"] <= pd.to_datetime(end_date))
    big_df = big_df[mask]
    
    if big_df.empty:
        return pd.DataFrame()  # no rows in that date range
    
    sum_cols = ["Payment", "Interest_Expense", "Principal", "Lease_Liability_Balance"]
    grouped = big_df.groupby("Period")[sum_cols].sum().reset_index()
    grouped = grouped.sort_values("Period")
    
    grouped.rename(columns={
        "Payment": "Total Payment",
        "Interest_Expense": "Total Interest",
        "Principal": "Total Principal",
        "Lease_Liability_Balance": "Ending Liability"
    }, inplace=True)
    
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
    grouped = big_df.groupby("Period")[sum_cols].sum().reset_index()
    grouped = grouped.sort_values("Period")
    
    grouped.rename(columns={
        "ROU_Asset_Amortization": "Total Amortization",
        "ROU_Asset_Balance": "Ending ROU Asset"
    }, inplace=True)
    
    beginnings = []
    prev_end = 0.0
    for i, row in grouped.iterrows():
        beginnings.append(prev_end)
        prev_end = row["Ending ROU Asset"]
    grouped.insert(1, "Beginning ROU Asset", beginnings)
    
    return grouped

############################
# 6. CONSOLIDATED JOURNAL VIEW
############################
def get_all_journal_entries(saved_leases: dict) -> pd.DataFrame:
    frames = []
    for lease_name, data in saved_leases.items():
        df_journal = data["journal"].copy()
        df_journal["LeaseName"] = lease_name
        frames.append(df_journal)
    if not frames:
        return pd.DataFrame()
    big_df = pd.concat(frames, ignore_index=True)
    big_df.sort_values(by=["Date", "LeaseName"], inplace=True)
    return big_df

############################
# 7. STREAMLIT APP (THREE TABS)
############################
def main():
    st.title("ASC 842 LEASE MODULE")

    # Load existing leases from Google Sheets on first run
    if "saved_leases" not in st.session_state:
        st.session_state["saved_leases"] = load_leases_from_gsheet("LeaseData")

    # Create tabs
    tab1, tab2, tab3 = st.tabs(["Manage Leases", "Journal Entries", "Portfolio Reports"])

    # --- TAB 1: Manage Leases ---
    with tab1:
        # === Sidebar for Single Lease + Mass Upload ===
        with st.sidebar:
            st.header("Add/Update Single Lease")
            lease_name = st.text_input("Lease Name/ID", value="My Lease")
            lease_type = st.selectbox("Lease Classification", ["Operating", "Finance"])
            start_date_input = st.date_input("Lease Start Date", value=date.today())
            lease_term = st.number_input("Lease Term (months)", min_value=1, value=36)
            annual_discount_rate = st.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
            base_payment_amount = st.number_input("Base Monthly Payment (initial year)",
                                                  min_value=0.0,
                                                  value=1000.0)
            annual_escalation_pct = st.number_input("Annual Payment Escalation Rate (%)",
                                                    min_value=0.0,
                                                    value=5.0)
            payment_timing = st.selectbox("Payment Timing", ["end", "begin"])

            if st.button("Generate & Save Lease Schedule"):
                df_schedule = generate_amortization_schedule(
                    lease_term=lease_term,
                    base_payment=base_payment_amount,
                    annual_discount_rate=annual_discount_rate / 100.0,
                    annual_escalation_rate=annual_escalation_pct / 100.0,
                    start_date=start_date_input,
                    payment_timing=payment_timing,
                    lease_type=lease_type
                )
                df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)
                
                # Save locally
                st.session_state["saved_leases"][lease_name] = {
                    "schedule": df_schedule,
                    "journal": df_journal
                }
                # Save to Google Sheets
                save_lease_to_gsheet(lease_name, df_schedule, df_journal, "LeaseData")
                
                st.success(f"Lease schedule for '{lease_name}' generated and saved!")
                st.session_state["saved_leases"] = load_leases_from_gsheet("LeaseData")

            st.write("---")
            st.header("Mass Upload Leases via CSV")
            st.markdown("""
            **CSV Format** (one lease per row). Required columns:
            - `LeaseName`
            - `LeaseType` (Operating or Finance)
            - `StartDate` (YYYY-MM-DD)
            - `LeaseTerm` (integer, months)
            - `DiscountRate` (annual %)
            - `BasePayment` (float)
            - `EscalationRate` (annual %)
            - `PaymentTiming` ("end" or "begin")
            """)
            uploaded_file = st.file_uploader("Upload CSV for multiple leases", type=["csv"])
            if uploaded_file is not None:
                if st.button("Process CSV"):
                    df_csv = pd.read_csv(uploaded_file)
                    required_cols = ["LeaseName", "LeaseType", "StartDate", "LeaseTerm",
                                     "DiscountRate", "BasePayment", "EscalationRate", "PaymentTiming"]
                    missing = [c for c in required_cols if c not in df_csv.columns]
                    if missing:
                        st.error(f"Missing columns: {missing}. Please fix CSV.")
                    else:
                        success_count = 0
                        error_count = 0
                        for idx, row in df_csv.iterrows():
                            try:
                                ln = str(row["LeaseName"]).strip()
                                lt = str(row["LeaseType"]).strip()
                                sd = pd.to_datetime(row["StartDate"]).date()
                                term = int(row["LeaseTerm"])
                                dr = float(row["DiscountRate"])/100.0
                                bp = float(row["BasePayment"])
                                esc = float(row["EscalationRate"])/100.0
                                pt = str(row["PaymentTiming"]).lower()
                                
                                schedule = generate_amortization_schedule(
                                    lease_term=term,
                                    base_payment=bp,
                                    annual_discount_rate=dr,
                                    annual_escalation_rate=esc,
                                    start_date=sd,
                                    payment_timing=pt,
                                    lease_type=lt
                                )
                                journal = generate_monthly_journal_entries(schedule, lease_type=lt)

                                st.session_state["saved_leases"][ln] = {
                                    "schedule": schedule,
                                    "journal": journal
                                }
                                save_lease_to_gsheet(ln, schedule, journal, "LeaseData")
                                
                                success_count += 1
                            except Exception as ex:
                                st.warning(f"Row {idx} failed: {ex}")
                                error_count += 1
                        st.success(f"CSV processed! {success_count} leases uploaded, {error_count} errors.")
                        st.session_state["saved_leases"] = load_leases_from_gsheet("LeaseData")

        # === Main area: "View / Edit Saved Lease" ===
        st.subheader("View / Edit Saved Lease")

        saved_lease_names = list(st.session_state["saved_leases"].keys())
        if saved_lease_names:
            selected_lease = st.selectbox("Select a saved lease to view:", options=saved_lease_names)
            if selected_lease:
                data = st.session_state["saved_leases"][selected_lease]
                df_schedule = data["schedule"]

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

                st.write("---")
                st.subheader("Manage This Lease Record")
                col1, col2 = st.columns([1,1])
                with col1:
                    if st.button("Delete Lease"):
                        delete_lease_in_gsheet(selected_lease, "LeaseData")
                        del st.session_state["saved_leases"][selected_lease]
                        st.success(f"Deleted lease '{selected_lease}'!")
                        st.session_state["saved_leases"] = load_leases_from_gsheet("LeaseData")
                with col2:
                    if st.button("Overwrite with Current Sidebar Inputs"):
                        # We'll use the same sidebar input fields
                        updated_schedule = generate_amortization_schedule(
                            lease_term=lease_term,
                            base_payment=base_payment_amount,
                            annual_discount_rate=annual_discount_rate / 100.0,
                            annual_escalation_rate=annual_escalation_pct / 100.0,
                            start_date=start_date_input,
                            payment_timing=payment_timing,
                            lease_type=lease_type
                        )
                        updated_journal = generate_monthly_journal_entries(updated_schedule, lease_type=lease_type)
                        
                        update_lease_in_gsheet(selected_lease, updated_schedule, updated_journal, "LeaseData")
                        
                        st.session_state["saved_leases"][selected_lease] = {
                            "schedule": updated_schedule,
                            "journal": updated_journal
                        }
                        st.success(f"Lease '{selected_lease}' updated with current sidebar inputs!")
                        st.session_state["saved_leases"] = load_leases_from_gsheet("LeaseData")
        else:
            st.info("No leases saved yet. Create or upload some in the sidebar to display them here.")

    # --- TAB 2: Journal Entries ---
    with tab2:
        st.header("Journal Entries")
        if not st.session_state["saved_leases"]:
            st.info("No lease records found. Go to 'Manage Leases' tab to add some!")
        else:
            # Combine all journal entries
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
                    df_show.style.format({
                        "Debit": "{:,.2f}",
                        "Credit": "{:,.2f}"
                    })
                )
                
                csv_journals = df_show.to_csv(index=False).encode('utf-8')
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
            st.info("No lease records found. Go to 'Manage Leases' tab to add some!")
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
