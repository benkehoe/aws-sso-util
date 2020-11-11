import re
from collections import namedtuple

import boto3
import aws_error_utils

import click

from ..api_utils import Ids

def get_principal_filter(group_values, user_values):
    def filter(type, id, name):
        if not (group_values or user_values):
            return True
        if type == "GROUP":
            for value in group_values:
                if id == value or re.search(value, name):
                    return True
        elif type == "USER":
            for value in user_values:
                if id == value or re.search(value, name):
                    return True
        else:
            raise ValueError(f"Unknown principal type {type}")
    return filter

def get_permission_set_filter(values):
    def filter(arn, name):
        if not values:
            return True
        for value in values:
            if arn == value:
                return True
            if arn.split("/", 1)[1] == value:
                return True
            if arn.split("/", 2)[2] == value:
                return True
            if re.search(value, name):
                return True
        return False
    return filter

def get_target_filter(values):
    def filter(type, id, name):
        if type != "AWS_ACCOUNT":
            return True
        if not values:
            return True
        for value in values:
            if id.startswith(value) or id.endswith(value) or re.search(value, name):
                return True
        return False
    return filter

@click.command()
@click.option("--instance-arn", "--ins")
@click.option("--identity-store-id", "--ids")

@click.option("--group", "-g", "group_values", multiple=True, default=[])
@click.option("--user", "-u", "user_values", multiple=True, default=[])
@click.option("--permission-set", "-p", "permission_set_values", multiple=True, default=[])
@click.option("--account", "-a", "account_values", multiple=True, default=[])

@click.option('--show-id/--hide-id', default=False, help='Print SSO instance/identity store id being used')
@click.option('--separator', '--sep', default=',')
def assignments(
        instance_arn,
        identity_store_id,
        group_values,
        user_values,
        permission_set_values,
        account_values,
        show_id,
        separator):
    session = boto3.Session()

    ids = Ids(session, instance_arn, identity_store_id)
    ids.suppress_print = not show_id

    principal_filter = get_principal_filter(group_values, user_values)
    permission_set_filter = get_permission_set_filter(permission_set_values)
    target_filter = get_target_filter(account_values)

    for assignment in lookup_assignments(session, ids, principal_filter, permission_set_filter, target_filter):
        print(f"{separator}".join(assignment))

Assignment = namedtuple("Assignment", [
    "principal_type",
    "principal_id",
    "principal_name",
    "permission_set_id",
    "permission_set_name",
    "target_type",
    "target_id",
    "target_name",
])

def lookup_assignments(session, ids: Ids, principal_filter, permission_set_filter, target_filter):
    organizations_client = session.client("organizations")
    sso_admin_client = session.client("sso-admin")
    identity_store_client = session.client("identitystore")

    cache = {}
    filter_cache = {}

    accounts_paginator = organizations_client.get_paginator("list_accounts")
    for response in accounts_paginator.paginate():
        for account in response["Accounts"]:
            account_id = account["Id"]
            account_name = account["Name"]

            if account_id not in filter_cache:
                filter_cache[account_id] = target_filter("AWS_ACCOUNT", account_id, account_name)
            if not filter_cache[account_id]:
                continue

            permission_sets_paginator = sso_admin_client.get_paginator("list_permission_sets_provisioned_to_account")
            for response in permission_sets_paginator.paginate(
                    InstanceArn=ids.instance_arn,
                    AccountId=account_id):
                if "PermissionSets" not in response:
                    continue

                for permission_set_arn in response["PermissionSets"]:
                    if permission_set_arn not in cache:
                        response = sso_admin_client.describe_permission_set(
                            InstanceArn=ids.instance_arn,
                            PermissionSetArn=permission_set_arn
                        )
                        cache[permission_set_arn] = response["PermissionSet"]["Name"]
                    permission_set_name = cache[permission_set_arn]
                    permission_set_id = permission_set_arn.split("/", 1)[1]

                    if permission_set_arn not in filter_cache:
                        filter_cache[permission_set_arn] = permission_set_filter(permission_set_arn, permission_set_name)
                    if not filter_cache[permission_set_arn]:
                        continue

                    assignments_paginator = sso_admin_client.get_paginator("list_account_assignments")

                    for response in assignments_paginator.paginate(
                            InstanceArn=ids.instance_arn,
                            AccountId=account_id,
                            PermissionSetArn=permission_set_arn):
                        for assignment in response["AccountAssignments"]:
                            principal_type = assignment["PrincipalType"]
                            principal_id = assignment["PrincipalId"]
                            principal_key = (principal_type, principal_id)
                            if principal_key not in cache:
                                if principal_type == "GROUP":
                                    try:
                                        response = identity_store_client.describe_group(
                                            IdentityStoreId=ids.identity_store_id,
                                            GroupId=principal_id
                                        )
                                        cache[principal_key] = response["DisplayName"]
                                    except aws_error_utils.catch_aws_error("ResourceNotFoundException"):
                                        cache[principal_key] = "UNKNOWN"
                                elif principal_type == "USER":
                                    try:
                                        response = identity_store_client.describe_user(
                                            IdentityStoreId=ids.identity_store_id,
                                            UserId=principal_id
                                        )
                                        cache[principal_key] = response["UserName"]
                                    except aws_error_utils.catch_aws_error("ResourceNotFoundException"):
                                        cache[principal_key] = "UNKNOWN"
                                else:
                                    raise ValueError(f"Unknown principal type {principal_type}")
                            principal_name = cache[principal_key]

                            if principal_key not in filter_cache:
                                filter_cache[principal_key] = principal_filter(principal_type, principal_id, principal_name)
                            if not filter_cache[principal_key]:
                                continue

                            yield (
                                principal_type,
                                principal_id,
                                principal_name,
                                permission_set_id,
                                permission_set_name,
                                "AWS_ACCOUNT",
                                account_id,
                                account_name,
                            )

if __name__ == "__main__":
    assignments(prog_name="python -m aws_sso_util.cli.assignments")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
