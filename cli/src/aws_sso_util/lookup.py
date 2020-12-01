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

import argparse
import sys
import os
from collections import namedtuple
import logging

import boto3
from botocore.credentials import JSONFileCache

import click

from aws_sso_lib import lookup as _lookup
from aws_sso_lib import format as _format

from .utils import configure_logging, Printer

LOGGER = logging.getLogger(__name__)

IDS_CACHE_DIR = os.path.expanduser(
    os.path.join("~", ".aws", "cli", "cache")
)

@click.command("lookup")
@click.argument("type", type=click.Choice(["instance", "identity-store", "group", "user", "permission-set"]))
@click.argument("value", nargs=-1)

@click.option("--instance-arn", "--ins", metavar="ARN")
@click.option("--identity-store-id", "--id-store", metavar="ID")

@click.option("--profile", metavar="PROFILE_NAME", help="Use a specific AWS profile")

@click.option("--error-if-not-found", "-e", is_flag=True, help="Do not continue if an entity is not found")

@click.option("--show-id/--hide-id", default=False, help="Print SSO instance/identity store id being used")
@click.option("--separator", "--sep", metavar="SEP", help="Field separator for output")
@click.option("--header/--no-header", help="Include or supress the header row")

@click.option("--permission-set-style", type=click.Choice(["arn", "id"]), default="arn", help="Full ARN or only ID")
@click.option("--verbose", "-v", count=True)
def lookup(
        type,
        value,
        instance_arn,
        identity_store_id,
        profile,
        error_if_not_found,
        show_id,
        separator,
        header,
        permission_set_style,
        verbose):
    """Look up names and ids in AWS SSO"""
    configure_logging(LOGGER, verbose)

    session = boto3.Session(profile_name=profile)

    cache = JSONFileCache(IDS_CACHE_DIR)

    ids = _lookup.Ids(session, instance_arn, identity_store_id, cache=cache)
    ids.print_on_fetch = show_id

    HEADER_FIELDS = {
    "group": ["Name", "Id"],
    "user": ["Name", "Id"],
    "permission-set": ["Name", permission_set_style.upper()],
}

    printer = Printer(
        separator=separator,
        default_separator=" ",
        header_fields=HEADER_FIELDS.get(type),
        disable_header=header,
    )

    try:
        if type == "instance":
            ids.print_on_fetch = False
            print(ids.instance_arn)
        elif type == "identity-store":
            ids.print_on_fetch = False
            print(ids.identity_store_id)
        elif type in "group":
            if not value:
                raise click.UsageError("Group name is required")
            lookup_groups(session, ids, value, printer, error_if_not_found=error_if_not_found)
        elif type == "user":
            if not value:
                raise click.UsageError("User name is required")
            lookup_users(session, ids, value, printer, error_if_not_found=error_if_not_found)
        elif type == "permission-set":
            if not value:
                raise click.UsageError("Permission set name is required")
            if len(value) == 1 and value[0] == ":all":
                lookup_all_permission_sets(session, ids, printer, permission_set_style=permission_set_style)
            else:
                lookup_permission_sets(session, ids, value, printer,
                    permission_set_style=permission_set_style,
                    error_if_not_found=error_if_not_found)

    except _lookup.LookupError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

def lookup_groups(session, ids, groups, printer: Printer, *, error_if_not_found):
    printer.print_header_before()
    for value in groups:
        try:
            group_name = value
            group_id = _lookup.lookup_group_by_name(session, ids, group_name)["GroupId"]
        except _lookup.LookupError as e:
            if error_if_not_found:
                printer.print_after()
                print("Group {} not found".format(group_name), file=sys.stderr)
                sys.exit(1)
            group_id = "NOT_FOUND"
        printer.add_row((group_name, group_id))
    printer.print_after()

def lookup_users(session, ids, users, printer: Printer, *, error_if_not_found):
    printer.print_header_before()
    for value in users:
        try:
            user_name = value
            user_id = _lookup.lookup_user_by_name(session, ids, user_name)["UserId"]
        except _lookup.LookupError as e:
            if error_if_not_found:
                printer.print_after()
                print("User {} not found".format(user_name), file=sys.stderr)
                sys.exit(1)
            user_id = "NOT_FOUND"
        printer.add_row((user_name, user_id))
    printer.print_after()

def lookup_permission_sets(session, ids, permission_sets, printer: Printer, *, permission_set_style, error_if_not_found):
    cache = {}
    printer.print_header_before()
    for value in permission_sets:
        try:
            if any(value.startswith(v) for v in ["arn", "ssoins-", "ins-", "ps-"]):
                permission_set = _lookup.lookup_permission_set_by_id(session, ids, value, cache=cache)
            else:
                permission_set = _lookup.lookup_permission_set_by_name(session, ids, value, cache=cache)
            permission_set_name = permission_set["Name"]
            permission_set_arn = permission_set["PermissionSetArn"]
        except _lookup.LookupError as e:
            if error_if_not_found:
                printer.print_after()
                print("Permission set {} not found".format(value), file=sys.stderr)
                sys.exit(1)
            if any(value.startswith(v) for v in ["arn", "ssoins-", "ins-", "ps-"]):
                permission_set_arn = _format.format_permission_set_arn(ids, value)
                permission_set_name = "UNKNOWN"
            else:
                permission_set_arn = "UNKNOWN"
                permission_set_name = value
        if permission_set_style == "id":
            permission_set_arn = permission_set_arn.rsplit("/", 1)[1]
        printer.add_row((permission_set_name, permission_set_arn))
    printer.print_after()

def lookup_all_permission_sets(session, ids, printer: Printer, *, permission_set_style):
    cache = {}
    printer.print_header_before()
    sso = session.client("sso-admin")
    paginator = sso.get_paginator("list_permission_sets")
    for ind, response in enumerate(paginator.paginate(InstanceArn=ids.instance_arn)):
        LOGGER.debug(f"ListPermissionSets page {ind+1}: {', '.join(response['PermissionSets'])}")
        for permission_set_arn in response["PermissionSets"]:
            permission_set = _lookup.lookup_permission_set_by_id(session, ids, permission_set_arn, cache=cache)
            permission_set_name = permission_set["Name"]
            permission_set_arn = permission_set["PermissionSetArn"]
            if permission_set_style == "id":
                permission_set_arn = permission_set_arn.rsplit("/", 1)[1]
            printer.add_row((permission_set_name, permission_set_arn))
    printer.print_after()

if __name__ == "__main__":
    lookup(prog_name="python -m aws_sso_util.lookup")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
