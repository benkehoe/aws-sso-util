import numbers

from . import utils

class ConfigError(Exception):
    pass

class Config:
    def __init__(self):
        self.instance = None

        self.groups = []
        self.users = []

        self.permission_sets = []

        self.ous = []
        self.accounts = []

    def load(self, data, logger=None):
        logger = utils.get_logger(logger, "config")

        if "Instance" in data:
            self.instance = data["Instance"]

        self.groups.extend(data.get("Groups", []))
        self.users.extend(data.get("Users", []))

        self.permission_sets.extend(data.get("PermissionSets", []))

        self.ous.extend(data.get("OUs", []))
        for account in data.get("Accounts", []):
            if isinstance(account, (str, numbers.Number)):
                account = str(account).rjust(12, '0')
            self.accounts.append(account)

