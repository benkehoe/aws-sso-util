# Copyright (c) 2012-2013 Mitch Garnaat http://garnaat.org/
# Copyright 2012-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

# partial content of botocore.credentials in the v2 branch of awscli

import datetime
import json
import logging
import os
from hashlib import sha1

from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import (
    UnauthorizedSSOTokenError,
)
from .tokens import SSOTokenProvider
from botocore.utils import (
    JSONFileCache,
    SSOTokenLoader,
)
from botocore.credentials import CachedCredentialFetcher, CredentialProvider, DeferredRefreshableCredentials, SSOCredentialFetcher

logger = logging.getLogger(__name__)

def create_sso_provider(
        botocore_session,
        start_url,
        sso_region,
        account_id,
        role_name,
        sso_session_name=None,
        cache=None,
        token_cache=None):
    return SSOProvider(
        client_creator=botocore_session.create_client,
        start_url=start_url,
        sso_region=sso_region,
        account_id=account_id,
        role_name=role_name,
        sso_session_name=role_name,
        cache=cache,
        token_cache=token_cache,
        token_provider=SSOTokenProvider(
            session=botocore_session,
            start_url=start_url,
            sso_region=sso_region,
            sso_session_name=sso_session_name)
    )

class SSOProvider(CredentialProvider):
    METHOD = 'sso'

    _SSO_TOKEN_CACHE_DIR = os.path.expanduser(
        os.path.join('~', '.aws', 'sso', 'cache')
    )
    
    def __init__(self,
            client_creator,
            start_url,
            sso_region,
            account_id,
            role_name,
            sso_session_name=None,
            cache=None,
            token_cache=None,
            token_provider=None):
        if token_cache is None:
            token_cache = JSONFileCache(self._SSO_TOKEN_CACHE_DIR)
        self._token_cache = token_cache
        self._token_provider = token_provider
        if cache is None:
            cache = {}
        self.cache = cache
        self._client_creator = client_creator

        self.start_url = start_url
        self.sso_region = sso_region
        self.account_id = account_id
        self.role_name = role_name
        self.sso_session_name = sso_session_name

    def load(self):
        fetcher_kwargs = {
            'start_url': self.start_url,
            'sso_region': self.sso_region,
            'role_name': self.role_name,
            'account_id': self.account_id,
            'client_creator': self._client_creator,
            'token_loader': SSOTokenLoader(cache=self._token_cache),
            'cache': self.cache,
        }
        if self.sso_session_name:
            fetcher_kwargs['sso_session_name'] = self.sso_session_name
            fetcher_kwargs['token_provider'] = self._token_provider

        sso_fetcher = SSOCredentialFetcher(**fetcher_kwargs)

        return DeferredRefreshableCredentials(
            method=self.METHOD,
            refresh_using=sso_fetcher.fetch_credentials,
        )
