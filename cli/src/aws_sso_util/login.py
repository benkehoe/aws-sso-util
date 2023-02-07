# Copyright 2020 Ben Kehoe
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

import os
import sys
import json
import logging

import botocore
from dateutil.parser import parse
from dateutil.tz import tzlocal, tzutc

import click

import aws_error_utils

from aws_sso_lib.config import (
    Specifier,
    Session,
    Source,
    get_specifier,
    find_all_sessions,
    get_session_from_config_profile,
    get_session_from_config_session,
    InlineSessionError,
    ConfigProfileError,
    ConfigSessionError,
    MismatchedSessionError
)

from aws_sso_lib.sso import get_token_fetcher
from aws_sso_lib.exceptions import PendingAuthorizationExpiredError

from .utils import configure_logging

LOGGER = logging.getLogger(__name__)

LOGIN_DEFAULT_START_URL_VARS  = ["AWS_SSO_LOGIN_DEFAULT_SSO_START_URL"]
LOGIN_DEFAULT_SSO_REGION_VARS = ["AWS_SSO_LOGIN_DEFAULT_SSO_REGION"]

LOGIN_ALL_VAR = "AWS_SSO_LOGIN_ALL"

UTC_TIME_FORMAT = "%Y-%m-%d %H:%M UTC"
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M %Z"

@click.command()
@click.argument("specifier_param", metavar="SESSION_SPECIFIER", required=False)
@click.argument("sso_region", required=False)
@click.option("--profile", metavar="PROFILE_NAME", help="Use a config profile to specify Identity Center session")
@click.option("--sso-session", metavar="SESSION_NAME", help="Use a config session to specify Identity Center session")
@click.option("--all", "login_all", is_flag=True, default=None, help="Scan for all Identity Center sessions and log in to them all")
@click.option("--force-refresh", "force", is_flag=True, help="Force re-authentication")
@click.option("--headless", is_flag=True, default=None, help="Never open a browser window")
@click.option("--verbose", "-v", count=True)
@click.option("--session", "alternate_specifier_param", hidden=True)
@click.option("--sso-start-url", "alternate_sso_start_url", hidden=True)
@click.option("--sso-region", "alternate_sso_region", hidden=True)
@click.option("--force", "alternate_force", is_flag=True, hidden=True)
def login(
        specifier_param,
        sso_region,
        profile,
        sso_session,
        login_all,
        force,
        headless,
        verbose,
        alternate_specifier_param,
        alternate_sso_start_url,
        alternate_sso_region,
        alternate_force):
    """Log in to an Identity Center session.

    Note this only needs to be done once for a given Identity Center instance (i.e., start URL),
    as all profiles sharing the same start URL will share the same login.

    If only one Identity Center instance/start URL exists in your AWS config file,
    or you've set the environment variables AWS_DEFAULT_SSO_START_URL and AWS_DEFAULT_SSO_REGION,
    you don't need to provide a start URL or region.

    Otherwise, you can provide a full start URL, or a regex for the start URL (usually a substring will work),
    and if this uniquely identifies a start URL in your config, that will suffice.

    You can also provide a profile name with --profile to use the Identity Center session from a specific config profile,
    or --sso-session for a specific config session.
    """
    specifier_param = specifier_param or alternate_specifier_param
    sso_start_url = specifier_param or alternate_sso_start_url
    sso_region = sso_region or alternate_sso_region
    
    # mutually exclusive options
    if sso_start_url and profile:
        if alternate_specifier_param:
            raise click.BadParameter("Cannot use --session and --profile")
        else:
            raise click.BadParameter("Cannot use specifier and --profile")
    
    if sso_start_url and sso_session:
        if alternate_specifier_param:
            raise click.BadParameter("Cannot use --session and --sso-session")
        else:
            raise click.BadParameter("Cannot use specifier and --sso-session")
    
    if profile and sso_session:
        raise click.BadParameter("Cannot use --profile and --sso-session")

    if sso_region and not sso_start_url.startswith("http"):
        raise click.BadParameter("To use a region you must use a full start URL")

    force = force or alternate_force

    if login_all is None:
        login_all = os.environ.get(LOGIN_ALL_VAR, "").lower() in ["true", "1"]

    configure_logging(LOGGER, verbose)

    if verbose < 2:
        session_to_str_kwargs = {}
    else:
        session_to_str_kwargs = {"region": True, "registration_scopes": True}

    botocore_session = botocore.session.Session(session_vars={
        "profile": (None, None, None, None),
        "region": (None, None, None, None),
    })

    # first check if we've got specific config to get the session from
    # either a config profile or a config session, resulting in a list
    # of just a single session
    if profile:
        try:
            config_profile_session = get_session_from_config_profile(
                profile_name=profile,
                source=Source(type="CLI parameter", name="--profile"),
                botocore_session_full_config=botocore_session.full_config
            )
            if not config_profile_session:
                LOGGER.fatal(f"Config profile {profile} is not an Identity Center profile")
                sys.exit(5)
            LOGGER.debug(f"Session from config profile {profile}: {Session.to_str(config_profile_session, **session_to_str_kwargs)}")
            sessions = [config_profile_session]
        except ConfigProfileError as e:
            LOGGER.fatal(str(e))
            sys.exit(5)
    elif sso_session:
        try:
            config_session_session = get_session_from_config_session(
                session_name=sso_session,
                source=Source(type="CLI parameter", name="--sso-session"),
                botocore_session_full_config=botocore_session.full_config
            )
            LOGGER.debug(f"Session from config session {sso_session}: {Session.to_str(config_session_session, **session_to_str_kwargs)}")
            sessions = [config_session_session]
        except ConfigSessionError as e:
            LOGGER.fatal(str(e))
            sys.exit(5)
    else:
        # otherwise we need to search

        if login_all:
            specifier = None
        else:
            # the specifier might come from params
            if sso_start_url and sso_start_url.startswith("http") and sso_region:
                if not any([alternate_specifier_param, alternate_sso_start_url, alternate_sso_region]):
                    source_name = "positional parameters"
                else:
                    if alternate_specifier_param:
                        source_name_1 = "--session"
                    elif alternate_sso_start_url:
                        source_name_1 = "--sso-start-url"
                    else:
                        source_name_1 = "positional parameter"
                    if alternate_sso_region:
                        source_name_2 = "--sso-region"
                    else:
                        source_name_2 = "positional parameter"
                    source_name = f"{source_name_1} and {source_name_2}"
                
                try:
                    specifier = Specifier(
                        value=json.dumps({
                            "sso_start_url": sso_start_url,
                            "sso_region": sso_region
                        }),
                        source=Source(
                            type="CLI parameter",
                            name=source_name
                        ))
                except InlineSessionError as e:
                    LOGGER.fatal(str(e))
                    sys.exit(5)
            elif specifier_param:
                if alternate_specifier_param:
                    source_name = "--session"
                elif alternate_sso_start_url:
                    source_name = "--sso-start-url"
                else:
                    source_name = "positional parameter"
                try:
                    specifier = Specifier(
                        value=specifier_param,
                        source=Source(
                            type="CLI parameter",
                            name=source_name
                        ))
                except InlineSessionError as e:
                    LOGGER.fatal(str(e))
                    sys.exit(5)
            else:
                try:
                    specifier = get_specifier()
                except InlineSessionError as e:
                    LOGGER.fatal(str(e))
                    sys.exit(5)

        if specifier and specifier.session:
            message = f"Session from specifier"
            if specifier.source:
                message += f" from {specifier.source}"
            message += f": {specifier.session.to_str(**session_to_str_kwargs)}"
            LOGGER.debug(message)
            sessions = [specifier.session]
        else:
            all_sessions = find_all_sessions()

            if not all_sessions.unique_sessions:
                message = "No valid Identity Center sessions found"
                if all_sessions.malformed_session_errors:
                    message = (
                        message
                        + ", "
                        + f"but {len(all_sessions.malformed_session_errors)} invalid sessions were found"
                        + ": "
                        + "; ".join(str(e) for e in all_sessions.malformed_session_errors)
                    )
                LOGGER.fatal(message)
                sys.exit(1)
            
            if not specifier:
                sessions = all_sessions.unique_sessions
                LOGGER.debug(f"Sessions: {Session.to_strs(sessions, **session_to_str_kwargs)}")
            else:
                LOGGER.debug(f"Sessions before filtering with specifier {specifier.to_str()}: {Session.to_strs(all_sessions.unique_sessions, **session_to_str_kwargs)}")
                sessions = all_sessions.filter(specifier)
                if not sessions:
                    LOGGER.fatal(f"No Identity Center sessions matched specifier {specifier} from {Session.to_strs(all_sessions, **session_to_str_kwargs)}")
                    sys.exit(1)
                LOGGER.debug(f"Sessions after filtering: {Session.to_strs(sessions, **session_to_str_kwargs)}")
            
            try:
                all_sessions.raise_for_mismatch(sessions)
            except MismatchedSessionError as e:
                LOGGER.fatal(str(e))
                sys.exit(1)

        if not login_all and len(sessions) > 1:
            LOGGER.fatal(f"Found {len(sessions)} Identity Center sessions, please specify one or use --all: {Session.to_strs(sessions)}")
            sys.exit(1)

    regions = set(s.region for s in sessions)
    token_fetchers = {}
    for region in regions:
        token_fetchers[region] = get_token_fetcher(botocore_session, region, interactive=True, disable_browser=headless)

    if len(sessions) > 1:
        LOGGER.info(f"Logging in {len(sessions)} Identity Center sessions")
    for session in sessions:
        if session.is_inline_session():
            LOGGER.info(f"Logging in {session.start_url}")
            session_name = None
            registration_scopes = None
        else:
            LOGGER.info(f"Logging in {session.session_name} ({session.start_url})")
            session_name = session.session_name
            registration_scopes = session.registration_scopes
        
        token_fetcher = token_fetchers[session.region]
        
        try:

            token = token_fetcher.fetch_token(
                start_url=session.start_url,
                session_name=session_name,
                registration_scopes=registration_scopes,
                force_refresh=force)
            
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
            LOGGER.info(f"Login succeeded, valid until {expiration_str}")
        except PendingAuthorizationExpiredError:
            LOGGER.error(f"Login window expired")
            sys.exit(2)
        except aws_error_utils.catch_aws_error("InvalidGrantException") as e:
            LOGGER.debug("Login failed; the login window may have expired", exc_info=True)
            err_info = aws_error_utils.get_aws_error_info(e)
            msg_str = f" ({err_info.message})" if err_info.message else ""
            LOGGER.error(f"Login failed; the login window may have expired: {err_info.code}{msg_str}")
            sys.exit(3)
        except botocore.exceptions.ClientError as e:
            LOGGER.debug("Login failed", exc_info=True)
            err_info = aws_error_utils.get_aws_error_info(e)
            msg_str = f" ({err_info.message})" if err_info.message else ""
            LOGGER.error(f"Login failed: {err_info.code}{msg_str}")
            sys.exit(4)
        except Exception as e:
            LOGGER.debug("Login failed", exc_info=True)
            LOGGER.error(f"Login failed: {e}")
            sys.exit(4)


if __name__ == "__main__":
    login(prog_name="python -m aws_sso_util.login")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
