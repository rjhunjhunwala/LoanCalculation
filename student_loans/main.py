import streamlit as st
from collections import defaultdict
import pandas as pd
import re

import loans
from loans import (
    Person,
    DirectSubsidizedFederal,
    DirectUnsubsidizedFederal,
    PrivateLoanFactory,
    minimize_total_paid

)
from student_loans.loans import PLUS_UNSUB

st.title("Optimal Student Loan Planning")

# --------------------------
# Borrower Details Input
# --------------------------
st.sidebar.header("Borrower Details")
family_income = st.sidebar.number_input("Family Income (AGI)", value=50000.0, step=1000.0)
subsidized_loan_eligible = st.sidebar.checkbox("I am qualified for subsidized loans", value = family_income <= 45000)
starting_income = st.sidebar.number_input("Starting Annual Income", value=40000.0, step=1000.0)
personal_contrib = st.sidebar.number_input("Annual Personal Contribution", value=10000.0, step=500.0)
attendance_cost = st.sidebar.number_input("Annual Attendance Cost Net of Aid", value=20000.0, step=500.0)
graduation_time = st.sidebar.number_input("Years in School", min_value=1, max_value=10, value=4)

num_banks = st.sidebar.number_input("Number of plans to consider:", value = 1, step = 1)


# --------------------------
# Interest Rates Input
# --------------------------
st.sidebar.header("Federal Interest Rates")
subs_rate = st.sidebar.number_input("Federal Subsidized Rate (%)", value=loans.FEDERAL_RATE_SUBSIDIZED*100, step=0.1)/100
unsubs_rate = st.sidebar.number_input("Federal Unsubsidized Rate (%)", value=loans.FEDERAL_RATE_UNSUBSIDIZED*100, step=0.1)/100


# override module constants, (bad)
loans.FEDERAL_RATE_SUBSIDIZED   = subs_rate
loans.FEDERAL_RATE_UNSUBSIDIZED = unsubs_rate

FED_SUB_SRC   = DirectSubsidizedFederal()
FED_UNSUB_SRC = DirectUnsubsidizedFederal()

sources = [
    FED_SUB_SRC,
    FED_UNSUB_SRC,
]

st.sidebar.header("Financial Institution Details")

for i in range(num_banks):
    st.sidebar.header(f"Bank {i + 1}")
    bank_name = st.sidebar.text_input(f"Bank {i + 1} Name", f"Bank {i + 1}")
    bank_rate = st.sidebar.number_input(f"{bank_name} rate (%)", value=unsubs_rate * 100 + 2, step=0.1)/100
    max_years = st.sidebar.number_input(f"{bank_name} term duration", value=10, step=1)
    bank_src   = PrivateLoanFactory(bank_name, bank_rate, max_years=max_years)
    sources.append(bank_src)

# --------------------------
# Create Person
# --------------------------
person = Person(
    family_income=family_income,
    subsidized_loan_eligible=subsidized_loan_eligible,
    starting_income=starting_income,
    annual_personal_contribution=personal_contrib,
    annual_attendance_cost=attendance_cost,
    graduation_time=graduation_time,
)


# --------------------------
# Compute Optimal Plans
# --------------------------
yearly_optimal = minimize_total_paid(person, sources)

# flatten
all_plans = [item for year in yearly_optimal for item in year]

# --------------------------
# Group & Sum Plans
# --------------------------
groups = defaultdict(lambda: {"amount": 0.0, "rep": None})
for borrow, plan, src in all_plans:
    key = (src.name(), plan.__class__.__name__)
    groups[key]["amount"] += borrow
    # keep the last plan as representative
    groups[key]["rep"] = plan

# --------------------------
# Display Summarized Plans
# --------------------------
st.header("Selected plans: ")
for (src_name, plan_name), info in groups.items():


    parts = re.findall(r'[A-Z][^A-Z]*', str(src_name))
    if parts:
        src_name = " ".join(parts)

    parts = re.findall(r'[A-Z][^A-Z]*', str(plan_name))
    if parts:
        plan_name = " ".join(parts)

    total_borrowed = info["amount"]
    rep_plan = info["rep"]
    # reset principal & cache
    rep_plan.principal = total_borrowed
    if hasattr(rep_plan, "total_paid"):
        rep_plan.total_paid = None

    total_paid = rep_plan.compute_total_paid(person)
    first_pmt   = rep_plan.monthly_payment(1, person)

    with st.expander(f"{plan_name} from {src_name} — Borrow ${total_borrowed:,.2f}"):
        st.write(f"**Rate:** {rep_plan.annual_rate*100:.2f}%")
        st.write(f"**Term:** {rep_plan.term_years} years")
        st.write(f"**First Month Payment:** ${first_pmt:,.2f}")
        st.write(f"**Total Paid:** ${total_paid:,.2f}")
        schedule = rep_plan.amortization_schedule(person)
        st.dataframe(schedule)

# --------------------------
# Overall Summary
# --------------------------
st.header("Overall Loan Summary")
total_borrowed_all = sum(info["amount"] for info in groups.values())
total_paid_all     = sum(info["rep"].compute_total_paid(person) for info in groups.values())

with st.expander("Show Combined Summary"):
    st.write(f"**Total Borrowed Across All Plans:** ${total_borrowed_all:,.2f}")
    st.write(f"**Total Paid Across All Plans:** ${total_paid_all:,.2f}")
    # build a combined amortization by summing month-by-month
    combined = {}
    for info in groups.values():
        sched = info["rep"].amortization_schedule(person)
        for row in sched:
            m = row["month"]
            combined.setdefault(m, {"payment": 0.0, "interest_paid": 0.0, "principal_paid": 0.0})
            combined[m]["payment"]       += row["payment"]
            combined[m]["interest_paid"] += row["interest_paid"]
            combined[m]["principal_paid"]+= row["principal_paid"]

    # convert to DataFrame
    df = pd.DataFrame([
        {
            "month": m,
            **vals,
            "balance": ""  # omitted for aggregate
        }
        for m, vals in sorted(combined.items())
    ])
    st.dataframe(df)
