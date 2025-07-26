from dataclasses import dataclass, field

@dataclass
class Person:
    family_income: float  # initial AGI
    subsidized_loan_eligible: bool
    starting_income: float  # starting income for repayment
    annual_personal_contribution: float
    annual_attendance_cost: float
    graduation_time: int  # years until graduation
    income_appreciation: float = 0.03  # year-over-year income growth (e.g., 3%)
    discretionary_factor: float = 0.1  # percentage of discretionary income
    min_dti: float = 0.0
    max_dti: float = 1.0
    payoff_min_length: int = 0
    payoff_max_length: int = 30
    existing_loans: list["Plan"] = field(default_factory=lambda: [])

    def borrowed_amounts(self) -> list[float]:
        need = self.annual_attendance_cost - self.annual_personal_contribution
        return [need for _ in range(self.graduation_time)]

    def income_at_year(self, year: int) -> float:
        return self.starting_income * ((1 + self.income_appreciation) ** year)

    def discretionary_income(self, year: int = 0) -> float:
        agi = self.income_at_year(year)
        poverty_guideline = 13850
        return max(0.0, agi - 1.5 * poverty_guideline)
