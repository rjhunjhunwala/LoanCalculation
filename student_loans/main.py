import streamlit as st
from collections import defaultdict
import pandas as pd
import re

# Group things into expanders...
# Simplify Wording
# Cost of attendance: -> Tuition, Room and Board, Scholarships
# Parents Contribution Annual:
# Starting annual income after college
# Family Income -> Joint Parental income


import loans
from loans import (
    Person,
    DirectSubsidizedFederal,
    DirectUnsubsidizedFederal,
    PrivateLoanFactory,
    minimize_total_paid,
    PLUS_UNSUB
)

st.title("Optimal Student Loan Planning")

# --------------------------
# Borrower Details Input
# --------------------------
st.sidebar.header("Borrower Details")
subsidized_loan_eligible = st.sidebar.checkbox("I am qualified for subsidized loans", value = True)
starting_income = st.sidebar.number_input("Expected Income After Graduation", value=40000.0, step=1000.0)
personal_contrib = st.sidebar.number_input("Parent Contribution Annual", value=10000.0, step=500.0)
attendance_cost = st.sidebar.number_input("Tuition + Room/Board - Scholarships", value=20000.0, step=500.0)

with st.sidebar.expander("Timelines"):
    graduation_time = st.number_input("Years in School", min_value=1, max_value=10, value=4)

    payoff_min_length, payoff_max_length = st.slider("Select a number of years you are willing to wait to pay off your debt. ", 1, 30, (1, 30))

    min_dti, max_dti = st.slider("Select a debt to income range.\n We recommend you put no more than 30% of income to debt servicing. ", min_value=0.0, max_value=1.0, value=(0.0, 0.30))
    st.write("We will use these parameters to find a debt payoff plan within your constraints that minimizes the amount of **lifetime total interest** paid. ")


FED_SUB_SRC   = DirectSubsidizedFederal()
FED_UNSUB_SRC = DirectUnsubsidizedFederal()

sources = [
    FED_SUB_SRC,
    FED_UNSUB_SRC,
    PLUS_UNSUB
]

with st.sidebar.expander("Explore Private Loans"):
    num_banks = st.number_input("Number of private loans to consider", value = 0, step = 1)

    for i in range(num_banks):
        st.header(f"Bank {i + 1}")
        bank_name = st.text_input(f"Bank {i + 1} Name", f"Bank {i + 1}")
        bank_rate = st.number_input(f"{bank_name} rate (%)", value=10.0, step=0.1)/100
        max_years = st.number_input(f"{bank_name} term duration", value=10, step=1)
        bank_src   = PrivateLoanFactory(bank_name, bank_rate, max_years=max_years)
        sources.append(bank_src)

# --------------------------
# Create Person
# --------------------------
person = Person(
    family_income=0,
    subsidized_loan_eligible=subsidized_loan_eligible,
    starting_income=starting_income,
    annual_personal_contribution=personal_contrib,
    annual_attendance_cost=attendance_cost,
    graduation_time=graduation_time,
    min_dti= min_dti,
    max_dti=max_dti,
    payoff_min_length=payoff_min_length,
    payoff_max_length=payoff_max_length
)

# --------------------------
# Compute Optimal Plans
# --------------------------

if personal_contrib >= attendance_cost:
    st.write("Congratulations! You've entered that you've saved enough to not borrow for College!")
else:
    yearly_optimal = minimize_total_paid(person, sources)

    if not yearly_optimal:
        st.write("We can't find a set of student loans that meet your needs. ")
    else:
        # flatten
        all_plans = [item for year in yearly_optimal for item in year]

        # --------------------------
        # Group & Sum Plans
        # --------------------------
        groups = defaultdict(lambda: {"amount": 0.0, "rep": None,})
        for borrow, plan, src in all_plans:
            key = (src.name(), plan.__class__.__name__,  plan.loan_terms())

            groups[key]["amount"] += borrow

            if groups[key]["rep"] is not None:
                groups[key]["rep"] += plan
            else:
                groups[key]["rep"] = plan

        # --------------------------
        # Display Summarized Plans
        # --------------------------
        st.header("Selected plans: ")
        for (src_name, plan_name, _internal_name), info in groups.items():


            parts = re.findall(r'[A-Z][^A-Z]*', str(src_name))
            if parts:
                src_name = " ".join(parts)

            parts = re.findall(r'[A-Z][^A-Z]*', str(plan_name))
            if parts:
                plan_name = " ".join(parts)

            total_borrowed = info["amount"]
            rep_plan = info["rep"]
            initial_principal = rep_plan.principal

            total_paid = rep_plan.compute_total_paid(person)
            first_pmt   = rep_plan.monthly_payment(1, person)

            with st.expander(f"{plan_name} from {src_name} — Borrow ${total_borrowed:,.2f}"):
                st.write(f"**Rate:** {rep_plan.annual_rate*100:.2f}%")
                st.write(f"**Term:** {rep_plan.term_years} years")
                st.write(f"**First Month Payment:** ${first_pmt:,.2f}")
                st.write(f"**Principal on Graduation:** ${initial_principal:,.2f}")
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
