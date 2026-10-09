"""The checks this server can run without a model, and what one costs.

A checked policy is answered by a function. A reviewer says which of its
policies is answered by which check, and gives the policy its id and the
clause it cites. This module only names the checks.
"""

from bugflow.shared.domain.models.call_record import NANODOLLARS

#: The check that finds dashes used as punctuation.
EM_DASH_CHECK = "em-dash"

#: Every check this server can run.
CHECKS: tuple[str, ...] = (EM_DASH_CHECK,)

#: What one run of a check is recorded as having cost, in nanodollars.
#: Nobody has measured it. The figure is a placeholder.
#:
#: It is not zero, for two reasons. A cost of zero reads as a policy
#: that did not run. And a policy that costs nothing could run when the
#: allowance is used up, while a judged policy was refused.
CHECKED_COST_NANODOLLARS = 10

#: The same figure in dollars, for reporting. Sums are done on the
#: nanodollars.
CHECKED_COST_USD = float(CHECKED_COST_NANODOLLARS / NANODOLLARS)
