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

import os
import sys
import logging

import botocore
from dateutil.parser import parse
from dateutil.tz import tzlocal, tzutc

import click

import aws_error_utils

from aws_sso_lib.config import find_instances, SSOInstance
from aws_sso_lib.sso import get_token_fetcher
from aws_sso_lib.exceptions import PendingAuthorizationExpiredError

from .utils import configure_logging

LOGGER = logging.getLogger(__name__)

DEFAULT_START_URL_VARS  = ["AWS_SSO_LOGIN_DEFAULT_SSO_START_URL"]
DEFAULT_SSO_REGION_VARS = ["AWS_SSO_LOGIN_DEFAULT_SSO_REGION"]

LOGIN_ALL_VAR = "AWS_SSO_LOGIN_ALL"

UTC_TIME_FORMAT = "%Y-%m-%d %H:%M UTC"
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M %Z"

@click.command()
@click.argument("sso_start_url", required=False)
@click.argument("sso_region", required=False)
@click.option("--profile", metavar="PROFILE_NAME", help="Use a profile to specify AWS SSO instance")
@click.option("--all", "login_all", is_flag=True, default=None, help="Log in to all AWS SSO instances if multiple are found")
@click.option("--force", is_flag=True, help="Force re-authentication")
@click.option("--headless", is_flag=True, default=None, help="Never open a browser window")
@click.option("--verbose", "-v", count=True)
def login(
        sso_start_url,
        sso_region,
        profile,
        login_all,
        force,
        headless,
        verbose):
    """Log in to an AWS SSO instance.

    Note this only needs to be done once for a given SSO instance (i.e., start URL),
    as all profiles sharing the same start URL will share the same login.

    If only one SSO instance/start URL exists in your AWS config file,
    or you've set the environment variables AWS_DEFAULT_SSO_START_URL and AWS_DEFAULT_SSO_REGION,
    you don't need to provide a start URL or region.

    Otherwise, you can provide a full start URL, or a regex for the start URL (usually a substring will work),
    and if this uniquely identifies a start URL in your config, that will suffice.

    You can also provide a profile name with --profile to use the SSO instance from a specific profile.
    """

    if login_all is None:
        login_all = os.environ.get(LOGIN_ALL_VAR, "").lower() in ["true", "1"]

    configure_logging(LOGGER, verbose)

    instances, specifier, all_instances = find_instances(
        profile_name=profile,
        profile_source="--profile",
        start_url=sso_start_url,
        start_url_source="CLI input",
        region=sso_region,
        region_source="CLI input",
        start_url_vars=DEFAULT_START_URL_VARS,
        region_vars=DEFAULT_SSO_REGION_VARS,
    )

    if not instances:
        if all_instances:
            LOGGER.fatal((
                f"No AWS SSO config matched {specifier.to_str(region=True)} " +
                f"from {SSOInstance.to_strs(all_instances)}"))
        else:
            LOGGER.fatal("No AWS SSO config found")
        sys.exit(1)

    if len(instances) > 1 and not login_all:
        LOGGER.fatal(f"Found {len(instances)} SSO configs, please specify one or use --all: {SSOInstance.to_strs(instances)}")
        sys.exit(1)

    LOGGER.debug(f"Instances: {SSOInstance.to_strs(instances)}")

    session = botocore.session.Session()

    regions = [i.region for i in instances]
    token_fetchers = {}
    for region in regions:
        token_fetchers[region] = get_token_fetcher(session, region, interactive=True, disable_browser=headless)

    if len(instances) > 1:
        print(f"Logging in {len(instances)} AWS SSO instances")
    for instance in instances:
        print(f"Logging in {instance.start_url}")
        token_fetcher = token_fetchers[instance.region]
        try:
            token = token_fetcher.fetch_token(instance.start_url, force_refresh=force)
            LOGGER.debug(f"Token: {token}")
            expiration = token['expiresAt']
            if isinstance(expiration, str):
                expiration = parse(expiration)
            expiration_utc = expiration.astimezone(tzutc())
            expiration_str = expiration_utc.strftime(UTC_TIME_FORMAT)
            try:
                local_expiration = expiration_utc.astimezone(tzlocal())
                expiration_str = local_expiration.strftime(LOCAL_TIME_FORMAT)
                # TODO: locale-friendly string
            except:
                pass
            print(f"Login succeeded, valid until {expiration_str}")
        except PendingAuthorizationExpiredError:
            print(f"Login window expired", file=sys.stderr)
            sys.exit(2)
        except aws_error_utils.catch_aws_error("InvalidGrantException") as e:
            LOGGER.debug("Login failed; the login window may have expired", exc_info=True)
            err_info = aws_error_utils.get_aws_error_info(e)
            msg_str = f" ({err_info.message})" if err_info.message else ""
            print(f"Login failed; the login window may have expired: {err_info.code}{msg_str}", file=sys.stderr)
            sys.exit(3)
        except botocore.exceptions.ClientError as e:
            LOGGER.debug("Login failed", exc_info=True)
            err_info = aws_error_utils.get_aws_error_info(e)
            msg_str = f" ({err_info.message})" if err_info.message else ""
            print(f"Login failed: {err_info.code}{msg_str}", file=sys.stderr)
            sys.exit(4)
        except Exception as e:
            LOGGER.debug("Login failed", exc_info=True)
            print(f"Login failed: {e}", file=sys.stderr)
            sys.exit(4)


if __name__ == "__main__":
    login(prog_name="python -m aws_sso_util.login")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
