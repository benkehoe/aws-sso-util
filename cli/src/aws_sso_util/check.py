import logging
import sys
import re
import traceback

import click

from aws_sso_lib.sso import list_available_accounts, list_available_roles, login
from aws_sso_lib.config import find_instances, SSOInstance

from .utils import configure_logging, GetInstanceError

from .login import LOGIN_DEFAULT_START_URL_VARS, LOGIN_DEFAULT_SSO_REGION_VARS
from .configure_profile import CONFIGURE_DEFAULT_START_URL_VARS, CONFIGURE_DEFAULT_SSO_REGION_VARS

LOGGER = logging.getLogger(__name__)

def get_specifier_parts(specifier):
    parts = []
    if specifier.start_url:
        parts.extend([
            f"{specifier.start_url}",
            f"from {specifier.start_url_source}"
        ])
    if specifier.region:
        if specifier.start_url:
            parts.append("and")
        parts.extend([
            "region",
            f"{specifier.region}",
            f"from {specifier.region_source}"
        ])
    return parts

def join_parts(parts):
    return re.sub(r" (?=[,\(\)])", "", " ".join(parts))

@click.command()
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account", "-a")
@click.option("--role-name", "-r")
@click.option("--command", type=click.Choice(["default", "configure", "login"]), default="default")
@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--quiet", "-q", is_flag=True)
@click.option("--verbose", "-v", count=True)
def check(
        sso_start_url,
        sso_region,
        account,
        role_name,
        command,
        force_refresh,
        quiet,
        verbose):
    """Debug AWS SSO configuration and access.
    """

    if quiet:
        logging.disable(logging.CRITICAL)
    else:
        configure_logging(LOGGER, verbose)

    if command == "login":
        start_url_vars = LOGIN_DEFAULT_START_URL_VARS
        region_vars = LOGIN_DEFAULT_SSO_REGION_VARS
    elif command == "configure":
        start_url_vars = CONFIGURE_DEFAULT_START_URL_VARS
        region_vars = CONFIGURE_DEFAULT_SSO_REGION_VARS
    else:
        start_url_vars = None
        region_vars = None

    instances, specifier, all_instances = find_instances(
        start_url=sso_start_url,
        start_url_source="CLI input",
        region=sso_region,
        region_source="CLI input",
        start_url_vars=start_url_vars,
        region_vars=region_vars
    )

    if not instances:
        if not all_instances:
            parts = [
                "Did not find AWS SSO instance"
            ]
            if specifier:
                parts.append("(with specifier")
                parts.extend(get_specifier_parts(specifier))
                parts.append(")")
            LOGGER.error(join_parts(parts))
            sys.exit(101)
        else:
            parts = [
                "Did not find AWS SSO instance matching specifier"
            ]
            parts.extend(get_specifier_parts(specifier))
            parts.append(f"from instances {SSOInstance.to_strs(all_instances, region=True)}")
            LOGGER.error(join_parts(parts))
            sys.exit(102)

    if len(instances) > 1:
        parts = [
            f"Did not find unique AWS SSO instance. Found {len(instances)} instances"
        ]
        if not specifier:
            parts.append("with no specifier:")
            parts.append(f"{SSOInstance.to_strs(all_instances, region=True)}")
        else:
            parts.append("matching specifier")
            parts.extend(get_specifier_parts(specifier))
            parts.append(f", from instances {SSOInstance.to_strs(all_instances, region=True)}")
        LOGGER.error(join_parts(parts))
        sys.exit(103)

    instance = instances[0]

    if not (account or role_name):
        parts = [
            f"AWS SSO instance",
            f"start URL {instance.start_url} from {instance.start_url_source}",
            f"and",
            f"region {instance.region} from {instance.region_source}"
        ]
        if specifier:
            parts.append(", from specifier")
            if specifier.start_url:
                parts.extend([
                    f"{specifier.start_url}",
                    f"from {specifier.start_url_source}"
                ])
            if specifier.region:
                if specifier.start_url:
                    parts.append("and")
                parts.extend([
                    "region",
                    f"{specifier.region}",
                    f"from {specifier.region_source}"
                ])
        if len(all_instances) > 1:
            parts.append(f", from instances {SSOInstance.to_strs(all_instances, region=True)}")
        LOGGER.info(join_parts(parts))
        return

    LOGGER.info(f"AWS SSO instance: {instance.start_url} ({instance.region})")

    try:
        token = login(instance.start_url, instance.region, force_refresh=force_refresh)
    except Exception as e:
        LOGGER.exception(f"Exception during login")
        sys.exit(201)
    print(f"Token expiration: {token['expiresAt']}")

    if not account:
        accounts = {}
        for account_id, account_name, available_role_name in list_available_roles(instance.start_url, instance.region):
            if account_id in accounts:
                continue
            if role_name == available_role_name:
                LOGGER.debug(f"Found role in account: {account_id} ({account_name})")
                accounts[account_id] = account_name
        if not accounts:
            LOGGER.error(f"No access for {role_name}")
            sys.exit(203)

        account_strs = ", ".join("{} ({})".format(id, name) for id, name in accounts.items())

        LOGGER.info(f"Access found for {role_name} in {account_strs}")
    else:
        for account_id, account_name in list_available_accounts(instance.start_url, instance.region):
            if account in [account_id, account_name]:
                LOGGER.debug(f"Found account: {account_id} ({account_name})")
                break
        else:
            LOGGER.error(f"No access found for {account}")
            sys.exit(202)

        role_names = [
            available_role_name
            for _, _, available_role_name
            in list_available_roles(instance.start_url, instance.region, account_id=account_id)
        ]
        LOGGER.debug(f"Roles in account {account}: {', '.join(role_names)}")

        if not role_names:
            LOGGER.error(f"No access found for {account}")
            sys.exit(202)

        if role_name:
            if role_name not in role_names:
                LOGGER.error(f"No access found for {role_name} in account {account_id} ({account_name})")
                sys.exit(204)
            LOGGER.info(f"Access found for {role_name} in account {account_id} ({account_name})")
        else:
            LOGGER.info(f"Access found for account {account_id} ({account_name}): {', '.join(role_names)}")

if __name__ == "__main__":
    roles(prog_name="python -m aws_sso_util.check")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
