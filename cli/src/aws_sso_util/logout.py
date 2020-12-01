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

# modified from code at
# https://github.com/aws/aws-cli/blob/v2/awscli/customizations/sso/logout.py

import json
import logging
import os

import botocore
from botocore.exceptions import ClientError

from aws_sso_lib.sso import SSO_TOKEN_DIR
from aws_sso_lib.sso import CREDENTIALS_CACHE_DIR as AWS_CREDS_CACHE_DIR

from .utils import configure_logging

import click

LOGGER = logging.getLogger(__name__)

@click.command()
@click.option("--verbose", "-v", "--debug", count=True)
def logout(verbose):
    """Log out of all AWS SSO sessions"""
    configure_logging(LOGGER, verbose)
    session = botocore.session.Session()

    LOGGER.debug("Removing tokens")
    SSOTokenSweeper(session).delete_credentials(SSO_TOKEN_DIR)
    LOGGER.debug("Removing credentials")
    SSOCredentialSweeper().delete_credentials(AWS_CREDS_CACHE_DIR)


class BaseCredentialSweeper(object):
    def delete_credentials(self, creds_dir):
        if not os.path.isdir(creds_dir):
            return
        filenames = os.listdir(creds_dir)
        for filename in filenames:
            filepath = os.path.join(creds_dir, filename)
            contents = self._get_json_contents(filepath)
            if contents is None:
                continue
            if self._should_delete(contents):
                self._before_deletion(contents)
                os.remove(filepath)

    def _should_delete(self, filename):
        raise NotImplementedError('_should_delete')

    def _get_json_contents(self, filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except Exception:
            # We do not want to include the traceback in the exception
            # so that we do not accidentally log sensitive contents because
            # of the exception or its Traceback.
            LOGGER.debug('Failed to load: %s', filename)
            return None

    def _before_deletion(self, contents):
        pass


class SSOTokenSweeper(BaseCredentialSweeper):
    def __init__(self, session):
        self._session = session

    def _should_delete(self, contents):
        return 'accessToken' in contents

    def _before_deletion(self, contents):
        # If the sso region is present in the cached token, construct a client
        # and invoke the logout api to invalidate the token before deleting it.
        sso_region = contents.get('region')
        if sso_region:
            config = botocore.config.Config(
                region_name=sso_region,
                signature_version=botocore.UNSIGNED,
            )
            sso = self._session.create_client('sso', config=config)
            try:
                sso.logout(accessToken=contents['accessToken'])
            except ClientError:
                # The token may alread be expired or otherwise invalid. If we
                # get a client error on logout just log and continue on
                LOGGER.debug('Failed to call logout API:', exc_info=True)


class SSOCredentialSweeper(BaseCredentialSweeper):
    def _should_delete(self, contents):
        return contents.get('ProviderType') == 'sso'


if __name__ == "__main__":
    logout(prog_name="python -m aws_sso_util.logout")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
