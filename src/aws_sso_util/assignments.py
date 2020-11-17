import re
import numbers
import collections
import logging

import aws_error_utils

from .api_utils import Ids

LOGGER = logging.getLogger(__name__)

_Context = collections.namedtuple("_Context", [
    "session",
    "ids",
    "principal",
    "principal_filter",
    "permission_set",
    "permission_set_filter",
    "target",
    "target_filter",
    "get_principal_names",
    "get_permission_set_names",
    "ou_recursive",
    "cache",
    "filter_cache"
])

def _filter(filter_cache, key, func, args):
    if not func:
        return True
    if key not in filter_cache:
        filter_cache[key] = func(*args)
    return filter_cache[key]

def _process_permission_set(ids, permission_set):
    if not permission_set:
        return None
    if permission_set.startswith("arn"):
        permission_set_arn = permission_set
    elif permission_set.startswith("ssoins-") or permission_set.startswith("ins-"):
        permission_set_arn = f"arn:aws:sso:::permissionSet/{permission_set}"
    elif permission_set.startswith("ps-"):
        permission_set_arn = f"arn:aws:sso:::permissionSet/{ids.instance_id}/{permission_set}"
    else:
        raise TypeError(f"Invalid permission set id {permission_set}")
    return permission_set_arn

def _process_target(target):
    if not target:
        return None
    if isinstance(target, numbers.Number):
        target = str(int(target))
    if isinstance(target, str):
        if re.match(r"^\d+$", target):
            target = target.rjust(12, '0')
            return "AWS_ACCOUNT", target
        else:
            return "AWS_OU", target
    else:
        target_type, target_id = target
        if target_type not in ["AWS_ACCOUNT", "AWS_OU"]:
            raise TypeError(f"Invalid target type {target_type}")
        return target_type, target_id

def _get_account_iterator(context: _Context):
    def target_iterator():
        value = (*context.target, "UNKNOWN")
        if not _filter(context.filter_cache, value[1], context.target_filter, value):
            LOGGER.debug(f"Single account is filtered: {value}")
        else:
            LOGGER.debug(f"Visiting single account: {value}")
            yield value
    return target_iterator

def _get_ou_iterator(context: _Context):
    raise NotImplementedError

def _get_all_accounts_iterator(context: _Context):
    def target_iterator():
        organizations_client = context.session.client("organizations")
        accounts_paginator = organizations_client.get_paginator("list_accounts")
        for response in accounts_paginator.paginate():
            LOGGER.debug(f"ListAccounts page: {response}")
            for account in response["Accounts"]:
                account_id = account["Id"]
                account_name = account["Name"]

                value = ("AWS_ACCOUNT", account_id, account_name)

                if not _filter(context.filter_cache, account_id, context.target_filter, value):
                    LOGGER.debug(f"Account is filtered: {value}")
                    continue

                LOGGER.debug(f"Visiting account: {value}")
                yield value
    return target_iterator

def _get_target_iterator(context: _Context):
    if context.target:
        target_type = context.target[0]
        if target_type == "AWS_ACCOUNT":
            LOGGER.debug(f"Iterating for single account")
            return _get_account_iterator(context)
        elif target_type == "AWS_OU":
            LOGGER.debug(f"Iterating for single OU")
            return _get_ou_iterator(context)
        else:
            raise TypeError(f"Invalid target type {target_type}")
    else:
        LOGGER.debug(f"Iterating for all accounts")
        return _get_all_accounts_iterator(context)

def _get_single_permission_set_iterator(context: _Context):
    permission_set_arn = context.permission_set
    permission_set_id = permission_set_arn.split("/")[-1]

    def permission_set_iterator(target_type, target_id, target_name):
        if not context.get_permission_set_names:
            permission_set_name = "UNKNOWN"
        else:
            sso_admin_client = context.session.client("sso-admin")
            response = sso_admin_client.describe_permission_set(
                InstanceArn=context.ids.instance_arn,
                PermissionSetArn=permission_set_arn
            )
            LOGGER.debug(f"DescribePermissionSet response: {response}")
            permission_set_name = response["PermissionSet"]["Name"]

        if not _filter(context.filter_cache, permission_set_arn, context.permission_set_filter, (permission_set_arn, permission_set_name)):
            LOGGER.debug(f"Single permission set is filtered: {(permission_set_id, permission_set_name)}")
        else:
            LOGGER.debug(f"Visiting single permission set {(permission_set_id, permission_set_name)}")
            yield permission_set_arn, permission_set_id, permission_set_name
    return permission_set_iterator

def _get_all_permission_sets_iterator(context: _Context):
    def permission_set_iterator(target_type, target_id, target_name):
        if target_type != "AWS_ACCOUNT":
            raise TypeError(f"Unsupported target type {target_type}")
        sso_admin_client = context.session.client("sso-admin")
        permission_sets_paginator = sso_admin_client.get_paginator("list_permission_sets_provisioned_to_account")
        for response in permission_sets_paginator.paginate(
                InstanceArn=context.ids.instance_arn,
                AccountId=target_id):
            LOGGER.debug(f"ListPermissionSetsProvisionedToAccount {target_id} page: {response}")
            if "PermissionSets" not in response:
                continue

            for permission_set_arn in response["PermissionSets"]:
                permission_set_id = permission_set_arn.split("/", 2)[-1]
                if not context.get_permission_set_names:
                    permission_set_name = "UNKNOWN"
                else:
                    if permission_set_arn not in context.cache:
                        response = sso_admin_client.describe_permission_set(
                            InstanceArn=context.ids.instance_arn,
                            PermissionSetArn=permission_set_arn
                        )
                        LOGGER.debug(f"DescribePermissionSet response: {response}")
                        context.cache[permission_set_arn] = response["PermissionSet"]["Name"]
                    permission_set_name = context.cache[permission_set_arn]

                if not _filter(context.filter_cache, permission_set_arn, context.permission_set_filter, (permission_set_arn, permission_set_name)):
                    LOGGER.debug(f"Permission set is filtered: {(permission_set_id, permission_set_name)}")
                    continue

                LOGGER.debug(f"Visiting permission set: {(permission_set_id, permission_set_name)}")
                yield permission_set_arn, permission_set_id, permission_set_name
    return permission_set_iterator

def _get_permission_set_iterator(context: _Context):
    if context.permission_set:
        LOGGER.debug("Iterating for a single permission set")
        return _get_single_permission_set_iterator(context)
    else:
        LOGGER.debug("Iterating for all permission sets")
        return _get_all_permission_sets_iterator(context)

def _get_principal_iterator(context: _Context):
    def principal_iterator(
            target_type, target_id, target_name,
            permission_set_arn, permission_set_id, permission_set_name):
        if target_type != "AWS_ACCOUNT":
            raise TypeError(f"Unsupported target type {target_type}")

        sso_admin_client = context.session.client("sso-admin")
        identity_store_client = context.session.client("identitystore")

        assignments_paginator = sso_admin_client.get_paginator("list_account_assignments")
        for response in assignments_paginator.paginate(
                InstanceArn=context.ids.instance_arn,
                AccountId=target_id,
                PermissionSetArn=permission_set_arn):
            LOGGER.debug(f"ListAccountAssignments for {target_id} {permission_set_arn.split('/')[-1]} page: {response}")

            if not response["AccountAssignments"] and not "NextToken" in response:
                LOGGER.debug(f"No assignments for {target_id} {permission_set_arn.split('/')[-1]}")

            for assignment in response["AccountAssignments"]:
                principal_type = assignment["PrincipalType"]
                principal_id = assignment["PrincipalId"]

                if context.principal:
                    if (context.principal[0] != principal_type or context.principal[1] != principal_id):
                        LOGGER.debug(f"Principal {principal_type}:{principal_id} does not match single principal")
                        continue
                    else:
                        LOGGER.debug(f"Found single principal {principal_type}:{principal_id}")

                principal_key = (principal_type, principal_id)
                if not context.get_principal_names:
                    principal_name = "UNKNOWN"
                else:
                    if principal_key not in context.cache:
                        if principal_type == "GROUP":
                            try:
                                response = identity_store_client.describe_group(
                                    IdentityStoreId=context.ids.identity_store_id,
                                    GroupId=principal_id
                                )
                                LOGGER.debug(f"DescribeGroup response: {response}")
                                context.cache[principal_key] = response["DisplayName"]
                            except aws_error_utils.catch_aws_error("ResourceNotFoundException"):
                                context.cache[principal_key] = "UNKNOWN"
                        elif principal_type == "USER":
                            try:
                                response = identity_store_client.describe_user(
                                    IdentityStoreId=context.ids.identity_store_id,
                                    UserId=principal_id
                                )
                                LOGGER.debug(f"DescribeUser response: {response}")
                                context.cache[principal_key] = response["UserName"]
                            except aws_error_utils.catch_aws_error("ResourceNotFoundException"):
                                context.cache[principal_key] = "UNKNOWN"
                        else:
                            raise ValueError(f"Unknown principal type {principal_type}")
                    principal_name = context.cache[principal_key]

                if not _filter(context.filter_cache, principal_key, context.principal_filter, (principal_type, principal_id, principal_name)):
                    if context.principal:
                        LOGGER.debug(f"Single principal is filtered: {principal_type}:{principal_id}")
                    else:
                        LOGGER.debug(f"Principal is filtered: {principal_type}:{principal_id}")
                    continue

                LOGGER.debug(f"Visiting principal: {principal_type}:{principal_id}")
                yield principal_type, principal_id, principal_name
    return principal_iterator

Assignment = collections.namedtuple("Assignment", [
    "principal_type",
    "principal_id",
    "principal_name",
    "permission_set_arn",
    "permission_set_name",
    "target_type",
    "target_id",
    "target_name",
])

def get_assignments(
        session,
        instance_arn=None,
        identity_store_id=None,
        principal=None,
        principal_filter=None,
        permission_set=None,
        permission_set_filter=None,
        target=None,
        target_filter=None,
        get_principal_names=True,
        get_permission_set_names=True,
        ou_recursive=False):
    ids = Ids(lambda: session, instance_arn, identity_store_id)
    ids.suppress_print = True
    return _get_assignments(
        session,
        ids,
        principal=principal,
        principal_filter=principal_filter,
        permission_set=permission_set,
        permission_set_filter=permission_set_filter,
        target=target,
        target_filter=target_filter,
        get_principal_names=get_principal_names,
        get_permission_set_names=get_permission_set_names,
        ou_recursive=ou_recursive,
    )

def _get_assignments(
        session,
        ids,
        principal=None,
        principal_filter=None,
        permission_set=None,
        permission_set_filter=None,
        target=None,
        target_filter=None,
        get_principal_names=True,
        get_permission_set_names=True,
        ou_recursive=False):
    ids.suppress_print = True

    permission_set = _process_permission_set(ids, permission_set)
    target = _process_target(target)

    cache = {}
    filter_cache = {}

    context = _Context(
        session = session,
        ids=ids,
        principal=principal,
        principal_filter=principal_filter,
        permission_set=permission_set,
        permission_set_filter=permission_set_filter,
        target=target,
        target_filter=target_filter,
        get_principal_names=get_principal_names,
        get_permission_set_names=get_permission_set_names,
        ou_recursive=ou_recursive,
        cache=cache,
        filter_cache=filter_cache,
    )

    target_iterator = _get_target_iterator(context)

    permission_set_iterator = _get_permission_set_iterator(context)

    principal_iterator = _get_principal_iterator(context)

    for target_type, target_id, target_name in target_iterator():
        for permission_set_arn, permission_set_id, permission_set_name, in permission_set_iterator(target_type, target_id, target_name):
            for principal_type, principal_id, principal_name in principal_iterator(
                    target_type, target_id, target_name,
                    permission_set_arn, permission_set_id, permission_set_name):

                assignment = Assignment(
                    principal_type,
                    principal_id,
                    principal_name,
                    permission_set_arn,
                    permission_set_name,
                    target_type,
                    target_id,
                    target_name,
                )
                LOGGER.debug(f"Visiting assignment: {assignment}")
                yield assignment

if __name__ == "__main__":
    import boto3
    import sys
    import json

    logging.basicConfig(level=logging.INFO)
    LOGGER.setLevel(logging.DEBUG)

    if len(sys.argv) > 1:
        kwargs = json.loads(sys.argv[1])
    else:
        kwargs = {}

    try:
        session = boto3.Session()
        for value in get_assignments(session, **kwargs):
            print(",".join(value))
    except KeyboardInterrupt:
        pass
