# Copyright 2020 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This code is based on the code for the AWS CLI v2"s `aws sso login` functionality
# https://github.com/aws/aws-cli/tree/v2/awscli/customizations/sso

import os
import sys
import webbrowser
import logging
import datetime
import uuid
import numbers
import typing
import json

import boto3
import botocore
from botocore.credentials import JSONFileCache
from botocore.credentials import SSOCredentialFetcher

from .format import format_account_id

from .vendored_botocore.utils import SSOTokenFetcher

from .exceptions import InvalidSSOConfigError, AuthDispatchError, AuthenticationNeededError
from .browser import OpenBrowserHandler, non_interactive_auth_raiser

SSO_TOKEN_DIR = os.path.expanduser(
    os.path.join("~", ".aws", "sso", "cache")
)

CREDENTIALS_CACHE_DIR = os.path.expanduser(
    os.path.join("~", ".aws", "cli", "cache")
)

LOGGER = logging.getLogger(__name__)

__all__ = ["get_boto3_session", "login", "list_available_accounts", "list_available_roles"]

# from customizations/sso/utils.py in AWS CLI v2
def _serialize_utc_timestamp(obj):
    if isinstance(obj, datetime.datetime):
        return obj.strftime('%Y-%m-%dT%H:%M:%SZ')
    return obj
def _sso_json_dumps(obj):
    return json.dumps(obj, default=_serialize_utc_timestamp)

def get_token_fetcher(session, sso_region, *, interactive=False, sso_cache=None,
                     on_pending_authorization=None, message=None, outfile=None,
                     disable_browser=None, expiry_window=None):
    if hasattr(session, "_session"): #boto3 Session
        session = session._session

    if sso_cache is None:
        sso_cache = JSONFileCache(SSO_TOKEN_DIR, dumps_func=_sso_json_dumps)

    if on_pending_authorization is None:
        if interactive:
            on_pending_authorization = OpenBrowserHandler(
                outfile=outfile,
                message=message,
                disable_browser=disable_browser,
            )
        else:
            on_pending_authorization = non_interactive_auth_raiser

    token_fetcher = SSOTokenFetcher(
        sso_region=sso_region,
        client_creator=session.create_client,
        cache=sso_cache,
        on_pending_authorization=on_pending_authorization,
        expiry_window=expiry_window,
    )
    return token_fetcher

def _get_token_loader_from_token_fetcher(token_fetcher, force_refresh=False):
    def token_loader(start_url):
        token_response = token_fetcher.fetch_token(
            start_url=start_url,
            force_refresh=force_refresh
        )
        LOGGER.debug("TOKEN: {}".format(token_response))
        return token_response["accessToken"]

    return token_loader


def get_credentials(session, start_url, sso_region, account_id, role_name, *,
        token_fetcher=None,
        force_refresh=False,
        sso_cache=None,
        credential_cache=None):
    """Return credentials for the given role.

    The return value is a dict containing the assumed role credentials.

    You probably want to use get_boto3_session() instead, which returns
    a boto3 session that caches its credentials and automatically refreshes them.
    """
    if hasattr(session, "_session"): #boto3 Session
        session = session._session
    if not token_fetcher:
        token_fetcher = get_token_fetcher(session, sso_region, sso_cache=sso_cache)

    token_loader = _get_token_loader_from_token_fetcher(token_fetcher=token_fetcher, force_refresh=force_refresh)

    if credential_cache is None:
        credential_cache = JSONFileCache(CREDENTIALS_CACHE_DIR)

    credential_fetcher = SSOCredentialFetcher(
        start_url=start_url,
        sso_region=sso_region,
        role_name=role_name,
        account_id=account_id,
        client_creator=session.create_client,
        cache=credential_cache,
        token_loader=token_loader,
    )

    return credential_fetcher.fetch_credentials()

def _get_botocore_session(
        start_url,
        sso_region,
        account_id,
        role_name,
        credential_cache=None,
        sso_cache=None,
        ):
    botocore_session = botocore.session.Session()

    profile_name = str(uuid.uuid4())
    load_config = lambda: {
        "profiles": {
            profile_name: {
                "sso_start_url": start_url,
                "sso_region": sso_region,
                "sso_account_id": account_id,
                "sso_role_name": role_name,
            }
        }
    }
    sso_provider = botocore.credentials.SSOProvider(
        load_config=load_config,
        client_creator=botocore_session.create_client,
        profile_name=profile_name,
        cache=credential_cache,
        token_cache=sso_cache,
    )

    botocore_session.register_component(
        "credential_provider",
        botocore.credentials.CredentialResolver([sso_provider])
    )

    return botocore_session

def get_boto3_session(
        start_url: str,
        sso_region: str,
        account_id: typing.Union[str, int],
        role_name: str,
        *,
        region: str,
        login: bool=False,
        sso_cache=None,
        credential_cache=None) -> boto3.Session:
    """Get a boto3 session with the input configuration.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        account_id (str): The AWS account ID to use.
        role_name (str): The AWS SSO role (aka Permission Set) name to use.
        region (str): The AWS region for the boto3 session.
        login (bool): Interactively log in the user if their AWS SSO credentials have expired.
        sso_cache: A dict-like object for AWS SSO credential caching.
        credential_cache: A dict-like object to cache the role credentials in.

    Returns:
        A boto3 Session object configured for the account and role.
    """
    account_id = format_account_id(account_id)

    if login:
        _login(start_url, sso_region, sso_cache=sso_cache)

    botocore_session = _get_botocore_session(start_url, sso_region, account_id, role_name,
        credential_cache=credential_cache,
        sso_cache=sso_cache)

    session = boto3.Session(botocore_session=botocore_session, region_name=region)

    return session

def login(
        start_url: str,
        sso_region: str,
        *,
        force_refresh: bool=False,
        disable_browser: bool=None,
        message: str=None,
        outfile: typing.Union[typing.TextIO, bool]=None,
        sso_cache=None,
        expiry_window=None,) -> typing.Dict:
    """Interactively log in the user if their AWS SSO credentials have expired.

    If the user is not logged in or force_refresh is True, it will attempt to log in.
    If the user is logged in and force_refresh is False, no action is taken.

    If disable_browser is True, a message will be printed to stderr
    with a URL and code for the user to log in with.
    Otherwise, it will attempt to automatically open the user's browser
    to log in, as well as printing the URL and code to stderr as a fallback.

    A custom message can be printed by setting message to a template string
    using {url} and {code} as placeholders.
    The message can be suppressed by setting message to False.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        force_refresh (bool): Always go through the authentication process.
        disable_browser (bool): Skip the browser popup
            and only print a message with the URL and code.
        message (str): A message template to print with the fallback URL and code.
        outfile (file): The file-like object to print the message to,
            or False to suppress the message.
        sso_cache: A dict-like object for AWS SSO credential caching.
        expiry_window: An int or datetime.timedelta, or callable returning such,
            specifying the minimum duration in seconds any existing token
            must be valid for.

    Returns:
        The token dict as returned by sso-oidc:CreateToken,
        which contains the actual authorization token, as well as the expiration.
        """
    session = botocore.session.Session()

    token_fetcher = get_token_fetcher(
        session=session,
        sso_region=sso_region,
        interactive=True,
        message=message,
        outfile=outfile,
        disable_browser=disable_browser,
        sso_cache=sso_cache,
        expiry_window=expiry_window)

    token = token_fetcher.fetch_token(
        start_url=start_url,
        force_refresh=force_refresh
    )
    token['expiresAt'] = _serialize_utc_timestamp(token['expiresAt'])

    return token

_login = login

def logout(
        start_url: str,
        sso_region: str,
        *,
        sso_cache=None):
    """Log out of the given AWS SSO instance.

    Note that this function currently does not remove the token from
    the SSO file cache, which can cause subsequent usage of other functions
    in this module to pick up an invalid token from there.
    https://github.com/boto/botocore/issues/2255

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        sso_cache: A dict-like object for AWS SSO credential caching.

    Returns:
        Never raises.
        Returns True if a token was found and successfully logged out.
        Returns False if no token was found.
        If any exception is raised during the logout process,
            it is caught and returned.
    """

    session = botocore.session.Session()

    token_fetcher = get_token_fetcher(
        session=session,
        sso_region=sso_region,
        sso_cache=sso_cache)

    try:
        token = token_fetcher.pop_token_from_cache(
            start_url=start_url
        )

        if not token:
            return True
        else:
            config = botocore.config.Config(
                region_name=sso_region,
                signature_version=botocore.UNSIGNED,
            )
            client = session.create_client("sso", config=config)

            client.logout(accessToken=token["accessToken"])
            return False
    except Exception as e:
        LOGGER.debug("Exception during logout", exc_info=True)
        return e

def list_available_accounts(
        start_url: str,
        sso_region: str,
        *,
        login: bool=False,
        sso_cache=None) -> typing.Iterator[typing.Tuple[str, str]]:
    """Iterate over the available accounts the user has access to through AWS SSO.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        login (bool): Interactively log in the user if their AWS SSO credentials have expired.
        sso_cache: A dict-like object for AWS SSO credential caching.

    Returns:
        An iterator that yields account id and account name.
    """
    session = botocore.session.Session()

    token_fetcher = get_token_fetcher(session, sso_region, interactive=login, sso_cache=sso_cache)

    token = token_fetcher.fetch_token(start_url)

    config = botocore.config.Config(
        region_name=sso_region,
        signature_version=botocore.UNSIGNED,
    )
    client = session.create_client("sso", config=config)

    list_accounts_args = {"accessToken": token["accessToken"]}
    while True:
        response = client.list_accounts(**list_accounts_args)

        for account in response["accountList"]:
            yield account["accountId"], account["accountName"]

        next_token = response.get("nextToken")
        if not next_token:
            break
        else:
            list_accounts_args["nextToken"] = response["nextToken"]

def list_available_roles(
        start_url: str,
        sso_region: str,
        account_id: typing.Union[str, int, typing.Iterable[typing.Union[str, int]]]=None,
        *,
        login: bool=False,
        sso_cache=None) -> typing.Iterator[typing.Tuple[str, str, str]]:
    """Iterate over the available accounts and roles the user has access to through AWS SSO.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        account_id: Optional account id or list of account ids to check.
            If not set, all accounts available to the user are listed.
        login (bool): Interactively log in the user if their AWS SSO credentials have expired.
        sso_cache: A dict-like object for AWS SSO credential caching.

    Returns:
        An iterator that yields account id, account name, and role name.
        If the account(s) were provided in the input, the account name is always "UNKNOWN".
    """
    if account_id:
        if isinstance(account_id, (str, numbers.Number)):
            account_id_list = [format_account_id(account_id)]
        else:
            account_id_list = [format_account_id(v) for v in account_id]
    else:
        account_id_list = None

    session = botocore.session.Session()

    token_fetcher = get_token_fetcher(session, sso_region, interactive=login, sso_cache=sso_cache)

    token = token_fetcher.fetch_token(start_url)

    config = botocore.config.Config(
        region_name=sso_region,
        signature_version=botocore.UNSIGNED,
    )
    client = session.create_client("sso", config=config)

    if account_id_list:
        def account_iterator():
            for acct in account_id_list:
                yield acct, "UNKNOWN"
    else:
        def account_iterator():
            list_accounts_args = {"accessToken": token["accessToken"]}
            while True:
                response = client.list_accounts(**list_accounts_args)

                for account in response["accountList"]:
                    yield account["accountId"], account["accountName"]

                next_token = response.get("nextToken")
                if not next_token:
                    break
                else:
                    list_accounts_args["nextToken"] = response["nextToken"]

    for account_id, account_name in account_iterator():
        list_role_args = {
            "accessToken": token["accessToken"],
            "accountId": account_id,
        }

        while True:
            response = client.list_account_roles(**list_role_args)

            for role in response["roleList"]:
                role_name = role["roleName"]

                yield account_id, account_name, role_name

            next_token = response.get("nextToken")
            if not next_token:
                break
            else:
                list_role_args["nextToken"] = response["nextToken"]
