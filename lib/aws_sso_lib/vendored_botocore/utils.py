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

# partial content of botocore.utils in the v2 branch of awscli

import time
import datetime
import logging
import os
import getpass
import threading
import json
import subprocess
from collections import namedtuple
from copy import deepcopy
from hashlib import sha1
import hashlib

from dateutil.parser import parse
from dateutil.tz import tzlocal
import dateutil

import botocore.configloader
import botocore.compat
from botocore import UNSIGNED
from botocore.compat import total_seconds
# from botocore.compat import compat_shell_split
from botocore.config import Config
# from botocore.exceptions import UnknownCredentialError
# from botocore.exceptions import PartialCredentialsError
# from botocore.exceptions import ConfigNotFound
# from botocore.exceptions import InvalidConfigError
# from botocore.exceptions import PendingAuthorizationExpiredError

from botocore.utils import (
    CachedProperty,
    datetime2timestamp,
    tzutc
)

from .exceptions import PendingAuthorizationExpiredError

def _serialize_datetimes(obj, iso=False):
    if isinstance(obj, datetime.datetime):
        if iso:
            return obj.isoformat()
        return obj.strftime('%Y-%m-%dT%H:%M:%S%Z')
    if isinstance(obj, (list, tuple)):
        return list(_serialize_datetimes(v, iso=iso) for v in obj)
    if isinstance(obj, dict):
        return {key: _serialize_datetimes(value, iso=iso) for key, value in obj.items()}
    return obj

class SSOTokenFetcher(object):
    # The device flow RFC defines the slow down delay to be an additional
    # 5 seconds:
    # https://tools.ietf.org/html/draft-ietf-oauth-device-flow-15#section-3.5
    _SLOW_DOWN_DELAY = 5
    # The default interval of 5 is also defined in the RFC (see above link)
    _DEFAULT_INTERVAL = 5
    _DEFAULT_EXPIRY_WINDOW = 15 * 60
    _CLIENT_REGISTRATION_TYPE = 'public'
    _GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:device_code'

    def __init__(
            self,
            sso_region,
            client_creator,
            cache=None,
            on_pending_authorization=None,
            time_fetcher=None,
            sleep=None,
            expiry_window=None,
    ):
        self._sso_region = sso_region
        self._client_creator = client_creator
        self._on_pending_authorization = on_pending_authorization

        if time_fetcher is None:
            time_fetcher = self._utc_now
        self._time_fetcher = time_fetcher

        if sleep is None:
            sleep = time.sleep
        self._sleep = sleep

        if cache is None:
            cache = {}
        self._cache = cache

        if expiry_window is None:
            expiry_window = self._DEFAULT_EXPIRY_WINDOW
        self._expiry_window = expiry_window

    def _utc_now(self):
        return datetime.datetime.now(tzutc())

    def _parse_if_needed(self, value):
        if isinstance(value, datetime.datetime):
            return value
        return dateutil.parser.parse(value)

    def _is_expired(self, response):
        if 'expiresAt' not in response:
            return True
        end_time = self._parse_if_needed(response['expiresAt'])
        seconds = total_seconds(end_time - self._time_fetcher())
        if callable(self._expiry_window):
            expiry_window = self._expiry_window()
        else:
            expiry_window = self._expiry_window
        if isinstance(expiry_window, datetime.timedelta):
            expiry_window = expiry_window.total_seconds()
        return seconds < expiry_window

    @CachedProperty
    def _client(self):
        config = botocore.config.Config(
            region_name=self._sso_region,
            signature_version=botocore.UNSIGNED,
        )
        return self._client_creator('sso-oidc', config=config)

    def _register_client(self, session_name, scopes):
        timestamp = self._time_fetcher()
        if session_name is None:
            # Use a timestamp for the session name for legacy configuration
            session_name = f"anonymous-{int(datetime2timestamp(timestamp))}"
        register_kwargs = {
            'clientName': f'aws-sso-util-{session_name}',
            'clientType': self._CLIENT_REGISTRATION_TYPE,
        }
        if scopes:
            register_kwargs['scopes'] = scopes
        response = self._client.register_client(**register_kwargs)
        expires_at = response['clientSecretExpiresAt']
        expires_at = datetime.datetime.fromtimestamp(expires_at, tzutc())
        registration = {
            'clientId': response['clientId'],
            'clientSecret': response['clientSecret'],
            'expiresAt': expires_at,
            'receivedAt': timestamp.strftime('%Y-%m-%dT%H:%M:%S%Z'),
        }
        if scopes:
            registration['scopes'] = scopes
        registration = _serialize_datetimes(registration)
        return registration

    def _registration_cache_key(self, start_url, session_name, scopes):
        # Registration is unique based on the following properties to ensure
        # modifications to the registration do not affect the permissions of
        # tokens derived for other start URLs.
        args = {
            'tool': 'botocore',
            'startUrl': start_url,
            'region': self._sso_region,
            'scopes': scopes,
            'session_name': session_name,
        }
        cache_args = json.dumps(args, sort_keys=True).encode('utf-8')
        return hashlib.sha1(cache_args).hexdigest()

    def _registration(
        self,
        start_url,
        session_name,
        scopes,
        force_refresh=False,
    ):
        cache_key = self._registration_cache_key(
            start_url,
            session_name,
            scopes,
        )
        if not force_refresh and cache_key in self._cache:
            registration = self._cache[cache_key]
            if not self._is_expired(registration):
                return registration

        registration = self._register_client(
            session_name,
            scopes,
        )
        self._cache[cache_key] = registration
        return registration

    def _authorize_client(self, start_url, registration):
        # NOTE: The authorization response is not cached. These responses are
        # short lived (currently only 10 minutes) and can only be exchanged for
        # a token once. Having multiple clients share this is problematic.
        response = self._client.start_device_authorization(
            clientId=registration['clientId'],
            clientSecret=registration['clientSecret'],
            startUrl=start_url,
        )
        expires_in = datetime.timedelta(seconds=response['expiresIn'])
        timestamp = self._time_fetcher()
        authorization = {
            'deviceCode': response['deviceCode'],
            'userCode': response['userCode'],
            'verificationUri': response['verificationUri'],
            'verificationUriComplete': response['verificationUriComplete'],
            'expiresAt': timestamp + expires_in,
        }
        if 'interval' in response:
            authorization['interval'] = response['interval']
        return authorization

    def _poll_for_token(self, start_url, session_name, registration_scopes):
        registration = self._registration(
            start_url,
            session_name,
            registration_scopes,
        )
        authorization = self._authorize_client(start_url, registration)

        interval = authorization.get('interval', self._DEFAULT_INTERVAL)

        # In some circumstances the client may be pre-authorized to generate a
        # token and it's not necessary to display the authorization message. We
        # do a single create token attempt before displaying the message and
        # falling back to the polling loop.
        interval, token = self._create_token_attempt(
            start_url, registration, authorization, interval
        )
        if token is not None:
            return token

        if self._on_pending_authorization:
            # This callback can display the user code / verification URI
            # so the user knows the page to go to. Potentially, this call
            # back could even be used to auto open a browser.
            self._on_pending_authorization(**authorization)

        # NOTE: This loop currently relies on the service to either return
        # a valid token or a ExpiredTokenException to break the loop. If this
        # proves to be problematic it may be worth adding an additional
        # mechanism to control timing this loop out.
        while True:
            interval, token = self._create_token_attempt(
                start_url, registration, authorization, interval
            )
            if token is not None:
                return token
            self._sleep(interval)

    def _create_token_attempt(
        self, start_url, registration, authorization, interval,
    ):
        try:
            response = self._client.create_token(
                grantType=self._GRANT_TYPE,
                clientId=registration['clientId'],
                clientSecret=registration['clientSecret'],
                deviceCode=authorization['deviceCode'],
            )
            expires_in = datetime.timedelta(seconds=response['expiresIn'])
            timestamp = self._time_fetcher()
            token = {
                'startUrl': start_url,
                'region': self._sso_region,
                'accessToken': response['accessToken'],
                'expiresAt': timestamp + expires_in,
                'receivedAt': timestamp,
                # Cache the registration alongside the token
                'clientId': registration['clientId'],
                'clientSecret': registration['clientSecret'],
                'registrationExpiresAt': registration['expiresAt'],
            }
            if 'refreshToken' in response:
                token['refreshToken'] = response['refreshToken']
            token = _serialize_datetimes(token)
            return interval, token
        except self._client.exceptions.SlowDownException:
            interval += self._SLOW_DOWN_DELAY
        except self._client.exceptions.AuthorizationPendingException:
            pass
        except self._client.exceptions.ExpiredTokenException:
            raise PendingAuthorizationExpiredError()
        return interval, None

    def _token_cache_key(self, start_url, session_name):
        input_str = start_url
        if session_name is not None:
            input_str = session_name
        return hashlib.sha1(input_str.encode('utf-8')).hexdigest()

    def _token(
        self,
        start_url,
        force_refresh,
        registration_scopes,
        session_name,
    ):
        cache_key = self._token_cache_key(start_url, session_name)
        # Only obey the token cache if we are not forcing a refresh.
        if not force_refresh and cache_key in self._cache:
            token = self._cache[cache_key]
            # TODO: Should probably try to refresh token here
            if not self._is_expired(token):
                return token

        token = self._poll_for_token(
            start_url,
            session_name,
            registration_scopes,
        )
        self._cache[cache_key] = token
        return token

    def fetch_token(
        self,
        start_url,
        force_refresh=False,
        registration_scopes=None,
        session_name=None,
    ):
        return self._token(
            start_url,
            force_refresh,
            registration_scopes,
            session_name,
        )

    def get_token_from_cache(self, start_url, session_name=None):
        cache_key = self._token_cache_key(start_url, session_name)
        if cache_key in self._cache:
            token = self._cache[cache_key]
            return token
        return None

    def pop_token_from_cache(self, start_url, session_name=None):
        cache_key = self._cache_key(start_url, session_name)
        # Only obey the token cache if we are not forcing a refresh.
        if cache_key in self._cache:
            token = self._cache[cache_key]
            try:
                del self._cache[cache_key]
            except AttributeError:
                pass
            return token
        else:
            return None
    
    def is_token_expired(self, token):
        return self._is_expired(token)
