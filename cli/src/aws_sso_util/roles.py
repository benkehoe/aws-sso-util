# Copyright 2022 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import logging
import re
import sys
import json
from collections import namedtuple

import click

from .utils import configure_logging, get_specifier, GetSpecifierError, get_session, GetSessionError, Printer
from .sso import login, list_available_roles

LOGGER = logging.getLogger(__name__)

HEADER_FIELDS = {
    "id": "Account ID",
    "name": "Account name",
    "role": "Role name"
}

@click.command()
@click.option("--session", "session_param", metavar="SESSION_SPECIFIER", help="The specifier for selecting an Identity Center session")
@click.option("--account-id", "-a", "account_values", metavar="ACCOUNT_ID", multiple=True, default=[], help="List roles for a specific account ID, can be specified multiple times")
@click.option("--account", "account_values", multiple=True, hidden=True)
@click.option("--role-name", "-r", "role_name_patterns", metavar="REGEX", multiple=True, default=[], help="Filter roles by a regular expression, can be specified multiple times")
@click.option("--separator", "--sep", metavar="SEP", help="Field separator for output")
@click.option("--header/--no-header", default=True, help="Include or supress the header row")
@click.option("--sort-by", type=click.Choice(["id,role", "name,role", "role,id", "role,name"]), default=None, help="Specify how the output is sorted")
@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--verbose", "-v", count=True)
@click.option("--sso-session", "alternate_session_param", hidden=True)
@click.option("--sso-start-url", "-u", metavar="URL", help="Your Identity Center start URL", hidden=True)
@click.option("--sso-region", metavar="REGION", help="The AWS region your Identity Center instance is deployed in", hidden=True)
def roles(
        session_param,
        account_values,
        role_name_patterns,
        separator,
        header,
        sort_by,
        force_refresh,
        verbose,
        alternate_session_param,
        sso_start_url,
        sso_region):
    """List your available accounts and roles.

    --sso-start-url and --sso-region are not needed if a single value can be found for them in your ~/.aws/config
    or in the environment variables AWS_DEFAULT_SSO_START_URL and AWS_DEFAULT_SSO_REGION.

    You can filter the list by providing account IDs and role name patterns.

    """
    session_param = session_param or alternate_session_param

    configure_logging(LOGGER, verbose)

    if not account_values:
        account_ids = None
        account_filter = lambda id, name: True
    elif all(re.match(r"^\d{12}$", a) for a in account_values):
        account_ids = account_values
        account_filter = lambda id, name: True
    else:
        account_ids = None
        def account_filter(id, name):
            for value in account_values:
                if id.startswith(value) or id.endswith(value) or re.search(value, name):
                    return True
            return False

    if sort_by:
        sort_by_keys = sort_by.split(",")
    elif not separator:
        sort_by_keys = ("name", "role")
    else:
        sort_by_keys = None

    if not sort_by_keys:
        header_field_keys = ("name", "id", "role")
    elif sort_by_keys[0] == "id":
        header_field_keys = ("id", "name", "role")
    elif sort_by_keys[0] == "name":
        header_field_keys = ("name", "id", "role")
    elif sort_by_keys[1] == "id":
        header_field_keys = ("role", "id", "name")
    else:
        header_field_keys = ("role", "name", "id")
    header_fields = [HEADER_FIELDS[k] for k in header_field_keys]
    Row = namedtuple("Row", header_field_keys)

    if sort_by_keys:
        sort_key = lambda v: tuple(getattr(v, key) for key in sort_by_keys)
    else:
        sort_key = None

    try:
        specifier = get_specifier(
            session_param=session_param,
            sso_start_url=sso_start_url,
            sso_region=sso_region
        )
    except GetSpecifierError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)
    
    try:
        session = get_session(specifier=specifier)
    except GetSessionError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    login(session, force_refresh=force_refresh)

    printer = Printer(
        separator=separator,
        default_separator=" ",
        sort_key=sort_key,
        header_fields=header_fields,
        disable_header=not header,
        skip_repeated_values=False,
    )
    printer.print_header_before()

    for account_id, account_name, role_name in list_available_roles(session, account_id=account_ids):
        if not account_filter(account_id, account_name):
            continue
        if role_name_patterns:
            for pattern in role_name_patterns:
                if re.search(pattern, role_name):
                    break
            else:
                continue
        printer.add_row(Row(id=account_id, name=account_name, role=role_name))

    printer.print_after()


if __name__ == "__main__":
    roles(prog_name="python -m aws_sso_util.roles")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
