__version__ = '1.2.0'

from .sso import get_boto3_session, login, list_available_accounts, list_available_roles
from .assignments import Assignment, list_assignments
