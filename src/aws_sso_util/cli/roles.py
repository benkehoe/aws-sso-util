import logging
import re
import sys

import click

from .utils import configure_logging, get_instance, GetInstanceError
from ..sso import list_available_roles, login

LOGGER = logging.getLogger(__name__)

HEADER_FIELDS = ["Account ID", "Account name", "Role name"]

@click.command()
@click.option("--sso-start-url", "-u")
@click.option("--sso-region")
@click.option("--account", "-a", "account_values", multiple=True, default=[])
@click.option("--role-name", "-r", "role_name_patterns", multiple=True, default=[])
@click.option("--separator", "--sep")
@click.option("--header/--no-header")
@click.option("--sort-by", type=click.Choice(["id,role", "name,role", "role,id", "role,name"]), default=None)
@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--verbose", "-v", count=True)
def roles(
        sso_start_url,
        sso_region,
        account_values,
        role_name_patterns,
        separator,
        header,
        sort_by,
        force_refresh,
        verbose):

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

    print_along = separator and not sort_by

    sort_by_inds = {
        "id": 0,
        "name": 1,
        "role": 2
    }
    sort_by_keys = sort_by.split(",") if sort_by else ("name", "role")
    sort_key = lambda v: tuple(v[sort_by_inds[key]] for key in sort_by_keys)

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
        )
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    login(instance.start_url, instance.region, force_refresh=force_refresh)

    rows = []
    col_2_width = 0

    if separator:
        def print_header(col_2_width):
            print(separator.join(HEADER_FIELDS))
        def print_row(col_2_width, account_id, account_name, role_name):
            print(separator.join([account_id, account_name, role_name]))
    else:
        def print_header(col_2_width):
            fields = HEADER_FIELDS
            col_2_width = max(col_2_width, len(fields[1]))
            print(" ".join([
                fields[0].ljust(12),
                fields[1].ljust(col_2_width),
                fields[2],
            ]))
        def print_row(col_2_width, account_id, account_name, role_name):
            parts = []
            if account_id != prev_account_id:
                parts.extend([
                    account_id,
                    account_name.ljust(col_2_width)
                ])
            else:
                parts.extend([
                    " " * len(account_id),
                    " " * len(col_2_width),
                ])
            parts.append(role_name)
            print(" ".join(parts))


    if header and print_along:
        print_header(col_2_width)

    for account_id, account_name, role_name in list_available_roles(instance.start_url, instance.region, account_id=account_ids):
        if not account_filter(account_id, account_name):
            continue
        if role_name_patterns:
            for pattern in role_name_patterns:
                if re.search(pattern, role_name):
                    break
            else:
                continue
        if print_along:
            print_row(col_2_width, account_id, account_name, role_name)
        else:
            col_2_width = max(col_2_width, len(account_name))
            rows.append((account_id, account_name, role_name))

    if not print_along:
        rows.sort(key=sort_key)
        if header:
            print_header(col_2_width)
        prev_account_id = None
        for account_id, account_name, role_name in rows:
            print_row(col_2_width, account_id, account_name, role_name)


if __name__ == "__main__":
    roles(prog_name="python -m aws_sso_util.cli.roles")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
