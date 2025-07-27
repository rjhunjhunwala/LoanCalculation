import streamlit as st
from collections import defaultdict
import pandas as pd
import re
from dataclasses import dataclass, field

from math import ceil

import loans
from plans import StandardPlan, DirectSubsidizedFederal, DirectUnsubsidizedFederal, PrivateLoanFactory, \
    PLUS_UNSUB, FundingSource, find_optimal_plan, UserDefinedSource
from person import Person


def add_currency_to_input(label, cur_symbol='$'):
    st.markdown(
        f"""
        <style>
            [aria-label="{label}"] {{
                padding-left: 20px;
            }}
            [data-testid="stNumberInput"]:has([aria-label="{label}"])::before {{
                position: absolute;
                content: "{cur_symbol}";
                left:10px;
                top:35px;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


st.title("**Optimal Student Loan Planning**")

# --------------------------
# Borrower Details Input
# --------------------------
with st.expander("**Borrower Details**"):
    subsidized_loan_eligible = st.checkbox("I am qualified for subsidized loans", value=True,
                                           help="Subsidized loans do not accrue interest while you're in school at least half-time.")
    gov_loan_eligible = st.checkbox(
        "I am attending an accredited undergrad college or university and am interested in federal loans. ", value=True,
        help="Check if you attend an accredited institution to qualify for federal loans.")
    graduation_time = st.number_input("Years in School", min_value=1, max_value=10, value=4,
                                      help="Expected number of years left in school before graduation.")
    starting_income = st.number_input("Expected Income After Graduation", value=75000, step=1000, format="%d",
                                      min_value=0,
                                      help="Estimated annual salary for your first year after graduating.")

with st.expander("**Expenses**", expanded=True):
    tuition = st.number_input(label := "Tuition", value=15000, step=500, format="%d", min_value=0,
                              help="Annual tuition cost charged by your college or university.")
    add_currency_to_input(label)

    expenses = st.number_input(label := "Eligible Personal Expenses (Commute, books, food)", value=2500, step=500,
                               format="%d", min_value=0,
                               help="Annual costs for books, food, transportation, and other educational expenses.")
    add_currency_to_input(label)
    room_board = st.number_input(label := "Housing/ Room + Board", value=15000, min_value=0, step=500,
                                 help="Estimated annual cost of housing and meals.")

    add_currency_to_input(label)

with st.expander("**Payments**"):
    parent_contribution = st.number_input(label := "Parent Contribution Annual", value=0, step=500, format="%d",
                                          min_value=0,
                                          help="How much your parents or guardians can contribute each year.")
    add_currency_to_input(label)
    student_contribution = st.number_input(label := "Student Contribution Annual", value=0, step=500, format="%d",
                                           min_value=0,
                                           help="How much you can contribute from personal savings each year.")
    add_currency_to_input(label)
    employment_contribution = st.number_input(label := "Student Employment Annual Income", value=0, step=500,
                                              format="%d", min_value=0,
                                              help="Income from work-study, internships, or part time employment.")
    add_currency_to_input(label)

    personal_contrib = parent_contribution + student_contribution + employment_contribution

    num_scholarships = st.number_input("Number of Scholarships Awarded", value=0, step=1, min_value=0,
                                       help="Enter the number of different private loan offers you'd like to compare.")

    total_scholarships = 0

    for i in range(num_scholarships):

        scholarship = st.number_input(label := f"Scholarships or Grant Financial Aid Amount: Source #{i + 1}", value=0,
                                      min_value=0,
                                      help="Annual amount of scholarships or need-based grant aid received from this source.")

        add_currency_to_input(label)

        if st.checkbox(f"#{i + 1} One Time Grant/Scholarship: ",
                       help="Check this if this scholarship or grant is only awarded once and not repeated annually."):
            total_scholarships += scholarship / graduation_time
        else:
            total_scholarships += scholarship

if gov_loan_eligible:

    FED_SUB_SRC = DirectSubsidizedFederal()
    FED_UNSUB_SRC = DirectUnsubsidizedFederal()

    sources = [
        FED_SUB_SRC,
        FED_UNSUB_SRC,
    ]
else:
    sources = []

with st.expander("**Explore Private Loans**"):
    num_banks = st.number_input("Number of private loans to consider", value=1, step=1, min_value=0,
                                help="Enter the number of different private loan offers you'd like to compare.")

    for i in range(num_banks):
        st.header(f"Private Loan {i + 1}")
        bank_name = st.text_input(f"Private Loan {i + 1} Name", f"Private Loan {i + 1}")
        bank_rate = st.number_input(f"{bank_name} rate (%)", value=9.0, step=0.1, min_value=0.5,
                                    help="Annual interest rate (APR) for this private loan.") / 100
        max_years = st.number_input(f"{bank_name} term duration", value=10, step=1, min_value=0,
                                    help="Number of years you have to pay off this loan.")
        bank_src = PrivateLoanFactory(bank_name, bank_rate, max_years=max_years)
        sources.append(bank_src)

attendance_cost = tuition + expenses + room_board - total_scholarships

with st.expander("**Timelines**"):
    payoff_min_length, payoff_max_length = st.slider(
        "How many years do you plan to take to pay off your student loan debt. ",
        1, 30, (1, 30),
        help="Minimum and maximum number of years you'd be comfortable repaying your loans over."
    )

    min_dti, max_dti = st.slider(
        "What percentage of your income can you allocate toward loan payments? Most lenders recommend keeping this below 30% of your gross income. ",
        min_value=0, max_value=100, value=(0, 30), step=1,
        help="Debt-to-Income ratio (DTI) is the percentage of income you are willing to spend on monthly loan payments."
    )
    min_dti, max_dti = min_dti / 100, max_dti / 100

    min_payment_only = st.checkbox("I only will make the minimum payments. ", value=False,
                                   help="Check this if you want to make only minimum payments on loans. This solver is most helpful when it helps you find ways to save money by paying loans off early. ")
    st.write("We will find a debt payoff plan within your constraints to minimize **lifetime total interest** paid.")

with st.expander("**Current loan balances**", expanded=True):
    existing_loans = []
    num_loans = st.number_input("Number of current loans: ", value=0, step=1, min_value=0,
                                help="If you are already in college, you might have outstanding loans. ")
    for loan in range(1, num_loans + 1):
        loan_name = st.text_input(f"Existing Loan {loan} Name", f"Existing Loan {loan}")
        curr_balance = st.number_input(label := f"Current Balance on {loan_name}", min_value=100.0, step=1.0,
                                       help="Current Balance on This Loan")
        add_currency_to_input(label)

        rate = st.number_input(f"Loan {loan} rate (%)", value=10.0, step=0.1, min_value=0.0,
                               help="Annual interest rate (APR) for this private loan.") / 100
        subsidized_loan = st.checkbox(f"Loan {loan} does not accrue interest while in school  ", value=False,
                                      help="Subsidized loans do not accrue interest while you're in school at least half-time.")
        term = st.number_input(f"Loan {loan} Term:. ", value=10, step=1, min_value=0,
                               help="How long do you have to pay this loan off. ")

        existing_loans.append((curr_balance, StandardPlan(rate, term), UserDefinedSource(loan_name, StandardPlan(rate, term), rate, subsidized_loan)))

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
    min_dti=min_dti,
    max_dti=max_dti,
    payoff_min_length=payoff_min_length,
    payoff_max_length=payoff_max_length,
    existing_loans={0:existing_loans},
    minimum_payment_only = min_payment_only,
)

# --------------------------
# Compute Optimal Plans
# --------------------------

if personal_contrib >= attendance_cost:
    st.write("Congratulations! You've entered that you've saved enough to not borrow for College!")
else:
    yearly_optimal, overpayments = find_optimal_plan(person, sources)

    if not yearly_optimal:
        st.write(
            "We can't find a set of student loans that meet your needs. Please adjust your debt to income or payoff timelines. ")
    else:
        all_plans = {year: [] for year in range(graduation_time)}
        # flatten
        for year in range(graduation_time):
            for balance, plan, src in yearly_optimal.get(year, []):
                all_plans[year].append((balance, plan, src))

        # --------------------------
        # Group & Sum Plans
        # --------------------------

        groups = defaultdict(lambda:defaultdict(lambda : {"amount": 0, "rep": None, "src": None }))

        for year in all_plans:
            for borrow, plan, src in all_plans[year]:
                key = (src.name(), plan.__class__.__name__, plan.loan_terms())

                groups[key][year]["amount"] += borrow
                groups[key][year]["rep"] = plan
                groups[key][year]["src"] = src

        # --------------------------
        # Display Summarized Plans
        # --------------------------
        st.header("Selected plans: ")
        tables = []

        for (src_name, plan_name, _internal_name), info in groups.items():

            parts = re.findall(r'[A-Z][^A-Z]*', str(src_name))
            if parts:
                src_name = " ".join(parts)

            parts = re.findall(r'[A-Z][^A-Z]*', str(plan_name))
            if parts:
                plan_name = " ".join(parts)

            total_borrowed = sum(info[year]["amount"] for year in info)
            rep_plan = [info[year]["rep"] for year in info][0]
            src = [info[year]["src"] for year in info][0]
            initial_principal = sum(src.principal(info[year]["amount"], year, person) for year in info)
            if initial_principal == 10000:
                breakpoint()
            print(src, rep_plan)
            schedule = rep_plan.amortization_schedule(initial_principal, person, overpayments[src, rep_plan])
            total_paid = sum(row["payment"] for row in schedule)
            first_pmt = overpayments[src, rep_plan][0]
            real_term = ceil(min([rep_plan.term_years* 12] + [i for i in overpayments[src, rep_plan] if overpayments[src, rep_plan][i] < 1]) / 12)
            with st.expander(f"{plan_name} from {src_name} — Borrow ${total_borrowed:,.2f}"):
                st.write(f"**Rate:** {rep_plan.annual_rate * 100:.2f}%")
                st.write(f"**Term:** {rep_plan.term_years} years")
                st.write(f"**Recommended Payoff Term:** {real_term} years")
                st.write(f"**First Month Payment:** ${first_pmt:,.2f}")
                st.write(f"**Principal on Graduation:** ${initial_principal:,.2f}")
                st.write(f"**Total Paid:** ${total_paid:,.2f}")
                for year in info:
                    st.write(f"In Year **{year + 1}:** ${info[year]['amount']:,.2f} Borrowed")

                tables.append(schedule)
                st.dataframe(schedule)

        # --------------------------
        # Overall Summary
        # --------------------------
        st.header("Overall Loan Summary")
        total_borrowed_all = sum(info[year]["amount"] for info in groups.values() for year in info)
        total_paid_all = sum(
            sum(row["payment"] for row in sched) for sched in tables
        )
        with st.expander("Show Combined Summary", expanded=True):
            st.write(f"**Total Borrowed Across All Plans:** ${total_borrowed_all:,.2f}")
            st.write(f"**Total Paid Across All Plans:** ${total_paid_all:,.2f}")
            # build a combined amortization by summing month-by-month
            combined = {}

            for sched in tables:
                for row in sched:
                    m = row["month"]
                    combined.setdefault(m,
                                        {"payment": 0.0, "interest_paid": 0.0, "principal_paid": 0.0, "balance": 0.0})
                    combined[m]["payment"] += row["payment"]
                    combined[m]["interest_paid"] += row["interest_paid"]
                    combined[m]["principal_paid"] += row["principal_paid"]
                    combined[m]["balance"] += row["balance"]

            # convert to DataFrame
            df = pd.DataFrame([
                {
                    "Payment Month": m,
                    "Payment": f"${vals["payment"]:,.0f}",
                    "Interest": f"${vals["interest_paid"]:,.0f}",
                    "Principal Paid": f"${vals["principal_paid"]:,.0f}",
                    "Balance": f"${vals["balance"]:,.0f}"
                }
                for m, vals in sorted(combined.items())
            ])
            st.dataframe(df, hide_index=True)
