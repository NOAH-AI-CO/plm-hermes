from enum import Enum, auto
from typing import List

class Phase(str, Enum):
    PHASE_1 = "1"
    PHASE_1_2 = "1/2"
    PHASE_2 = "2"
    PHASE_2_3 = "2/3"
    PHASE_3 = "3"
    PHASE_4 = "4"

class TreatmentLine(str, Enum):
    FIRST_LINE = "first-line"
    SECOND_LINE = "second-line"
    LATER_LINE = "later-line"
    RELAPSED_REFRACTORY = "rr"

class HealthCondition(str, Enum):
    HEALTHY_VOLUNTEERS = "healthy volunteers"
    HIV_POSITIVE = "hiv-positive"
    DIABETIC = "diabetic"
    HYPERTENSIVE = "hypertensive"
    OBESE = "obese"
    HEPATIC_RENAL_IMPAIRMENT = "hepatic/renal impairment"
    LIVER_KIDNEY_DYSFUNCTION = "liver/kidney dysfunction"

class Sex(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    ALL = "ALL"

class Age(str, Enum):
    CHILD = "CHILD"
    ADULT = "ADULT"
    OLDER_ADULT = "OLDER_ADULT"

class InterventionModel(str, Enum):
    SINGLE_GROUP = "SINGLE_GROUP"
    PARALLEL = "PARALLEL"
    CROSSOVER = "CROSSOVER"
    FACTORIAL = "FACTORIAL"
    SEQUENTIAL = "SEQUENTIAL"

class MaskingType(str, Enum):
    NONE = "NONE"
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    TRIPLE = "TRIPLE"
    QUADRUPLE = "QUADRUPLE"

class Location(str, Enum):
    CHINA = "CN"
    UNITED_STATES = "US"
    EUROPEAN_UNION = "EU"
    JAPAN = "JP"
    OTHER = "Other"

# Lists for examples
phases = [p.value for p in Phase]
treatment_lines = [t.value for t in TreatmentLine]
health_conditions = [h.value for h in HealthCondition]
sexes = [s.value for s in Sex]
ages = [a.value for a in Age]
intervention_models = [i.value for i in InterventionModel]
masking_types = [m.value for m in MaskingType]
locations = [l.value for l in Location]
