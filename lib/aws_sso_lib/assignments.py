import re
import numbers
import collections
import logging
from collections.abc import Iterable
import itertools

import aws_error_utils

from .lookup import Ids, lookup_accounts_for_ou
from .format import format_account_id

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
    "get_target_names",
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

def _flatten(list_of_lists):
    return list(itertools.chain(*list_of_lists))

def _is_principal_tuple(principal):
    try:
        return all([
            len(principal) == 2,
            isinstance(principal[0], str),
            principal[0] in ["GROUP", "USER"],
            isinstance(principal[1], str),
        ])
    except:
        return False

def _process_principal(principal):
    if not principal:
        return None
    if isinstance(principal, str):
        return [(None, principal)]
    if _is_principal_tuple(principal):
        return [tuple(principal)]
    else:
        return _flatten(_process_principal(p) for p in principal)

def _process_permission_set(ids, permission_set):
    if not permission_set:
        return None
    if not isinstance(permission_set, str) and isinstance(permission_set, Iterable):
        return _flatten(_process_permission_set(ids, ps) for ps in permission_set)

    if permission_set.startswith("arn"):
        permission_set_arn = permission_set
    elif permission_set.startswith("ssoins-") or permission_set.startswith("ins-"):
        permission_set_arn = f"arn:aws:sso:::permissionSet/{permission_set}"
    elif permission_set.startswith("ps-"):
        permission_set_arn = f"arn:aws:sso:::permissionSet/{ids.instance_id}/{permission_set}"
    else:
        raise TypeError(f"Invalid permission set id {permission_set}")
    return [permission_set_arn]

def _is_target_tuple(target):
    try:
        return all([
            len(target) == 2,
            isinstance(target[0], str),
            target[0] in ["AWS_OU", "AWS_ACCOUNT"],
            isinstance(target[1], str),
        ])
    except:
        return False

def _process_target(target):
    if not target:
        return None
    if isinstance(target, numbers.Number):
        return [("AWS_ACCOUNT", format_account_id(target))]
    if isinstance(target, str):
        if re.match(r"^\d+$", target):
            return [("AWS_ACCOUNT", format_account_id(target))]
        elif re.match(r"^r-[a-z0-9]{4,32}$", target) or re.match(r"^ou-[a-z0-9]{4,32}-[a-z0-9]{8,32}$", target):
            return [("AWS_OU", target)]
        else:
            raise TypeError(f"Invalid target {target}")
    elif _is_target_tuple(target):
        target_type, target_id = target
        if target_type not in ["AWS_ACCOUNT", "AWS_OU"]:
            raise TypeError(f"Invalid target type {target_type}")
        return [(target_type, target_id)]
    else:
        value = _flatten(_process_target(t) for t in target)
        return value

def _get_account_iterator(target, context: _Context):
    def target_iterator():
        target_name = None
        if context.get_target_names:
            organizations_client = context.session.client("organizations")
            account = organizations_client.describe_account(AccountId=target[1])["Account"]
            if account.get("Name"):
                target_name = account["Name"]
        value = (*target, target_name)
        if not _filter(context.filter_cache, value[1], context.target_filter, value):
            LOGGER.debug(f"Account is filtered: {value}")
        else:
            LOGGER.debug(f"Visiting single account: {value}")
            yield value
    return target_iterator

def _get_ou_iterator(target, context: _Context):
    def target_iterator():
        target_name = None
        # if context.get_target_names:
        #     organizations_client = context.session.client("organizations")
        #     ou = organizations_client.describe_organizational_unit(OrganizationalUnitId=target[1])["OrganizationalUnit"]
        #     if ou.get("Name"):
        #         target_name = ou("Name")
        value = (*target, target_name)
        accounts = lookup_accounts_for_ou(context.session, value[1], recursive=context.ou_recursive)
        for account in accounts:
            yield "AWS_ACCOUNT", account["Id"], account["Name"]
    return target_iterator

def _get_single_target_iterator(target, context: _Context):
    target_type = target[0]
    if target_type == "AWS_ACCOUNT":
        return _get_account_iterator(target, context)
    elif target_type == "AWS_OU":
        return _get_ou_iterator(target, context)
    else:
        raise TypeError(f"Invalid target type {target_type}")

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
        iterables = [_get_single_target_iterator(t, context) for t in context.target]
        def target_iterator():
            return itertools.chain(*[it() for it in iterables])
        return target_iterator
    else:
        LOGGER.debug(f"Iterating for all accounts")
        return _get_all_accounts_iterator(context)

def _get_single_permission_set_iterator(permission_set, context: _Context):
    permission_set_arn = permission_set
    permission_set_id = permission_set_arn.split("/")[-1]

    def permission_set_iterator(target_type, target_id, target_name):
        if not context.get_permission_set_names:
            permission_set_name = None
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
                    permission_set_name = None
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
        iterables = [_get_single_permission_set_iterator(ps, context) for ps in context.permission_set]
        def permission_set_iterator(target_type, target_id, target_name):
            return itertools.chain(*[it(target_type, target_id, target_name) for it in iterables])
        return permission_set_iterator
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
                LOGGER.debug(f"Visiting principal {principal_type}:{principal_id}")

                if context.principal:
                    for principal in context.principal:
                        type_matches = (principal[0] is None or principal[0] != principal_type)
                        if type_matches and principal[1] == principal_id:
                            LOGGER.debug(f"Found principal {principal_type}:{principal_id}")
                            break
                    else:
                        LOGGER.debug(f"Principal {principal_type}:{principal_id} does not match principals")
                        continue

                principal_key = (principal_type, principal_id)
                if not context.get_principal_names:
                    principal_name = None
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
                                context.cache[principal_key] = None
                        elif principal_type == "USER":
                            try:
                                response = identity_store_client.describe_user(
                                    IdentityStoreId=context.ids.identity_store_id,
                                    UserId=principal_id
                                )
                                LOGGER.debug(f"DescribeUser response: {response}")
                                context.cache[principal_key] = response["UserName"]
                            except aws_error_utils.catch_aws_error("ResourceNotFoundException"):
                                context.cache[principal_key] = None
                        else:
                            raise ValueError(f"Unknown principal type {principal_type}")
                    principal_name = context.cache[principal_key]

                if not _filter(context.filter_cache, principal_key, context.principal_filter, (principal_type, principal_id, principal_name)):
                    if context.principal:
                        LOGGER.debug(f"Principal is filtered: {principal_type}:{principal_id}")
                    else:
                        LOGGER.debug(f"Principal is filtered: {principal_type}:{principal_id}")
                    continue

                LOGGER.debug(f"Visiting principal: {principal_type}:{principal_id}")
                yield principal_type, principal_id, principal_name
    return principal_iterator

Assignment = collections.namedtuple("Assignment", [
    "instance_arn",
    "principal_type",
    "principal_id",
    "principal_name",
    "permission_set_arn",
    "permission_set_name",
    "target_type",
    "target_id",
    "target_name",
])

def list_assignments(
        session,
        instance_arn=None,
        identity_store_id=None,
        principal=None,
        principal_filter=None,
        permission_set=None,
        permission_set_filter=None,
        target=None,
        target_filter=None,
        get_principal_names=False,
        get_permission_set_names=False,
        get_target_names=False,
        ou_recursive=False):
    """Iterate over AWS SSO assignments.

    Args:
        session (boto3.Session): boto3 session to use
        instance_arn (str): The SSO instance to use, or it will be looked up using ListInstances
        identity_store_id (str): The identity store to use if principal names are being retrieved
            or it will be looked up using ListInstances
        principal: A principal specification or list of principal specifications.
            A principal specification is a principal id or a 2-tuple of principal type and id.
        principal_filter: A callable taking principal type, principal id, and principal name
            (which may be None), and returning True if the principal should be included.
        permission_set: A permission set arn or id, or a list of the same.
        permission_set_filter: A callable taking permission set arn and name (name may be None),
            returning True if the permission set should be included.
        target: A target specification or list of target specifications.
            A target specification is an account or OU id, or a 2-tuple of target type, which
            is either AWS_ACCOUNT or AWS_OU, and target id.
        target_filter: A callable taking target type, target id, and target name
            (which may be None), and returning True if the target should be included.
        get_principal_names (bool): Retrieve names for principals in assignments.
        get_permission_set_names (bool): Retrieve names for permission sets in assignments.
        get_target_names (bool): Retrieve names for targets in assignments.
        ou_recursive (bool): Set to True if an OU is provided as a target to get all accounts
            including those in child OUs.

    Returns:
        An iterator over Assignment namedtuples
    """
    ids = Ids(lambda: session, instance_arn, identity_store_id)

    return _list_assignments(
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
        get_target_names=get_target_names,
        ou_recursive=ou_recursive,
    )

def _list_assignments(
        session,
        ids,
        principal=None,
        principal_filter=None,
        permission_set=None,
        permission_set_filter=None,
        target=None,
        target_filter=None,
        get_principal_names=False,
        get_permission_set_names=False,
        get_target_names=False,
        ou_recursive=False):

    principal = _process_principal(principal)
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
        get_target_names=get_target_names,
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
                    ids.instance_arn,
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

    kwargs = {}
    for v in sys.argv[1:]:
        if hasattr(logging, v):
            LOGGER.setLevel(getattr(logging, v))
        else:
            kwargs = json.loads(v)

    def fil(*args):
        print(args)
        return True

    kwargs["target_filter"] = fil

    try:
        session = boto3.Session()
        print(",".join(Assignment._fields))
        for value in list_assignments(session, **kwargs):
            print(",".join(v or "" for v in value))
    except KeyboardInterrupt:
        pass
