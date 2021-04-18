__version__ = '1.7.0' # change in pyproject.toml too

from .sso import get_boto3_session, login, list_available_accounts, list_available_roles
from .assignments import Assignment, list_assignments
