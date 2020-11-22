# Copyright 2020 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import logging

import boto3
import aws_error_utils

LOGGER = logging.getLogger(__name__)

from . import format as _format

def _init_cache(cache, key, type):
    if key not in cache:
        cache[key] = type()

class LookupError(Exception):
    pass

class Ids:
    def __init__(self, session, instance_arn=None, identity_store_id=None):
        if isinstance(session, boto3.Session):
            session_fetcher = lambda: session
        elif callable(session):
            session_fetcher = session
        else:
            raise TypeError("Session must be a boto3 Session or a callable returning one")

        if instance_arn and not instance_arn.startswith("arn:"):
            instance_arn = f"arn:aws:sso:::instance/{instance_arn}"

        self._session_fetcher = session_fetcher
        self._client = None
        self._instance_arn = instance_arn
        self._instance_arn_printed = False
        self._identity_store_id = identity_store_id
        self._identity_store_id_printed = False
        self.print_on_fetch = None

    def _get_client(self):
        if not self._client:
            self._client = self._session_fetcher().client("sso-admin")
        return self._client

    def _print(self, message):
        LOGGER.info(message)
        if self.print_on_fetch:
            print(message)

    def instance_arn_matches(self, instance):
        if not self._instance_arn:
            return True
        if instance and not instance.startswith("arn:"):
            instance = f"arn:aws:sso:::instance/{instance}"
        return instance == self._instance_arn

    @property
    def instance_arn(self):
        if self._instance_arn:
            if not self._instance_arn_printed:
                self._print("Using SSO instance {}".format(self._instance_arn.split('/')[-1]))
                self._instance_arn_printed = True
            return self._instance_arn
        response = self._get_client().list_instances()
        if len(response["Instances"]) == 0:
            raise LookupError("No SSO instance found, please specify with --instance-arn")
        elif len(response["Instances"]) > 1:
            raise LookupError("{} SSO instances found, please specify with --instance-arn".format(len(response["Instances"])))
        else:
            instance_arn = response["Instances"][0]["InstanceArn"]
            self._instance_arn = instance_arn
            self._print("Using SSO instance {}".format(self._instance_arn.split("/")[-1]))
            self._instance_arn_printed = True
            identity_store_id = response["Instances"][0]["IdentityStoreId"]
            if self._identity_store_id and self._identity_store_id != identity_store_id:
                raise LookupError("SSO instance identity store {} does not match given identity store {}".format(identity_store_id, self._identity_store_id))
            else:
                self._identity_store_id = identity_store_id
        return self._instance_arn

    @property
    def instance_id(self):
        return self.instance_arn.split("/", 1)[1]

    @property
    def identity_store_id(self):
        if self._identity_store_id:
            if not self._identity_store_id_printed:
                self._print("Using SSO identity store {}".format(self._identity_store_id))
                self._identity_store_id_printed = True
            return self._identity_store_id
        response = self._get_client().list_instances()
        if len(response["Instances"]) == 0:
            raise LookupError("No SSO instance found, please specify identity store with --identity-store-id or instance with --instance-arn")
        elif len(response["Instances"]) > 1:
            raise LookupError("{} SSO instances found, please specify identity store with --identity-store-id or instance with --instance-arn".format(len(response["Instances"])))
        else:
            identity_store_id = response["Instances"][0]["IdentityStoreId"]
            self._identity_store_id = identity_store_id
            self._print("Using SSO identity store {}".format(self._identity_store_id))
            self._identity_store_id_printed = True
            instance_arn = response["Instances"][0]["InstanceArn"]
            instance_id = instance_arn.split("/")[-1]
            if self._instance_arn and self._instance_arn != instance_arn:
                raise LookupError("SSO instance {} does not match given instance {}".format(instance_id, self._instance_arn.split("/")[-1]))
            else:
                self._instance_arn = instance_arn
        return self._identity_store_id

def _acct_str(account):
    if "Name" in account:
        return f"{account['Id']}:{account['Name']}"
    else:
         return f"{account['Id']}"

_CACHE_KEY_PREFIX_GROUP_ID = "group#id#"
_CACHE_KEY_PREFIX_GROUP_NAME = "group#name#"

def lookup_group_by_id(session: boto3.Session, ids: Ids, group_id, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_id = f"{_CACHE_KEY_PREFIX_GROUP_ID}{group_id}"
    if cache_key_id in cache:
        LOGGER.debug(f"Found group {group_id} in cache")
        group = cache[cache_key_id]
        if isinstance(group, LookupError):
            raise group
        return group

    LOGGER.debug(f"Looking up group {group_id}")

    identity_store = session.client('identitystore')
    try:
        group = identity_store.describe_group(IdentityStoreId=ids.identity_store_id, GroupId=group_id)
        group.pop("ResponseMetadata", None)
    except aws_error_utils.catch_aws_error("ResourceNotFoundException") as e:
        err = LookupError(e)
        cache[cache_key_id] = err
        raise err

    group_name = group["DisplayName"]

    cache_key_name = f"{_CACHE_KEY_PREFIX_GROUP_NAME}{group_name}"
    cache[cache_key_id] = group
    cache[cache_key_name] = group

    return group

def lookup_group_by_name(session: boto3.Session, ids: Ids, group_name, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_name = f"{_CACHE_KEY_PREFIX_GROUP_NAME}{group_name}"
    if cache_key_name in cache:
        LOGGER.debug(f"Found group {group_name} in cache")
        group = cache[cache_key_name]
        if isinstance(group, LookupError):
            raise group
        return group

    LOGGER.debug(f"Looking up group {group_name}")

    identity_store = session.client('identitystore')
    filters=[{'AttributePath': 'DisplayName', 'AttributeValue': group_name}]
    response = identity_store.list_groups(IdentityStoreId=ids.identity_store_id, Filters=filters)

    if len(response['Groups']) == 0:
        err = LookupError("No group named {} found".format(group_name))
        cache[cache_key_name] = err
        raise err
    elif len(response['Groups']) > 1:
        err = LookupError("{} groups named {} found".format(len(response['Groups']), group_name))
        cache[cache_key_name] = err
        raise err
    group = response['Groups'][0]
    group_id = group['GroupId']

    cache_key_id = f"{_CACHE_KEY_PREFIX_GROUP_ID}{group_id}"
    cache[cache_key_id] = group
    cache[cache_key_name] = group

    return group

_CACHE_KEY_PREFIX_USER_ID = "user#id#"
_CACHE_KEY_PREFIX_USER_NAME = "user#name#"

def lookup_user_by_id(session: boto3.Session, ids: Ids, user_id, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_id = f"{_CACHE_KEY_PREFIX_USER_ID}{user_id}"
    if cache_key_id in cache:
        LOGGER.debug(f"Found user {user_id} in cache")
        user = cache[cache_key_id]
        if isinstance(user, LookupError):
            raise user
        return user

    LOGGER.debug(f"Looking up user {user_id}")

    identity_store = session.client('identitystore')
    try:
        user = identity_store.describe_user(IdentityStoreId=ids.identity_store_id, UserId=user_id)
        user.pop("ResponseMetadata", None)
    except aws_error_utils.catch_aws_error("ResourceNotFoundException") as e:
        err = LookupError(e)
        cache[cache_key_id] = err
        raise err

    user_name = user["UserName"]

    cache_key_name = f"{_CACHE_KEY_PREFIX_USER_NAME}{user_name}"
    cache[cache_key_id] = user
    cache[cache_key_name] = user

    return user

def lookup_user_by_name(session: boto3.Session, ids: Ids, user_name, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_name = f"{_CACHE_KEY_PREFIX_USER_NAME}{user_name}"

    if cache_key_name in cache:
        LOGGER.debug(f"Found user {user_name} in cache")
        user = cache[cache_key_name]
        if isinstance(user, LookupError):
            raise user
        return user

    LOGGER.debug(f"Looking up user {user_name}")

    identity_store = session.client('identitystore')
    filters=[{'AttributePath': 'UserName', 'AttributeValue': user_name}]
    response = identity_store.list_users(IdentityStoreId=ids.identity_store_id, Filters=filters)

    if len(response['Users']) == 0:
        err = LookupError("No user named {} found".format(user_name))
        cache[cache_key_name] = err
        raise err
    elif len(response['Users']) > 1:
        err = LookupError("{} users named {} found".format(len(response['Users']), user_name))
        cache[cache_key_name] = err
        raise err

    user = response['Users'][0]
    user_id = user["UserId"]

    cache_key_id = f"{_CACHE_KEY_PREFIX_USER_ID}{user_id}"
    cache[cache_key_id] = user
    cache[cache_key_name] = user

    return user

_CACHE_KEY_PREFIX_PERMISSION_SET_ARN = "ps#arn#"
_CACHE_KEY_PREFIX_PERMISSION_SET_NAME = "ps#name#"

def lookup_permission_set_by_id(session: boto3.Session, ids: Ids, permission_set_id, *, cache=None):
    if cache is None:
        cache = {}

    permission_set_arn = _format.format_permission_set_arn(ids, permission_set_id, raise_on_unknown=True)

    cache_key_arn = f"{_CACHE_KEY_PREFIX_PERMISSION_SET_ARN}{permission_set_arn}"

    if cache_key_arn in cache:
        LOGGER.debug(f"Found permission set {permission_set_id} in cache")
        ps = cache[cache_key_arn]
        if isinstance(ps, LookupError):
            raise ps
        return ps

    LOGGER.debug(f"Looking up permission set {permission_set_id}")

    sso = session.client("sso-admin")

    try:
        ps = sso.describe_permission_set(InstanceArn=ids.instance_arn, PermissionSetArn=permission_set_arn)["PermissionSet"]
    except aws_error_utils.catch_aws_error("ResourceNotFoundException") as e:
        err = LookupError(e)
        cache[cache_key_arn] = err
        raise err

    cache_key_name = f"{_CACHE_KEY_PREFIX_PERMISSION_SET_NAME}{ps['Name']}"

    cache[cache_key_arn] = ps
    cache[cache_key_name] = ps

    return ps

def lookup_permission_set_by_name(session: boto3.Session, ids: Ids, permission_set_name, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_name = f"{_CACHE_KEY_PREFIX_PERMISSION_SET_NAME}{permission_set_name}"

    if cache_key_name in cache:
        LOGGER.debug(f"Found permission set {permission_set_name} in cache")
        ps = cache[cache_key_name]
        if isinstance(ps, LookupError):
            raise ps
        return ps

    LOGGER.debug(f"Looking up permission set {permission_set_name}")

    found_permission_set = None
    sso = session.client("sso-admin")
    paginator = sso.get_paginator('list_permission_sets')
    for ind, response in enumerate(paginator.paginate(InstanceArn=ids.instance_arn)):
        LOGGER.debug(f"ListPermissionSets page {ind+1}: {', '.join(response['PermissionSets'])}")
        for permission_set_arn in response['PermissionSets']:
            ps = sso.describe_permission_set(InstanceArn=ids.instance_arn, PermissionSetArn=permission_set_arn)["PermissionSet"]
            LOGGER.debug(f"PermissionSet {permission_set_arn} has name {ps['Name']}")

            ps_cache_key_arn = f"{_CACHE_KEY_PREFIX_PERMISSION_SET_ARN}{permission_set_arn}"
            ps_cache_key_name = f"{_CACHE_KEY_PREFIX_PERMISSION_SET_NAME}{ps['Name']}"

            cache[ps_cache_key_arn] = ps
            cache[ps_cache_key_name] = ps

            if ps["Name"] == permission_set_name:
                found_permission_set = ps
        if found_permission_set:
            break
    else:
        err = LookupError("No permission set named {} found".format(permission_set_name))
        cache[cache_key_name] = err
        raise err

    return found_permission_set

_CACHE_KEY_PREFIX_ACCOUNT_ID = "account#id#"
_CACHE_KEY_PREFIX_ACCOUNT_NAME = "account#name#"

def lookup_account_by_id(session, account_id, *, cache=None):
    if cache is None:
        cache = {}

    account_id = _format.format_account_id(account_id)

    cache_key_id = f"{_CACHE_KEY_PREFIX_ACCOUNT_ID}{account_id}"

    if cache_key_id in cache:
        LOGGER.debug(f"Found account {account_id} in cache")
        account = cache[cache_key_id]
        if isinstance(account, LookupError):
            raise account
        return account

    LOGGER.debug(f"Looking up account {account_id}")

    organizations = session.client("organizations")
    try:
        account = organizations.describe_account(AccountId=account_id)["Account"]
    except aws_error_utils.catch_aws_error("AccountNotFoundException") as e:
        err = LookupError(e)
        cache[cache_key_id] = err
        raise err

    account_name = account["Name"]

    cache_key_name = f"{_CACHE_KEY_PREFIX_ACCOUNT_NAME}{account_name}"

    cache[cache_key_id] = account
    cache[cache_key_name] = account

    return account

def lookup_account_by_name(session, account_name, *, cache=None):
    if cache is None:
        cache = {}

    cache_key_name = f"{_CACHE_KEY_PREFIX_ACCOUNT_NAME}{account_name}"

    if cache_key_name in cache:
        LOGGER.debug(f"Found account {account_name} in cache")
        account = cache[cache_key_name]
        if isinstance(account, LookupError):
            raise account
        return account

    LOGGER.debug(f"Looking up account {account_name}")

    found_account = None
    organizations = session.client("organizations")
    paginator = organizations.get_paginator('list_accounts')
    for ind, response in enumerate(paginator.paginate()):
        LOGGER.debug(f"ListAccounts page {ind+1}: {', '.join(a['Name'] for a in response['Accounts'] if 'Name' in a)}")
        for account in response["Accounts"]:
            acct_cache_key_id = f"{_CACHE_KEY_PREFIX_ACCOUNT_ID}{account['Id']}"
            cache[acct_cache_key_id] = account

            if 'Name' in account:
                acct_cache_key_name = f"{_CACHE_KEY_PREFIX_ACCOUNT_NAME}{account['Name']}"
                cache[acct_cache_key_name] = account

            if account.get("Name") == account_name:
                found_account = account
        if found_account:
            break
    else:
        err = LookupError("No account named {} found".format(account_name))
        cache[cache_key_name] = err
        raise err

    return found_account

def lookup_accounts_for_ou(session, ou, *, recursive, refresh=False, cache=None):
    if cache is None:
        cache = {}

    ou_type = "root" if ou.startswith("r-") else "OU"

    ou_children_key = f"{ou}#children"
    ou_accounts_key = f"{ou}#accounts"

    accounts = []

    if refresh or ou_accounts_key not in cache:
        LOGGER.info(f"Retrieving accounts for {ou_type} {ou}")
        client = session.client("organizations")

        paginator = client.get_paginator("list_accounts_for_parent")
        for ind, response in enumerate(paginator.paginate(ParentId=ou)):
            _init_cache(cache, ou_accounts_key, list)
            if not response["Accounts"]:
                LOGGER.debug(f"No accounts directly in {ou}")
                continue
            acct_strs = [_acct_str(a) for a in response["Accounts"]]
            LOGGER.debug(f"ListAccountsPage page {ind+1} for {ou}: {', '.join(acct_strs)}")
            for account in response["Accounts"]:
                cache[ou_accounts_key].append(account)
                yield account
    else:
        acct_strs = [_acct_str(a) for a in cache[ou_accounts_key]]
        if acct_strs:
            LOGGER.debug(f"Loaded cached accounts for {ou_type} {ou}: {', '.join(acct_strs)}")
        else:
            LOGGER.debug(f"Loaded cached accounts for {ou_type} {ou}: (empty list)")
        for account in cache[ou_accounts_key]:
            yield account

    if recursive:
        if recursive is True:
            child_recursive = True
        else:
            child_recursive = recursive - 1

        if refresh or ou_children_key not in cache:
            LOGGER.info(f"Processing child OUs for {ou_type} {ou}")
            client = session.client("organizations")

            paginator = client.get_paginator("list_organizational_units_for_parent")
            for ind, response in enumerate(paginator.paginate(ParentId=ou)):
                _init_cache(cache, ou_children_key, list)
                if not response["OrganizationalUnits"]:
                    LOGGER.debug(f"No child OUs in {ou}")
                    continue
                sub_ous = [data["Id"] for data in response["OrganizationalUnits"]]
                LOGGER.debug(f"ListOrganizationalUnitsForParent page {ind+1} for {ou}: {', '.join(sub_ous)}")
                for sub_ou_id in sub_ous:
                    cache[ou_children_key].append(sub_ou_id)
                    for account in lookup_accounts_for_ou(session, sub_ou_id, recursive=child_recursive, refresh=refresh, cache=cache):
                        yield account
        else:
            sub_ous = cache[ou_children_key]
            if sub_ous:
                LOGGER.debug(f"Loaded cached child OUs for {ou_type} {ou}: {', '.join(sub_ous)}")
            else:
                LOGGER.debug(f"Loaded cached child OUs for {ou_type} {ou}: (empty list)")
            for sub_ou_id in sub_ous:
                for account in lookup_accounts_for_ou(session, sub_ou_id, recursive=child_recursive, refresh=refresh, cache=cache):
                    yield account

    return accounts

