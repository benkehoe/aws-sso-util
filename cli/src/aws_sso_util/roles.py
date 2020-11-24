import logging
import re
import sys
from collections import namedtuple

import click

from aws_sso_lib.sso import list_available_roles, login

from .utils import configure_logging, get_instance, GetInstanceError, Printer

LOGGER = logging.getLogger(__name__)

HEADER_FIELDS = {
    "id": "Account ID",
    "name": "Account name",
    "role": "Role name"
}

@click.command()
@click.option("--sso-start-url", "-u")
@click.option("--sso-region")
@click.option("--account", "-a", "account_values", multiple=True, default=[])
@click.option("--role-name", "-r", "role_name_patterns", multiple=True, default=[])
@click.option("--separator", "--sep")
@click.option("--header/--no-header", default=True)
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

    sort_by_keys = sort_by.split(",") if sort_by else ("name", "role")

    if sort_by_keys[0] == "id":
        header_field_keys = ("id", "name", "role")
    elif sort_by_keys[0] == "name":
        header_field_keys = ("name", "id", "role")
    elif sort_by_keys[1] == "id":
        header_field_keys = ("role", "id", "name")
    else:
        header_field_keys = ("role", "name", "id")
    header_fields = [HEADER_FIELDS[k] for k in header_field_keys]
    Row = namedtuple("Row", header_field_keys)
    if sort_by:
        sort_key = lambda v: tuple(getattr(v, key) for key in sort_by_keys)
    else:
        sort_key = None

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
        )
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    login(instance.start_url, instance.region, force_refresh=force_refresh)

    printer = Printer(
        separator=separator,
        default_separator=" ",
        sort_key=sort_key,
        header_fields=header_fields,
        disable_header=not header,
        skip_repeated_values=False,
    )
    printer.print_header_before()

    for account_id, account_name, role_name in list_available_roles(instance.start_url, instance.region, account_id=account_ids):
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
    roles(prog_name="python -m aws_sso_util.cli.roles")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
