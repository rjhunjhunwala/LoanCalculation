from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
import math

# --------------------------
# Constants
# --------------------------
FEDERAL_RATE_SUBSIDIZED = 0.0653
FEDERAL_RATE_UNSUBSIDIZED = 0.0653
FEDERAL_ORIG_FEE = 0.01057           # 1.057% origination fee
PLUS_UNSUB_RATE = 0.0894
PLUS_ORIG_FEE = .04228

# --------------------------
# Person Data Model
# --------------------------
@dataclass
class Person:
    family_income: float                  # initial AGI
    subsidized_loan_eligible: bool
    starting_income: float                # starting income for repayment
    annual_personal_contribution: float
    annual_attendance_cost: float
    graduation_time: int                  # years until graduation
    income_appreciation: float = 0.03     #  year-over-year income growth (e.g., 3%)
    discretionary_factor: float = 0.1     # percentage of discretionary income

    def borrowed_amounts(self) -> List[float]:
        need = self.annual_attendance_cost - self.annual_personal_contribution
        return [need for _ in range(self.graduation_time)]

    def income_at_year(self, year: int) -> float:
        return self.starting_income * ((1 + self.income_appreciation) ** year)

    def discretionary_income(self, year: int = 0) -> float:
        agi = self.income_at_year(year)
        poverty_guideline = 13850
        return max(0.0, agi - 1.5 * poverty_guideline)

# --------------------------
# Plan Interface
# --------------------------
class Plan(ABC):
    @abstractmethod
    def monthly_payment(self, month: int, person: Person) -> float:
        """Compute payment for given month and borrower"""

    @abstractmethod
    def amortization_schedule(self, person: Person) -> List[dict]:
        """Generate amortization schedule based on monthly_payment(month, person)"""

    def compute_total_paid(self, person: Person) -> float:
        """
        Sum of all payments over the life of the loan, caching the result.
        """
        if not hasattr(self, 'total_paid') or self.total_paid is None:
            schedule = self.amortization_schedule(person)
            self.total_paid = sum(entry['payment'] for entry in schedule)
        return self.total_paid
# --------------------------
# Loan Base Class
# --------------------------
class Loan(Plan, ABC):
    def loan_terms(self):
        return f"{self.__class__.__name__}, {self.annual_rate}, {self.term_years}"

    def __add__(self, other):
        assert other.term_years == self.term_years and self.annual_rate == other.annual_rate and self.__class__ is other.__class__
        return self.__class__(self.principal + other.principal, self.annual_rate, self.term_years)
    def __init__(self, principal: float, annual_rate: float, term_years: int):
        self.principal = principal
        self.annual_rate = annual_rate
        self.term_years = term_years

    def amortization_schedule(self, person: Person) -> List[dict]:
        balance = self.principal
        r = self.annual_rate / 12
        schedule = []
        for m in range(1, self.term_years * 12 + 1):
            payment = self.monthly_payment(m, person)
            interest = balance * r
            principal_paid = payment - interest
            if principal_paid > balance:
                principal_paid = balance
                payment = principal_paid + interest
            balance -= principal_paid
            schedule.append({
                'month': m,
                'payment': round(payment, 2),
                'principal_paid': round(principal_paid, 2),
                'interest_paid': round(interest, 2),
                'balance': round(balance, 2)
            })
            if balance <= 0:
                break
        return schedule

# --------------------------
# Standard Helper
# --------------------------
def fixed_payment(principal: float, annual_rate: float, term_years: int) -> float:
    n = term_years * 12
    r = annual_rate / 12
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

# --------------------------
# Concrete Plans
# --------------------------
class StandardPlan(Loan):
    def __init__(self, principal: float, annual_rate: float, term_years: int = 10):
        super().__init__(principal, annual_rate, term_years)

    def monthly_payment(self, month: int, person: Person) -> float:
        return fixed_payment(self.principal, self.annual_rate, self.term_years)

class GraduatedPlan(Loan):
    def __init__(self, principal: float, annual_rate: float, term_years: int = 10,
                 step_years: int = 2, alpha: float = 1.5):
        super().__init__(principal, annual_rate, term_years)
        self.step_years = step_years
        self.alpha = alpha

    def monthly_payment(self, month: int, person: Person) -> float:
        if month == 1:
            # compute base based on PV formula
            n = self.term_years * 12
            r = self.annual_rate / 12
            pv = 0.0
            for m in range(1, n + 1):
                bump = (m - 1) // (self.step_years * 12)
                multiplier = self.alpha ** bump
                pv += multiplier / ((1 + r) ** m)
            self._base_payment = self.principal / pv
        bump = (month - 1) // (self.step_years * 12)
        return self._base_payment * (self.alpha ** bump)

class ExtendedPlan(StandardPlan):
    def __init__(self, principal: float, annual_rate: float):
        super().__init__(principal, annual_rate, term_years=25)

class PAYEPlan(Loan):
    def __init__(self, principal: float, rate, term_years=20):
        super().__init__(principal, rate, term_years=term_years)
    def monthly_payment(self, month: int, person: Person) -> float:
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        return max((disc * person.discretionary_factor) / 12, 0)

class REPAYEPlan(PAYEPlan):
    def monthly_payment(self, month: int, person: Person) -> float:
        return super().monthly_payment(month, person)

class SAVEPlan(PAYEPlan):
    def monthly_payment(self, month: int, person: Person) -> float:
        # SAVE uses 5% discretionary
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        return max((disc * 0.05) / 12, 0)

class ICRPlan(Loan):
    def __init__(self, principal: float, rate, term_years = 25):
        super().__init__(principal, rate, term_years=term_years)

    def monthly_payment(self, month: int, person: Person) -> float:
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        idr = (disc * 0.20) / 12
        twelve = StandardPlan(self.principal, self.annual_rate, term_years=12)
        std_pay = twelve.monthly_payment(month, person)
        return min(idr, std_pay)

# --------------------------
# Funding Sources
# --------------------------
@dataclass
class FundingSource(ABC):
    def limit(self, year, person):
        return 1e9

    def name(self):
        return self.__class__.__name__

    def principal(self, borrow, idx, person):
        return borrow

    @abstractmethod
    def plan_options(self, principal, person):
        return ...

    def available_plans(self, person: Person) -> List[Tuple[float, List[Plan]]]:
        out = []
        for idx, amt in enumerate(person.borrowed_amounts()):
            principal = self.principal(amt, idx, person)
            out.append((amt, self.plan_options(principal, person)))
        return out

def _federal_plans(principal: float, person: Person, rate) -> List[Plan]:
    return [
        *[StandardPlan(principal, rate, term) for term in range(1, 11)],
        GraduatedPlan(principal, rate),
        ExtendedPlan(principal, rate),
        PAYEPlan(principal, rate),
        REPAYEPlan(principal, rate),
        ICRPlan(principal, rate)
    ]

class DirectSubsidizedFederal(FundingSource):
    def limit(self, year, person):
        return (3500 + min(year, 2) * 1000) * int(person.subsidized_loan_eligible)

    def principal(self, borrow, year, person):
        return borrow * (1 + FEDERAL_ORIG_FEE)

    def plan_options(self, principal, person):
        return _federal_plans(principal, person, FEDERAL_RATE_SUBSIDIZED)

class DirectUnsubsidizedFederal(FundingSource):

    def limit(self, year, person):
        return 2000

    def principal(self, borrow, year, person):
        total = person.graduation_time
        monthly = FEDERAL_RATE_UNSUBSIDIZED / 12
        return borrow * (1 + FEDERAL_ORIG_FEE) * ((1+monthly)**((total-year)*12))

    def plan_options(self, principal, person: Person) -> List[Tuple[float, List[Plan]]]:
        return _federal_plans(principal, person, FEDERAL_RATE_UNSUBSIDIZED)

class PlusFederal(FundingSource):

    def limit(self, year, person):
        return 1e9

    def principal(self, borrow, idx, person):
        monthly = PLUS_UNSUB_RATE/12
        return borrow * (1 + PLUS_UNSUB_RATE) * ((1+monthly)**((person.graduation_time-idx)*12))

    def plan_options(self, principal, person: Person):
        return [StandardPlan(principal, PLUS_UNSUB_RATE, term) for term in range(1, 11)]

class PrivateLoanFactory(FundingSource):
    provider: str = "Unknown"
    max_years: int = 20

    def name(self):
        return self.provider

    def __init__(self, provider: str,  annual_rate: float, origination_fee: float = 0.0, max_years=20):
        self.rate = annual_rate
        self.fee = origination_fee
        self.provider = provider

    def principal(self, borrow, idx, person):
         monthly = self.rate / 12
         return borrow * (1+self.fee) * ((1+monthly)**((person.graduation_time-idx)*12))

    def plan_options(self, principal, person: Person):
        return [StandardPlan(principal, self.rate, term) for term in range(1, self.max_years + 1)]

# --------------------------
# Optimization
# --------------------------
def minimize_total_paid(person: Person, funding_sources: List[FundingSource]
                        ) -> List[List[Tuple[float, Plan, FundingSource]]]:
    """
    For each enrollment year:
    - collect options (borrow_amt, plan_index, source, ratio)
    - sort by total_paid/borrow ratio
    - greedily take funds until yearly need met, using fresh plan instances via available_plans on a temp Person
    """
    optimal = []
    total = sum(person.borrowed_amounts())
    for year_idx, need in enumerate(person.borrowed_amounts()):
        options: List[Tuple[float, int, FundingSource, float]] = []  # (full_amt, plan_idx, src, ratio)
        # gather base options
        for src in funding_sources:
            av = src.available_plans(person)
            if year_idx < len(av):
                full_amt, plans = av[year_idx]
                plan_options = []
                for idx, plan in enumerate(plans):
                    starting_payment = plan.monthly_payment(1, person)

                    if (starting_payment * 12 * total / plan.principal) / person.starting_income > .3:
                        continue
                    total_paid = plan.compute_total_paid(person)
                    ratio = total_paid / full_amt if full_amt > 0 else math.inf
                    plan_options.append((full_amt, idx, src, ratio))
                if plan_options:
                    options.append(min(plan_options, key= lambda x: x[3]))
        options.sort(key=lambda x: x[3])
        selected: List[Tuple[float, Plan, FundingSource]] = []
        cum = 0.0
        # select until need satisfied
        for full_amt, plan_idx, src, _ in options:
            if cum >= need:
                break
            take = min(full_amt, need - cum, src.limit(year_idx, person))
            # create a temp Person borrowing 'take'
            temp_person = Person(
                family_income=person.family_income,
                subsidized_loan_eligible=person.subsidized_loan_eligible,
                starting_income=person.starting_income,
                annual_personal_contribution=0.0,
                annual_attendance_cost=take,
                graduation_time=person.graduation_time,
                income_appreciation=person.income_appreciation,
                discretionary_factor=person.discretionary_factor
            )
            # get new plan for this partial borrow
            temp_plans = src.available_plans(temp_person)[year_idx][1]
            print(src.available_plans(temp_person))
            new_plan = temp_plans[plan_idx]
            print(new_plan.principal)
            # clear cached
            if hasattr(new_plan, 'total_paid'):
                new_plan.total_paid = None
            if take > 0:
                selected.append((take, new_plan, src))
            cum += take
        optimal.append(selected)
    return optimal

# Predefined Sources
FED_SUB = DirectSubsidizedFederal()
FED_UNSUB = DirectUnsubsidizedFederal()
PLUS_UNSUB = PlusFederal()

# End of loans.py

