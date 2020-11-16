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

# This code is based on the code for the AWS CLI v2's `aws sso login` functionality
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
    os.path.join('~', '.aws', 'sso', 'cache')
)

CREDENTIALS_CACHE_DIR = os.path.expanduser(
    os.path.join('~', '.aws', 'cli', 'cache')
)

LOGGER = logging.getLogger(__name__)

def get_token_fetcher(session, sso_region, interactive=False, token_cache=None,
                     on_pending_authorization=None, message=None, outfile=None):
    if hasattr(session, '_session'): #boto3 Session
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

def get_token_loader(session, sso_region, interactive=False, token_cache=None,
                     on_pending_authorization=None, message=None, force_refresh=False):
    token_fetcher = get_token_fetcher(
        session=session,
        sso_region=sso_region,
        interactive=interactive,
        token_cache=token_cache,
        on_pending_authorization=on_pending_authorization,
        message=message,
    )
    return get_token_loader_from_token_fetcher(token_fetcher, force_refresh=force_refresh)

def get_token_loader_from_token_fetcher(token_fetcher, force_refresh=False):
    def token_loader(start_url):
        token_response = token_fetcher.fetch_token(
            start_url=start_url,
            force_refresh=force_refresh
        )
        LOGGER.debug('TOKEN: {}'.format(token_response))
        return token_response['accessToken']

    return token_loader


def get_credentials(session, start_url, sso_region, account_id, role_name, token_loader=None, cache=None):
    if hasattr(session, '_session'): #boto3 Session
        session = session._session
    if not token_loader:
        token_loader = get_token_loader(session, sso_region)

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
        'credential_provider',
        botocore.credentials.CredentialResolver([sso_provider])
    )

    return botocore_session

def get_boto3_session(start_url, sso_region, account_id, role_name, region, login=False):
    """Get a boto3 session with the input configuration"""
    if login:
        _login(start_url, sso_region)

    if isinstance(account_id, (str, numbers.Number)):
        account_id = str(int(account_id)).rjust(12, '0')

    botocore_session = get_botocore_session(start_url, sso_region, account_id, role_name)

    session = boto3.Session(botocore_session=botocore_session, region_name=region)

    return session

def login(start_url, sso_region, force_refresh=False, message=None, outfile=None):
    """Interactively log in the user if their AWS SSO credentials have expired"""
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
