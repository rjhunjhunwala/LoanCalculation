from abc import ABC, abstractmethod
from dataclasses import dataclass

from constants import FEDERAL_ORIG_FEE, FEDERAL_RATE_SUBSIDIZED, FEDERAL_RATE_UNSUBSIDIZED, \
    PLUS_UNSUB_RATE, PLUS_ORIG_FEE
from person import Person

from mip import Model, xsum, BINARY, CONTINUOUS, minimize

@dataclass(frozen=True, eq=True)
class Plan:
    """
    A plan is defined to have an APR and a term years.

    We further assume that all loans are pre-payable without explicit penalty,
    and simply have a minimum monthly payment table with the outstanding balance
    forgiven on closure of the payment plan.

    We also assume that your minimum monthly payments are affine functions of your initial balance.
    This seems extreme, but if somebody creates a loan which does not behave this way,
    I will personally lobby to fix this glitch.

    Most importantly, a payment plan isn't associated with a precise "balance".

    Its just an algorithm to convert outstanding balances to monthly payments.
    """

    def _m(self, month, person):
        """
        A number _m such that the minimum monthly payment for month x is _m * initial_balance + _b
        :param month: Month 0 indexed after graduation
        :param person: person who uses this plan
        :return: _m
        """
        n = self.term_years * 12
        r = self.annual_rate / 12
        return (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    def _b(self, month, person):

        """
        A number _b such that the monthly payment for month x is _m * x + _b
        :param month: Month 0 indexed after graduation
        :param person: person borrowing with this plan
        :return: _b
        """
        return 0

    def monthly_payment(self, balance: float, month: int, person: Person) -> float:
        """Compute payment for given month and borrower. Month zero indexed. """
        m = self._m(month, person)
        b = self._b(month, person)
        return m * balance + b

    def compute_total_paid(self, balance: float, person: Person) -> float:
        """
        Sum of all payments over the life of the loan for a given balance:
        """
        schedule = self.amortization_schedule(balance, person)
        total_paid = sum(entry['payment'] for entry in schedule)
        return total_paid


    def loan_terms(self):
        return f"{self.__class__.__name__}, {self.annual_rate}, {self.term_years}"


    def __init__(self, annual_rate: float, term_years: int):
        self.annual_rate = annual_rate
        self.term_years = term_years

    def amortization_schedule(self, balance: float, person: Person, overpayments) -> list[dict]:
        """
        Compute an amortization table for a given person paying off this loan.
        :param person:
        :return:
        """
        initial_balance = balance
        r = self.annual_rate / 12
        schedule = []
        for m in range(0, self.term_years * 12):
            payment = overpayments[m]
            interest = balance * r
            principal_paid = payment - interest
            balance -= principal_paid
            schedule.append({
                'month': m + 1,
                'payment': round(payment, 2),
                'principal_paid': round(principal_paid, 2),
                'interest_paid': round(interest, 2),
                'balance': round(balance, 2)
            })
            if balance <= .01:
                break
        return schedule


class StandardPlan(Plan):
    """
    A standard plan with monthly minimum payments that finish the loan with no balance.
    """

    def __init__(self,  annual_rate: float, term_years: int = 10):
        super().__init__(annual_rate, term_years)


class GraduatedPlan(Plan):
    def __init__(self, annual_rate: float, term_years: int = 10,
                 step_years: int = 2, alpha: float = 1.5):
        super().__init__(annual_rate, term_years)
        self.step_years = step_years
        self.alpha = alpha

    def _m(self, month: int, person: Person) -> float:
        # compute base based on PV formula
        n = self.term_years * 12
        r = self.annual_rate / 12
        pv = 0.0
        for m in range(n):
            bump = (m ) // (self.step_years * 12)
            multiplier = self.alpha ** bump
            pv += multiplier / ((1 + r) ** m)
        self._base_payment = 1 / pv
        bump = (month) // (self.step_years * 12)
        return self._base_payment * (self.alpha ** bump)


class ExtendedPlan(StandardPlan):
    def __init__(self, annual_rate: float):
        super().__init__(annual_rate, term_years=25)


class PAYEPlan(Plan):
    def __init__(self, rate, term_years=20):
        super().__init__( rate, term_years=term_years)

    def _m(self, month: int, person: Person) -> float:
        """ Minimum Payments independent of balance. """
        return 0.0

    def _b(self, month: int, person: Person) -> float:
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        return max((disc * person.discretionary_factor) / 12, 0)


class REPAYEPlan(PAYEPlan):
    pass


class SAVEPlan(PAYEPlan):
    def _m(self, month: int, person: Person) -> float:
        # SAVE uses 5% discretionary
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        return max((disc * 0.05) / 12, 0)


class ICRPlan(Plan):
    def __init__(self, rate, term_years=25):
        super().__init__( rate, term_years=term_years)

    def _m(self, month: int, person: Person) -> float:
        year = (month - 1) // 12
        disc = person.discretionary_income(year)
        idr = (disc * 0.20) / 12
        twelve = StandardPlan(self.annual_rate, term_years=12)
        std_pay = twelve._m(month, person)
        return min(idr, std_pay)


@dataclass(eq=True, frozen=True)
class FundingSource(ABC):
    """
    A funding source determines two things.

    1: A list of limits that a borrower can take out for each given year.
    2: A list of Loan options to borrow from.
    The Borrower can have only _one_ loan product from the given source.

    """

    def limit(self, year, person) -> float:
        """ Many funding sources are without limits. So just default to a large number.

        Is this numerically stable? Who knows?
        """
        return 1e9

    def name(self) -> str:
        """
        How should we describe the name of this source of funds to the user?
        :return:
        """
        return self.__class__.__name__

    def _principal_m(self, year, person):
        """How many dollars owed at graduation for 1 dollar borrowed in year. """
        return 1

    def _principal_b(self, year, person):
        """Cost to borrow _any_ money from this source. """
        return 0

    def principal(self, borrow, year, person):
        """
        How much will the loan balance be if we borrow a certain amount in the given year as a given person.

        Why is this not simply the identity function? Capitalism.

        :param borrow: Borrowed amount in the students given year
        :param year: The year 0 indexed money borrowed: 0 = Freshman 1 = Sophomore etc...
        :param person: The person borrowing the amount
        :return: The starting balance.
        """

        return self._principal_m(year, person) * borrow + self._principal_b(year, person)

    @abstractmethod
    def plan_options(self, person):
        """What are the plan options available to the user. """
        return ...


def _federal_plans(rate) -> list[Plan]:
    return [
        StandardPlan(rate, 10),
        GraduatedPlan( rate),
        ExtendedPlan( rate),
        # PAYEPlan(principal, rate), # Relatively hard to actually qualify for...
        REPAYEPlan( rate),
        ICRPlan( rate)
    ]


class DirectSubsidizedFederal(FundingSource):
    def limit(self, year, person):
        return (3500 + min(year, 2) * 1000) * int(person.subsidized_loan_eligible)

    def _principal_m(self, year, person):
        return (1 + FEDERAL_ORIG_FEE)

    def plan_options(self, person):
        return _federal_plans(FEDERAL_RATE_SUBSIDIZED)


class DirectUnsubsidizedFederal(FundingSource):

    def limit(self, year, person):
        return 2000

    def _principal_m(self, year, person):
        total = person.graduation_time
        monthly = FEDERAL_RATE_UNSUBSIDIZED / 12
        return (1 + FEDERAL_ORIG_FEE) * ((1 + monthly) ** ((total - year) * 12))

    def plan_options(self, person: Person) -> list[tuple[float, list[Plan]]]:
        return _federal_plans(FEDERAL_RATE_UNSUBSIDIZED)


class PlusFederal(FundingSource):

    def limit(self, year, person):
        return 1e9

    def _principal_m(self, idx, person):
        monthly = PLUS_UNSUB_RATE / 12
        return (1 + PLUS_ORIG_FEE) * ((1 + monthly) ** ((person.graduation_time - idx) * 12))

    def plan_options(self, person: Person):
        return [StandardPlan(principal, PLUS_UNSUB_RATE, 10)]


class PrivateLoanFactory(FundingSource):
    provider: str = "Unknown"
    max_years: int = 20

    def name(self):
        return self.provider

    def __init__(self, provider: str, annual_rate: float, origination_fee: float = 0.0, max_years=20):
        self.rate = annual_rate
        self.fee = origination_fee
        self.provider = provider
        self.max_years = max_years

    def _principal_m(self, idx, person):
        monthly = self.rate / 12
        return (1 + self.fee) * ((1 + monthly) ** ((person.graduation_time - idx) * 12))

    def plan_options(self, person: Person):
        return [StandardPlan(self.rate,  self.max_years)]

FED_SUB = DirectSubsidizedFederal()
FED_UNSUB = DirectUnsubsidizedFederal()
PLUS_UNSUB = PlusFederal()

def find_optimal_plan(person: Person, sources: list[FundingSource]) -> dict[int, list[tuple[float, Plan, FundingSource]]]:
    """
    Given a person who can borrow from given sources find out where we he should borrow from
    :param person:
    :param sources:
    :return: A dict where for each year we say how much to borrow from which plan from which source.
    """
    try:
        model = Model(sense=minimize, backend="GRB")
        model.set_param("MIPFocus", 3)  # Emphasize finding feasible solutions quickly
        model.set_param("Presolve", 2)  # Aggressive presolve
        model.set_param("Cuts", 0
                        )  # Use more aggressive cuts
        model.set_param("Heuristics", 0.5)  # Increase heuristic effort
    except:
        model = Model(sense=minimize, backend="CBC")
    known_balances = {(plan, src): balance for balance, plan, src in person.existing_loans[0]}

    borrowed_from: dict[tuple[int, FundingSource, Plan], mip.Var] = {}
    used: dict[tuple[int, FundingSource, Plan], mip.Var] = {}
    months = max(plan.term_years for s in sources for plan in s.plan_options(person)) * 12

    # Variables for payments and balances
    payment: dict[tuple[int, FundingSource, Plan], mip.Var] = {}
    balance: dict[tuple[int, FundingSource, Plan], mip.Var] = {}

    # Create variables for borrowing from each source/plan in each year
    for year in range(person.graduation_time):
        for source in sources:
            plans = source.plan_options(person)
            for plan in plans:
                var = model.add_var(var_type=CONTINUOUS, name=f"borrow_{year}_{source.name()}_{plan.__class__.__name__}", lb=0, ub=source.limit(year, person))
                used_var = model.add_var(var_type=BINARY, name=f"use_{year}_{source.name()}_{plan.__class__.__name__}")
                borrowed_from[(year, source, plan)] = var
                used[(year, source, plan)] = used_var
                model += var <= source.limit(year, person) * used_var

        for (plan, src), known_balance in known_balances.items():
            print(known_balances)
            var = model.add_var(var_type=CONTINUOUS, name=f"borrow_{year}_{src.name()}_{plan.__class__.__name__}", lb=0, ub=known_balance)
            used_var = model.add_var(var_type=BINARY, name=f"use_{year}_{src.name()}_{plan.__class__.__name__}")
            borrowed_from[(year, src, plan)] = var
            used[(year, src, plan)] = used_var
            if year == 0:
                model += (var == known_balance)
            else:
                model += (var == 0)

    active_plan: dict[tuple[FundingSource, Plan], mip.Var] = {}
    known_balance_sources = [source for (plan, source) in known_balances]

    for source in sources + known_balance_sources:
        for plan in source.plan_options(person):
            active_plan[(source, plan)] = model.add_var(var_type=BINARY)
        model += xsum(active_plan[(source, plan)] for plan in source.plan_options(person)) == 1


    for source in sources + known_balance_sources:
        for year in range(person.graduation_time):
            for plan in source.plan_options(person):
                model += active_plan[(source, plan)] >= used[(year, source, plan)]

    for year in range(person.graduation_time):
        model += (xsum(borrowed_from[(year, source, plan)] for source in sources for plan in source.plan_options(person)) == person.borrowed_amounts()[year])

    # Calculate the total borrowed per plan
    plan_balance = {
        (plan, s): model.add_var(var_type=CONTINUOUS)
        for s in sources + known_balance_sources
        for plan in s.plan_options(person)
    }

    for (plan, s), var in plan_balance.items():
        model += var == xsum(
            s.principal(borrowed_from[(year, s, plan)], year, person)
            for year in range(person.graduation_time)
        )

    # Monthly constraints: balance update and DTI limits
    for source in sources + known_balance_sources:
        for plan in source.plan_options(person):
            r = plan.annual_rate / 12
            for month in range(0, plan.term_years * 12 ):
                payment[(month, source, plan)] = model.add_var(var_type=CONTINUOUS, name=f"payment_{month}_{plan.__class__.__name__}", lb=0)
                balance[(month, source, plan)] = model.add_var(var_type=CONTINUOUS, name=f"balance_{month}_{plan.__class__.__name__}", lb=0)
            # Initial balance and boundary conditions
            model += balance[(0, source, plan)] == (1 + r) * plan_balance[(plan, source)] - payment[(0,source, plan)]
            model += balance[(plan.term_years * 12 - 1, source, plan)] == 0

            # Recurrence for remaining months
            for month in range(1, plan.term_years * 12):
                 model += balance[(month, source, plan)] >= 0
                 model += balance[(month, source, plan)] == (1 + r) * balance[(month - 1, source, plan)] - payment[(month, source, plan)]

            # Minimum and maximum DTI-limited payment constraints
            for month in range(0, plan.term_years * 12 ):
                min_formula = plan._m(month, person) * plan_balance[plan, source] + plan._b(month, person)
                full = (plan_balance[plan, source] if month == 0 else balance[(month - 1, source, plan)]) * (1 + r)

                i1 = model.add_var(var_type=BINARY, name=f"i1_{month}_{plan.__class__.__name__}")
                i2 = model.add_var(var_type=BINARY, name=f"i2_{month}_{plan.__class__.__name__}")
                s1 = model.add_var(lb=-1e6, ub =1e6 * (1 - person.minimum_payment_only))
                s2 = model.add_var(lb=-1e6, ub=1e6 * (1 - person.minimum_payment_only))
                model += s1 >= 1e6 * -i1
                model += s1 <= 1e6 * i1
                model += s2 >= 1e6 * -i2
                model += s2 <= 1e6 * i2


                # Enforce that exactly one of i1 or i2 is 1
                model += i1 + i2 == 1


                # Constrain payment to be >= i1 * balance + i2 * min_payment (min of the two)
                model += payment[(month, source, plan)] == min_formula + s1
                model += payment[(month, source, plan)] == full + s2

                model += payment[(month, source, plan)] <= full
                model += payment[(month, source, plan)] >= 0


    for month in range(0, months):
        debt_service = person.max_dti * person.income_at_year(int(month / 12)) / 12
        model += xsum(payment[(month, s, plan)] for plan, s in plan_balance if (month, s, plan) in payment) <=  debt_service


    # Objective: Minimize total payment
    model.objective = minimize(xsum(payment[(month, source, plan)] for plan, source in plan_balance for month in range(plan.term_years * 12 )))

    model.optimize()

    if model.num_solutions == 0:
        return None, None

    result: dict[int, list[tuple[float, Plan, FundingSource]]] = {year: [] for year in range(person.graduation_time)}

    overpayments = dict()
    for year, source, plan in borrowed_from:
        amt = borrowed_from[(year, source, plan)].x
        if type(source) == UserDefinedSource:
            print(year, source, plan, amt)
        if amt > 1e-3:
            result[year].append((amt, plan, source))
            overpayments[source, plan] = {month: payment[(month, source, plan)].x for month in range(0, plan.term_years * 12)}


    return result, overpayments


class UserDefinedSource(FundingSource):
    """
    Existing user defined loans
    """
    _name: str
    _options: list
    _rate: float

    def __init__(self, name: str, plan: Plan, rate: float, subsidized: bool) -> None:
        self._name = name
        self._options = [plan]
        self._rate = rate
        self._subsidized = subsidized

    def name(self):
        return self._name

    def _principal_m(self, year, person):
        if self._subsidized:
            return 1
        else:
            monthly = self._rate / 12
            return ((1 + monthly) ** ((person.graduation_time - year) * 12))


    def plan_options(self, person):
        return self._options
