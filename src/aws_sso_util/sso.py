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

import boto3
import botocore
from botocore.credentials import JSONFileCache

from .vendored_botocore.utils import SSOTokenFetcher
from .vendored_botocore.credentials import SSOCredentialFetcher

from .exceptions import InvalidSSOConfigError, AuthDispatchError, AuthenticationNeededError
from .browser import OpenBrowserHandler, non_interactive_auth_raiser

SSO_TOKEN_DIR = os.path.expanduser(
    os.path.join("~", ".aws", "sso", "cache")
)

CREDENTIALS_CACHE_DIR = os.path.expanduser(
    os.path.join("~", ".aws", "cli", "cache")
)

LOGGER = logging.getLogger(__name__)

def _fmt_acct(account_id):
    if isinstance(account_id, numbers.Number):
        account_id = str(int(account_id))
    if len(account_id) < 12:
        account_id = account_id.rjust(12, "0")
    return account_id

def get_token_fetcher(session, sso_region, interactive=False, token_cache=None,
                     on_pending_authorization=None, message=None, outfile=None):
    if hasattr(session, "_session"): #boto3 Session
        session = session._session

    if token_cache is None:
        token_cache = JSONFileCache(SSO_TOKEN_DIR)

    if on_pending_authorization is None:
        if interactive:
            on_pending_authorization = OpenBrowserHandler(
                outfile=outfile,
                message=message,
            )
        else:
            on_pending_authorization = non_interactive_auth_raiser

    token_fetcher = SSOTokenFetcher(
        sso_region=sso_region,
        client_creator=session.create_client,
        cache=token_cache,
        on_pending_authorization=on_pending_authorization,
    )
    return token_fetcher

# def get_token_loader(session, sso_region, interactive=False, token_cache=None,
#                      on_pending_authorization=None, message=None, force_refresh=False):
#     token_fetcher = get_token_fetcher(
#         session=session,
#         sso_region=sso_region,
#         interactive=interactive,
#         token_cache=token_cache,
#         on_pending_authorization=on_pending_authorization,
#         message=message,
#     )
#     return get_token_loader_from_token_fetcher(token_fetcher, force_refresh=force_refresh)

def _get_token_loader_from_token_fetcher(token_fetcher, force_refresh=False):
    def token_loader(start_url):
        token_response = token_fetcher.fetch_token(
            start_url=start_url,
            force_refresh=force_refresh
        )
        LOGGER.debug("TOKEN: {}".format(token_response))
        return token_response["accessToken"]

    return token_loader


def get_credentials(session, start_url, sso_region, account_id, role_name, token_fetcher=None, force_refresh=False, cache=None):
    if hasattr(session, "_session"): #boto3 Session
        session = session._session
    if not token_fetcher:
        token_fetcher = get_token_fetcher(session, sso_region)

    token_loader = _get_token_loader_from_token_fetcher(token_fetcher=token_fetcher, force_refresh=force_refresh)

    if cache is None:
        cache = JSONFileCache(CREDENTIALS_CACHE_DIR)

    credential_fetcher = SSOCredentialFetcher(
        start_url=start_url,
        sso_region=sso_region,
        role_name=role_name,
        account_id=account_id,
        client_creator=session.create_client,
        cache=cache,
        token_loader=token_loader,
    )

    return credential_fetcher.fetch_credentials()

def get_botocore_session(start_url, sso_region, account_id, role_name):
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
        profile_name=profile_name
    )

    botocore_session.register_component(
        "credential_provider",
        botocore.credentials.CredentialResolver([sso_provider])
    )

    return botocore_session

def get_boto3_session(start_url, sso_region, account_id, role_name, region, login=False):
    """Get a boto3 session with the input configuration.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        account_id (str): The AWS account ID to use.
        role_name (str): The AWS SSO role (aka PermissionSet) name to use.
        region (str): The AWS region for the boto3 session.
        login (bool): Interactively log in the user if their AWS SSO credentials have expired.
    """
    account_id = _fmt_acct(account_id)

    if login:
        _login(start_url, sso_region)

    botocore_session = get_botocore_session(start_url, sso_region, account_id, role_name)

    session = boto3.Session(botocore_session=botocore_session, region_name=region)

    return session

def login(start_url, sso_region, force_refresh=False, message=None, outfile=None):
    """Interactively log in the user if their AWS SSO credentials have expired.

    If the user is not logged in or force_refresh is True, it will attempt
    to open a browser window to log in, as well as print a message to stderr
    with a URL and code to enter as a fallback.

    If the user is logged in and force_refresh is False, no action is taken.

    A custom message can be printed by setting message to a template string
    using {url} and {code} as placeholders.
    The message can be suppressed by setting outfile to False.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        force_refresh (bool): Always go through the authentication process.
        message (str): A message template to print with the fallback URL and code.
        outfile (file): The file-like object to print the message to,
            or False to suppress the message.

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
        outfile=outfile)

    token = token_fetcher.fetch_token(
        start_url=start_url,
        force_refresh=force_refresh
    )

    return token

_login = login

def list_available_roles(start_url, sso_region, account_id=None, login=False):
    """Iterate over the available accounts and roles the user has access to through AWS SSO.

    Args:
        start_url (str): The start URL for the AWS SSO instance.
        sso_region (str): The AWS region for the AWS SSO instance.
        account_id: Optional account id or list of account ids to check.
            If not set, all accounts available to the user are listed.
        role_name (str): The AWS SSO role (aka PermissionSet) name to use.
        login (bool): Interactively log in the user if their AWS SSO credentials have expired.

    Returns:
        An iterator that yields account id, account name, and role name.
        If the account(s) were provided in the input, the account name is always "UNKNOWN".
    """
    if account_id:
        if isinstance(account_id, (str, numbers.Number)):
            account_id_list = [_fmt_acct(account_id)]
        else:
            account_id_list = [_fmt_acct(v) for v in account_id]
    else:
        account_id_list = None

    session = botocore.session.Session()

    token_fetcher = get_token_fetcher(session, sso_region, interactive=login)

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
