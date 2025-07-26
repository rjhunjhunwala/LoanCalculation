from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
import math

from student_loans.constants import FEDERAL_RATE_SUBSIDIZED, FEDERAL_RATE_UNSUBSIDIZED, FEDERAL_ORIG_FEE, \
    PLUS_UNSUB_RATE, PLUS_ORIG_FEE
from student_loans.person import Person
from student_loans.plans import FundingSource


class UserDefinedSource(FundingSource):
    """
    Existing user defined loans
    """
    _name: str
    _options: list

    def __init__(self, name: str, options: list) -> None:
        self._name = name
        self._options = options

    def name(self):
        return self._name

    def plan_options(self, person):
        return _options
