# Exception types shared by the JAS import skills.
from __future__ import annotations


# Raised when a requested job reference number has no matching JAS records page.
class JobNotFoundError(ValueError):
    """Indicates the requested refno does not exist on the JAS system."""


# Raised when the browser reached the sign-in page instead of the records page on a site that
# requires a login.
#
# Deliberately distinct from JobNotFoundError: a logged-out run lands on the identity provider's
# page, which parses as "no job" — and reporting that as a missing job sends HR to look for a job
# that was never the problem. The two need different instructions, so they are different types.
class SiteLoginRequiredError(ValueError):
    """Indicates the run reached the sign-in page instead of the requested records page."""


__all__ = ["JobNotFoundError", "SiteLoginRequiredError"]
