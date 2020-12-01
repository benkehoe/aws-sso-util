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

import re
from collections import namedtuple
import logging

import boto3
import aws_error_utils

import click

from aws_sso_lib.lookup import Ids
from aws_sso_lib.assignments import _list_assignments, Assignment

from .utils import configure_logging

LOGGER = logging.getLogger(__name__)

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
@click.option("--instance-arn", "--ins", metavar="ARN")
@click.option("--identity-store-id", "--id-store", metavar="ID")

@click.option("--profile", metavar="PROFILE_NAME", help="Use a specific AWS profile")

@click.option("--group", "-g", "group_values", multiple=True, default=[], metavar="GROUP", help="Group ID or display name")
@click.option("--user", "-u", "user_values", multiple=True, default=[], metavar="USER", help="User ID or user name")
@click.option("--permission-set", "-p", "permission_set_values", multiple=True, default=[], metavar="PERM_SET", help="Permission set ARN, ID, or name")
@click.option("--account", "-a", "account_values", multiple=True, default=[], metavar="ACCOUNT", help="Account ID or name")
@click.option("--ou", "ou_values", multiple=True, default=[], metavar="ID", help="Organizations OU or root ID")
@click.option("--ou-recursive/--ou-not-recursive", help="Include accounts of child OUs when using --ou")

@click.option("--lookup-names/--no-lookup-names", default=True, help="Look up names for principals, permission sets, and accounts")

@click.option("--show-id/--hide-id", default=False, help="Print SSO instance/identity store id being used")
@click.option("--separator", "--sep", default=",", metavar="SEP", help="Field separator for output")
@click.option("--header/--no-header", default=True, help="Include or supress the header row")
@click.option("--arn-style", type=click.Choice(["arn", "id"]), default="arn", envvar="AWS_SSO_UTIL_ASSIGNMENTS_ARN_STYLE", help="Full ARN or only ID")
@click.option("--verbose", "-v", count=True)
def assignments(
        instance_arn,
        identity_store_id,
        profile,
        group_values,
        user_values,
        permission_set_values,
        account_values,
        ou_values,
        ou_recursive,
        lookup_names,
        show_id,
        separator,
        header,
        arn_style,
        verbose):
    """Retrieve assignments from AWS SSO

    You can filter by principal, permission set, and target."""

    configure_logging(LOGGER, verbose)

    principal = None
    principal_filter = get_principal_filter(group_values, user_values)

    ps_pattern = r"^(arn:aws:sso:::permissionSet/)?((sso)?ins-[0-9a-f]+/)?ps-[0-9a-f]+$"
    if all(re.match(ps_pattern, ps) for ps in permission_set_values):
        LOGGER.debug(f"Using specific permission set ids")
        permission_set = permission_set_values
        permission_set_filter = None
    else:
        if permission_set_values:
            LOGGER.debug("Filtering permission sets")
        permission_set = None
        permission_set_filter = get_permission_set_filter(permission_set_values)

    if account_values and all(re.match(r"^\d{12}$", a) for a in account_values):
        if ou_values:
            LOGGER.debug(f"Using specific accounts and OUs")
        else:
            LOGGER.debug(f"Using specific accounts")
        target = account_values + ou_values
        target_filter = None
    elif account_values and ou_values:
        raise click.UsageError("Cannot provide account names and OUs")
    elif ou_values:
        target = ou_values
        target_filter =  None
    else:
        LOGGER.debug("Filtering account values")
        target = None
        target_filter = get_target_filter(account_values)

    session = boto3.Session(profile_name=profile)

    ids = Ids(lambda: session, instance_arn, identity_store_id)
    ids.print_on_fetch = show_id

    assignments_iterator = _list_assignments(
        session,
        ids,
        principal=principal,
        principal_filter=principal_filter,
        permission_set=permission_set,
        permission_set_filter=permission_set_filter,
        target=target,
        target_filter=target_filter,
        get_principal_names=lookup_names,
        get_permission_set_names=lookup_names,
        get_target_names=lookup_names,
        ou_recursive=ou_recursive)

    if header:
        fields = list(Assignment._fields)
        if arn_style == "id":
            fields[fields.index("instance_arn")] = "instance_id"
            fields[fields.index("permission_set_arn")] = "permission_set_id"
        print(separator.join(fields))

    for assignment in assignments_iterator: #lookup_assignments(session, ids, principal_filter, permission_set_filter, target_filter):
        if arn_style == "id":
            assignment = assignment._replace(instance_arn=assignment.instance_arn.split("/", 1)[-1])
            assignment = assignment._replace(permission_set_arn=assignment.permission_set_arn.split("/", 2)[-1])
        print(separator.join(v or "" for v in assignment))

if __name__ == "__main__":
    assignments(prog_name="python -m aws_sso_util.assignments")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
