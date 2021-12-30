import logging
import sys
import os
from datetime import datetime
import shlex
import subprocess

import click

from aws_sso_lib.sso import get_boto3_session, login

from .utils import configure_logging, get_instance, GetInstanceError

LOGGER = logging.getLogger(__name__)

@click.command("run-as", context_settings=dict(
    ignore_unknown_options=True,
))
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account-id", "-a", "account", metavar="ACCOUNT_ID", help="The AWS account", required=True)
@click.option("--role-name", "-r", "role", metavar="ROLE_NAME", help="The SSO role to assume in account", required=True)
@click.option("--region", metavar="REGION", help="The AWS region")
@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--verbose", "-v", count=True)
@click.argument("exec_args", nargs=-1, type=click.UNPROCESSED, required=True)
def run_as(
        sso_start_url,
        sso_region,
        account,
        role,
        region,
        force_refresh,
        verbose,
        exec_args):
    """Run a command as a specific account + role.
    """

    configure_logging(LOGGER, verbose)

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
        )
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    login(instance.start_url, instance.region, force_refresh=force_refresh)

    for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE']:
        os.environ.pop(key, None)

    session = get_boto3_session(
        instance.start_url,
        instance.region,
        account,
        role,
        region=region,
    )

    session_credentials = session.get_credentials()

    read_only_credentials = session_credentials.get_frozen_credentials()
    access_key_id = read_only_credentials.access_key
    secret_access_key = read_only_credentials.secret_key
    session_token = read_only_credentials.token


    expiration = None
    if hasattr(session_credentials, '_expiry_time') and session_credentials._expiry_time:
        if isinstance(session_credentials._expiry_time, datetime):
            expiration = session_credentials._expiry_time
        else:
            LOGGER.debug("Expiration in session credentials is of type {}, not datetime".format(type(expiration)))

    env_vars = {
        'AWS_ACCESS_KEY_ID': access_key_id,
        'AWS_SECRET_ACCESS_KEY': secret_access_key,
    }
    if session_token:
        env_vars['AWS_SESSION_TOKEN'] = session_token
    if expiration:
        env_vars['AWS_CREDENTIALS_EXPIRATION'] = expiration.strftime('%Y-%m-%dT%H:%M:%SZ')

    if session.region_name:
        env_vars['AWS_DEFAULT_REGION'] = session.region_name

    os.environ.update(env_vars)

    command = ' '.join(shlex.quote(arg) for arg in exec_args)
    result = subprocess.run(command, shell=True)
    sys.exit(result.returncode)

if __name__ == "__main__":
    run_as(prog_name="python -m aws_sso_util.run_as")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
