import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

############################
# 1. HELPER FUNCTIONS
############################
def generate_monthly_payments(
    base_payment: float,
    lease_term: int,
    annual_escalation_rate: float,
    payment_timing: str = "end"
):
    """
    Generate a list of monthly payments, applying
    an annual escalation once per year.
    
    :param base_payment: The initial monthly payment
    :param lease_term: Total number of months
    :param annual_escalation_rate: e.g., 0.05 for 5% each year
    :param payment_timing: 'end' or 'begin' (used for reference if needed)
    :return: List of monthly payment amounts
    """
    monthly_payments = []
    
    for month in range(1, lease_term + 1):
        # Figure out how many "full years" have passed:
        # (month-1)//12 is 0 for months 1-12, 1 for months 13-24, etc.
        years_elapsed = (month - 1) // 12
        # Payment escalates by (1 + annual_escalation_rate)^years_elapsed
        payment_for_month = base_payment * (1 + annual_escalation_rate) ** years_elapsed
        monthly_payments.append(payment_for_month)
    
    return monthly_payments

def present_value_of_varied_payments(
    payments: list[float],
    monthly_rate: float,
    payment_timing: str = "end"
):
    """
    Compute the present value of a list of payments,
    discounted at 'monthly_rate'.

    :param payments: List of monthly payments
    :param monthly_rate: Discount rate per month (annual_rate / 12)
    :param payment_timing: 'end' (ordinary annuity) or 'begin' (annuity due)
    :return: Present value of all payments
    """
    pv = 0.0
    for i, pmt in enumerate(payments, start=1):
        if payment_timing == "end":
            # Payment in arrears: discount by i periods
            pv += pmt / ((1 + monthly_rate) ** i)
        else:
            # Payment in advance: discount by (i-1) periods
            pv += pmt / ((1 + monthly_rate) ** (i - 1))
    return pv

############################
# 2. MAIN AMORTIZATION FUNCTION
############################
def generate_amortization_schedule(
    lease_term: int,
    base_payment: float,
    annual_discount_rate: float,
    annual_escalation_rate: float,
    start_date: date,
    payment_timing: str = "end",
    lease_type: str = "Operating"
):
    """
    Create a monthly amortization schedule for an ASC 842 lease
    with annual payment escalations.
    """
    # 1) Generate the monthly payments array, including escalation
    monthly_payments = generate_monthly_payments(
        base_payment, lease_term, annual_escalation_rate, payment_timing
    )
    
    # 2) Calculate the initial lease liability (present value)
    monthly_rate = annual_discount_rate / 12.0
    lease_liability = present_value_of_varied_payments(
        monthly_payments, monthly_rate, payment_timing
    )
    
    # Assume initial ROU Asset = lease liability (no prepayments, etc.)
    rou_asset = lease_liability
    
    # We'll iterate month by month using the effective-interest approach
    schedule_rows = []
    liability_balance = lease_liability
    
    for period in range(1, lease_term + 1):
        current_payment = monthly_payments[period - 1]
        
        # Calculate interest for the period
        interest_expense = liability_balance * monthly_rate
        
        if payment_timing == "end":
            # Payment made at period end => principal portion after interest
            principal = current_payment - interest_expense
        else:
            # Payment made at period begin => reduce liability first
            principal = current_payment
            interest_expense = (liability_balance - principal) * monthly_rate
        
        new_liability_balance = liability_balance - principal
        
        # Operating vs. Finance lease differences
        if lease_type == "Operating":
            # Straight-line expense each month
            total_lease_expense = sum(monthly_payments) / lease_term
            # ROU amortization is the difference between total expense and interest
            rou_amortization = total_lease_expense - interest_expense
            # Adjust ROU asset
            rou_asset -= rou_amortization
        else:
            # Finance lease => typically ROU amort is straight-line over the lease term
            rou_amortization = rou_asset / lease_term
        
        # Prepare row for the schedule
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
        
        # Update running balance
        liability_balance = new_liability_balance
    
    return pd.DataFrame(schedule_rows)

############################
# 3. JOURNAL ENTRY CREATION
############################
def generate_monthly_journal_entries(schedule_df, lease_type="Operating"):
    """
    Convert the amortization schedule into monthly JE line items.
    """
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
            # ROU Asset Amortization
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
# 4. STREAMLIT APP
############################
def main():
    st.title("LAMPE LEASE")
    
    st.sidebar.header("Lease Inputs")
    lease_type = st.sidebar.selectbox("Lease Classification", ["Operating", "Finance"])
    start_date = st.sidebar.date_input("Lease Start Date", value=date.today())
    
    lease_term = st.sidebar.number_input("Lease Term (months)", min_value=1, value=36)
    annual_discount_rate = st.sidebar.number_input("Annual Discount Rate (%)", min_value=0.0, value=5.0)
    
    base_payment_amount = st.sidebar.number_input(
        "Base Monthly Payment (initial year)",
        min_value=0.0,
        value=1000.0
    )
    
    annual_escalation_pct = st.sidebar.number_input(
        "Annual Payment Escalation Rate (%)",
        min_value=0.0,
        value=5.0
    )
    
    payment_timing = st.sidebar.selectbox("Payment Timing", ["end", "begin"])
    
    if st.sidebar.button("Generate Schedule"):
        # 1) Generate schedule DataFrame
        df_schedule = generate_amortization_schedule(
            lease_term=lease_term,
            base_payment=base_payment_amount,
            annual_discount_rate=annual_discount_rate / 100.0,  # convert % to decimal
            annual_escalation_rate=annual_escalation_pct / 100.0, 
            start_date=start_date,
            payment_timing=payment_timing,
            lease_type=lease_type
        )
        
        # 2) Display schedule
        st.subheader("Lease Amortization Schedule")
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
        
        # 3) Download schedule CSV
        csv_schedule = df_schedule.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Amortization Schedule (CSV)",
            data=csv_schedule,
            file_name="variable_lease_amortization_schedule.csv",
            mime="text/csv"
        )
        
        # 4) Generate Journal Entries
        df_journal = generate_monthly_journal_entries(df_schedule, lease_type=lease_type)
        
        st.subheader("Monthly Journal Entries")
        st.dataframe(
            df_journal.style.format({"Debit": "{:,.2f}", "Credit": "{:,.2f}"})
        )
        
        # 5) Download JEs CSV
        csv_journal = df_journal.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Journal Entries (CSV)",
            data=csv_journal,
            file_name="monthly_journal_entries.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()


