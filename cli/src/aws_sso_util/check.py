import logging
import sys
import re
import pathlib
import getpass
import traceback
import datetime

import botocore
import click

from aws_sso_lib.sso import get_boto3_session, list_available_accounts, list_available_roles, login, get_token_fetcher, SSO_TOKEN_DIR
from aws_sso_lib.config import find_instances, SSOInstance
from aws_sso_lib.exceptions import AuthenticationNeededError

from .utils import configure_logging, GetInstanceError

from .login import LOGIN_DEFAULT_START_URL_VARS, LOGIN_DEFAULT_SSO_REGION_VARS
from .configure_profile import CONFIGURE_DEFAULT_START_URL_VARS, CONFIGURE_DEFAULT_SSO_REGION_VARS

from . import __version__ as aws_sso_util_version
from aws_sso_lib import __version__ as aws_sso_lib_version

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

def extract_error(e, e_type):
    if isinstance(e, e_type):
        return e
    cause = e.__cause__ or e.__context__
    if isinstance(cause, e_type):
        return cause
    return None

@click.command()
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account-id", "-a", "account", metavar="ACCOUNT_ID", help="Check for access to a particular account")
@click.option("--account", hidden=True)
@click.option("--role-name", "-r", metavar="ROLE_NAME", help="Check for access to a particular role")
@click.option("--command", type=click.Choice(["default", "configure", "login"]), default="default")
@click.option("--instance-details", is_flag=True, default=None, help="Display details of the AWS SSO instance")
@click.option("--skip-token-check", is_flag=True, help="When not checking an account and/or role, do not check token validity")
@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--quiet", "-q", is_flag=True)
@click.option("--verbose", "-v", count=True)
def check(
        sso_start_url,
        sso_region,
        account,
        role_name,
        command,
        instance_details,
        skip_token_check,
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

    if instance_details is None:
        instance_details = not (account or role_name)

    if skip_token_check and (account or role_name):
        raise click.UsageError("Cannot specify --skip-token-check when checking an account and/or role")

    if skip_token_check and force_refresh:
        raise click.UsageError("Cannot specify both --force-refresh and --skip-token-check")

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOGGER.info(f"aws-sso-util: v{aws_sso_util_version}; aws-sso-lib: v{aws_sso_lib_version}; time: {now}")

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

    if instance_details:
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
    else:
        LOGGER.info(f"AWS SSO instance: {instance.start_url} ({instance.region})")

    if not account and not role_name and skip_token_check:
        return

    if force_refresh:
        try:
            token = login(instance.start_url, instance.region, force_refresh=True)
        except Exception as e:
            LOGGER.exception(f"Exception during login")
            sys.exit(201)
    else:
        try:
            session = botocore.session.Session(session_vars={
                'profile': (None, None, None, None),
                'region': (None, None, None, None),
            })
            token_fetcher = get_token_fetcher(session, instance.region, interactive=False)
            token = token_fetcher.fetch_token(instance.start_url)
        except AuthenticationNeededError as e:
            LOGGER.debug(traceback.format_exc())
            LOGGER.error("No valid token found")
            sys.exit(201)
        except Exception as e:
            perm_error = extract_error(e, PermissionError)
            if perm_error:
                coda = ""
                if perm_error.filename:
                    msg = f"located at {perm_error.filename}"
                    try:
                        path = pathlib.Path(perm_error.filename)
                        owner = path.owner()
                        if owner != getpass.getuser():
                            coda = f", it is owned by {owner}"
                    except Exception:
                        pass
                else:
                    msg = f"located in {SSO_TOKEN_DIR} by default"
                LOGGER.debug(traceback.format_exc())
                LOGGER.error(f"The SSO cache file ({msg}) may have the wrong permissions{coda}")
            else:
                LOGGER.exception(f"Exception in loading token")
                os_error = extract_error(e, OSError)
                if os_error and os_error.filename:
                    LOGGER.error(f"The SSO cache file is located at {os_error.filename}")
            sys.exit(201)
    LOGGER.info(f"Token expiration: {token['expiresAt']}")

    if not account and not role_name:
        return
    elif not account:
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
    check(prog_name="python -m aws_sso_util.check")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
