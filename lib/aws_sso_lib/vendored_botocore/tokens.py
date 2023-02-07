# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

# partial content of botocore.tokens in the v2 branch of awscli

import json
import logging
import os
from datetime import datetime, timedelta

import dateutil.parser
from dateutil.tz import tzutc

from botocore import UNSIGNED
from botocore.compat import total_seconds
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
)
from botocore.utils import CachedProperty, JSONFileCache, SSOTokenLoader
from botocore.tokens import FrozenAuthToken, DeferredRefreshableToken

logger = logging.getLogger(__name__)

def _utc_now():
    return datetime.now(tzutc())

def _serialize_utc_timestamp(obj):
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
    return obj

def _sso_json_dumps(obj):
    return json.dumps(obj, default=_serialize_utc_timestamp)

class SSOTokenProvider:
    METHOD = "sso"
    _REFRESH_WINDOW = 15 * 60
    _SSO_TOKEN_CACHE_DIR = os.path.expanduser(
        os.path.join("~", ".aws", "sso", "cache")
    )
    _GRANT_TYPE = "refresh_token"
    DEFAULT_CACHE_CLS = JSONFileCache

    def __init__(self,
            session,
            start_url,
            sso_region,
            sso_session_name,
            cache=None,
            time_fetcher=_utc_now
        ):
        self._session = session
        self._start_url = start_url
        self._sso_region = sso_region
        self._sso_session_name = sso_session_name
        if cache is None:
            cache = self.DEFAULT_CACHE_CLS(
                self._SSO_TOKEN_CACHE_DIR,
                dumps_func=_sso_json_dumps,
            )
        self._now = time_fetcher
        self._cache = cache
        self._token_loader = SSOTokenLoader(cache=self._cache)

    @CachedProperty
    def _client(self):
        config = Config(
            region_name=self._sso_region,
            signature_version=UNSIGNED,
        )
        return self._session.create_client("sso-oidc", config=config)

    def _attempt_create_token(self, token):
        response = self._client.create_token(
            grantType=self._GRANT_TYPE,
            clientId=token["clientId"],
            clientSecret=token["clientSecret"],
            refreshToken=token["refreshToken"],
        )
        expires_in = timedelta(seconds=response["expiresIn"])
        new_token = {
            "startUrl": self._start_url,
            "region": self._sso_region,
            "accessToken": response["accessToken"],
            "expiresAt": self._now() + expires_in,
            # Cache the registration alongside the token
            "clientId": token["clientId"],
            "clientSecret": token["clientSecret"],
            "registrationExpiresAt": token["registrationExpiresAt"],
        }
        if "refreshToken" in response:
            new_token["refreshToken"] = response["refreshToken"]
        logger.info("SSO Token refresh succeeded")
        return new_token

    def _refresh_access_token(self, token):
        keys = (
            "refreshToken",
            "clientId",
            "clientSecret",
            "registrationExpiresAt",
        )
        missing_keys = [k for k in keys if k not in token]
        if missing_keys:
            msg = f"Unable to refresh SSO token: missing keys: {missing_keys}"
            logger.info(msg)
            return None

        expiry = dateutil.parser.parse(token["registrationExpiresAt"])
        if total_seconds(expiry - self._now()) <= 0:
            logger.info(f"SSO token registration expired at {expiry}")
            return None

        try:
            return self._attempt_create_token(token)
        except ClientError:
            logger.warning("SSO token refresh attempt failed", exc_info=True)
            return None

    def _refresher(self):
        start_url = self._start_url
        session_name = self._sso_session_name
        logger.info(f"Loading cached SSO token for {session_name}")
        token_dict = self._token_loader(start_url, session_name=session_name)
        expiration = dateutil.parser.parse(token_dict["expiresAt"])
        logger.debug(f"Cached SSO token expires at {expiration}")

        remaining = total_seconds(expiration - self._now())
        if remaining < self._REFRESH_WINDOW:
            new_token_dict = self._refresh_access_token(token_dict)
            if new_token_dict is not None:
                token_dict = new_token_dict
                expiration = token_dict["expiresAt"]
                self._token_loader.save_token(
                    start_url, token_dict, session_name=session_name
                )

        return FrozenAuthToken(
            token_dict["accessToken"], expiration=expiration
        )

    def load_token(self):
        return DeferredRefreshableToken(
            self.METHOD, self._refresher, time_fetcher=self._now
        )