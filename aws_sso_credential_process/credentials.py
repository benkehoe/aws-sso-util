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

# this is the new content of botocore.credentials in the v2 branch

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

from dateutil.parser import parse
from dateutil.tz import tzlocal, tzutc

import botocore.configloader
import botocore.compat
from botocore import UNSIGNED
# from botocore.compat import total_seconds
# from botocore.compat import compat_shell_split
from botocore.config import Config
# from botocore.exceptions import UnknownCredentialError
# from botocore.exceptions import PartialCredentialsError
# from botocore.exceptions import ConfigNotFound
# from botocore.exceptions import InvalidConfigError
# from botocore.exceptions import InfiniteLoopConfigError
# from botocore.exceptions import RefreshWithMFAUnsupportedError
# from botocore.exceptions import MetadataRetrievalError
# from botocore.exceptions import CredentialRetrievalError
# from botocore.exceptions import UnauthorizedSSOTokenError
# from botocore.utils import InstanceMetadataFetcher, parse_key_val_file
# from botocore.utils import ContainerMetadataFetcher
# from botocore.utils import FileWebIdentityTokenLoader
# from botocore.utils import SSOTokenLoader

from botocore.credentials import (
    CachedCredentialFetcher,
    _serialize_if_needed,
)

from .exceptions import UnauthorizedSSOTokenError


class SSOCredentialFetcher(CachedCredentialFetcher):
    def __init__(self, start_url, sso_region, role_name, account_id,
                 client_creator, token_loader=None, cache=None,
                 expiry_window_seconds=None):
        self._client_creator = client_creator
        self._sso_region = sso_region
        self._role_name = role_name
        self._account_id = account_id
        self._start_url = start_url
        self._token_loader = token_loader

        super(SSOCredentialFetcher, self).__init__(
            cache, expiry_window_seconds
        )

    def _create_cache_key(self):
        """Create a predictable cache key for the current configuration.
        The cache key is intended to be compatible with file names.
        """
        args = {
            'startUrl': self._start_url,
            'roleName': self._role_name,
            'accountId': self._account_id,
        }
        # NOTE: It would be good to hoist this cache key construction logic
        # into the CachedCredentialFetcher class as we should be consistent.
        # Unfortunately, the current assume role fetchers that sub class don't
        # pass separators resulting in non-minified JSON. In the long term,
        # all fetchers should use the below caching scheme.
        args = json.dumps(args, sort_keys=True, separators=(',', ':'))
        argument_hash = sha1(args.encode('utf-8')).hexdigest()
        return self._make_file_safe(argument_hash)

    def _parse_timestamp(self, timestamp_ms):
        # fromtimestamp expects seconds so: milliseconds / 1000 = seconds
        timestamp_seconds = timestamp_ms / 1000.0
        timestamp = datetime.datetime.fromtimestamp(timestamp_seconds, tzutc())
        return _serialize_if_needed(timestamp)

    def _get_credentials(self):
        """Get credentials by calling SSO get role credentials."""
        config = Config(
            signature_version=UNSIGNED,
            region_name=self._sso_region,
        )
        client = self._client_creator('sso', config=config)

        kwargs = {
            'roleName': self._role_name,
            'accountId': self._account_id,
            'accessToken': self._token_loader(self._start_url),
        }
        try:
            response = client.get_role_credentials(**kwargs)
        except client.exceptions.UnauthorizedException:
            raise UnauthorizedSSOTokenError()
        credentials = response['roleCredentials']

        credentials = {
            'ProviderType': 'sso',
            'Credentials': {
                'AccessKeyId': credentials['accessKeyId'],
                'SecretAccessKey': credentials['secretAccessKey'],
                'SessionToken': credentials['sessionToken'],
                'Expiration': self._parse_timestamp(credentials['expiration']),
            }
        }
        return credentials
