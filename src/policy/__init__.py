"""Strategy Family Policy — maps Hermes outputs to allowed strategy families.

Layer model:
    Hermes v2.1 (Market & Risk Authority)
        ↓
    Strategy Family Policy (this package)
        ↓
    Concrete Strategies (future)

This package contains:
- StrategyFamilyPolicy: pure function mapping HermesDecision → allowed families
- StrategyFamily: enum of canonical strategy families
- StrategyFamilyMember: declaration-only interface for strategies
"""