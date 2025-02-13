import streamlit as st 
import pandas as pd
import numpy as np
from datetime import date

############################
# 1. HELPER FUNCTIONS
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
# 2. MAIN AMORTIZATION FUNCTION
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
    monthly_payments = generate_monthly_payments(base_payment, lease_term, annual_escalation_rate, payment_timing)
    
    monthly_rate = annual_discount_rate / 12.0
    lease_liability = present_value_of_varied_payments(monthly_payments, monthly_rate, payment_timing)
    rou_asset = lease_liability

    # For Operating leases, compute a single monthly expense across entire term
    operating_lease_monthly_expense = None
    if lease_type == "Operating":
        operating_lease_monthly_expense = sum(monthly_payments) / lease_term

    schedule_rows = []
    liability_balance = lease_liability

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
            # The total monthly lease expense is a single amount
            operating_lease_expense = operating_lease_monthly_expense
            rou_amortization = operating_lease_expense - interest_expense
            rou_asset -= rou_amortization
        else:
            # Finance lease: ROU asset amort is typically straight line over the term
            rou_amortization = rou_asset / lease_term
            operating_lease_expense = None  # Not used for Finance leases

        schedule_rows.append({
            "Period": period,
            "Date": pd.to_datetime(start_date) + pd.DateOffset(months=period - 1),
            "Payment": current_payment,
            "Interest_Expense": interest_expense,
            "Principal": principal,
            "Lease_Liability_Balance": new_liability_balance,
            "ROU_Asset_Amortization": rou_amortization,
            "ROU_Asset_Balance": max(rou_asset, 0),
            # NEW COLUMN: Show monthly Op Lease Expense if Operating; None if Finance
            "Operating_Lease_Expense": operating_lease_expense
        })
        
        liability_balance = new_liability_balance
    
    return pd.DataFrame(schedule_rows)

############################
# 3. JOURNAL ENTRY CREATION
############################
def generate_monthly_journal_entries(schedule_df, lease_type="Operating"):
    ...
    # (Unchanged from your original - omit for brevity)
    ...

############################
# 4. STREAMLIT APP
############################
def main():
    st.title("ASC 842 LEASE MODULE")
    
    st.sidebar.header("Lease Inputs")
    lease_type = st.sidebar.selectbox("Lease Classification", ["Operating", "Finance"])
    start_date = st.sidebar.date_input("Lease Start Date", value=date.today())
    
    lease_term = st.sidebar.number_input("Lease Term (months)", min_value=1, value=36)
    annual_discount_rate = st.sidebar.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
    
    base_payment_amount = st.sidebar.number_input("Base Monthly Payment (initial year)", min_value=0.0, value=1000.0)
    annual_escalation_pct = st.sidebar.number_input("Annual Payment Escalation Rate (%)", min_value=0.0, value=5.0)
    
    payment_timing = st.sidebar.selectbox("Payment Timing", ["end", "begin"])
    
    if st.sidebar.button("Generate Schedule"):
        df_schedule = generate_amortization_schedule(
            lease_term=lease_term,
            base_payment=base_payment_amount,
            annual_discount_rate=annual_discount_rate / 100.0,  # convert % to decimal
            annual_escalation_rate=annual_escalation_pct / 100.0, 
            start_date=start_date,
            payment_timing=payment_timing,
            lease_type=lease_type
        )
        
        st.subheader("Lease Amortization Schedule")
        if lease_type == "Operating":
            # Show the Operating_Lease_Expense column in a nice format
            format_dict = {
                "Payment": "{:,.2f}",
                "Interest_Expense": "{:,.2f}",
                "Principal": "{:,.2f}",
                "Lease_Liability_Balance": "{:,.2f}",
                "ROU_Asset_Amortization": "{:,.2f}",
                "ROU_Asset_Balance": "{:,.2f}",
                "Operating_Lease_Expense": "{:,.2f}"
            }
        else:
            # For Finance leases, Operating_Lease_Expense is None, so no need to format it
            format_dict = {
                "Payment": "{:,.2f}",
                "Interest_Expense": "{:,.2f}",
                "Principal": "{:,.2f}",
                "Lease_Liability_Balance": "{:,.2f}",
                "ROU_Asset_Amortization": "{:,.2f}",
                "ROU_Asset_Balance": "{:,.2f}"
            }

        st.dataframe(df_schedule.style.format(format_dict))
        
        csv_schedule = df_schedule.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Amortization Schedule (CSV)",
            data=csv_schedule,
            file_name="variable_lease_amortization_schedule.csv",
            mime="text/csv"
        )
        
        # Journal entries
        df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)
        st.subheader("Monthly Journal Entries")
        st.dataframe(
            df_journal.style.format({"Debit": "{:,.2f}", "Credit": "{:,.2f}"})
        )
        csv_journal = df_journal.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Journal Entries (CSV)",
            data=csv_journal,
            file_name="monthly_journal_entries.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()


