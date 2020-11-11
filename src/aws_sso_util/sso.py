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

from botocore.credentials import JSONFileCache

from .vendored_botocore.utils import SSOTokenFetcher
from .vendored_botocore.credentials import SSOCredentialFetcher

from .exceptions import InvalidSSOConfigError, AuthDispatchError, InteractiveAuthDisabledError
from .browser import OpenBrowserHandler, non_interactive_auth_raiser

SSO_TOKEN_DIR = os.path.expanduser(
    os.path.join('~', '.aws', 'sso', 'cache')
)

CREDENTIALS_CACHE_DIR = os.path.expanduser(
    os.path.join('~', '.aws', 'cli', 'cache')
)


def get_token_loader(session, sso_region, interactive=False, token_cache=None,
                     on_pending_authorization=None, force_refresh=False, logger=None):
    if hasattr(session, '_session'): #boto3 Session
        session = session._session

    if token_cache is None:
        token_cache = JSONFileCache(SSO_TOKEN_DIR)

    if on_pending_authorization is None:
        if interactive:
            on_pending_authorization = OpenBrowserHandler(
                outfile=sys.stderr,
                open_browser=webbrowser.open_new_tab,
            )
        else:
            on_pending_authorization = non_interactive_auth_raiser

    token_fetcher = SSOTokenFetcher(
        sso_region=sso_region,
        client_creator=session.create_client,
        cache=token_cache,
        on_pending_authorization=on_pending_authorization,
    )

    def token_loader(start_url):
        token_response = token_fetcher.fetch_token(
            start_url=start_url,
            force_refresh=force_refresh
        )
        if logger:
            logger.debug('TOKEN RESPONSE: {}'.format(token_response))
        return token_response['accessToken']

    return token_loader


def get_credentials(session, sso_region, start_url, account_id, role_name, token_loader=None, cache=None, logger=None):
    if hasattr(session, '_session'): #boto3 Session
        session = session._session
    if not token_loader:
        token_loader = get_token_loader(session, sso_region, logger=logger)

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
