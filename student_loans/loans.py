from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
import math

from student_loans.constants import FEDERAL_RATE_SUBSIDIZED, FEDERAL_RATE_UNSUBSIDIZED, FEDERAL_ORIG_FEE, \
    PLUS_UNSUB_RATE, PLUS_ORIG_FEE
from student_loans.person import Person
from student_loans.plans import FundingSource
