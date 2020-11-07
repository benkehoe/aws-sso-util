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

import argparse
import os
import sys
import json
import logging
import datetime

from botocore.session import Session
from botocore.exceptions import ClientError

import click

from ..sso import get_token_loader, get_credentials
from ..exceptions import InvalidSSOConfigError, AuthDispatchError, InteractiveAuthDisabledError

LOG_FILE = os.path.expanduser(
    os.path.join('~', '.aws', 'sso', 'aws-sso-credential-process-log.txt')
)

LOGGER = logging.getLogger(__name__)


CONFIG_VARS = [
    ('start url', 'sso_start_url'),
    ('SSO region', 'sso_region'),
    ('role', 'sso_role_name'),
    ('account', 'sso_account_id'),
    ('interactive', 'sso_interactive_auth')
]

def get_config(arg_config, profile_config, logger=None):
    sso_config = {}
    missing_vars = []
    for friendly_name, config_var_name in CONFIG_VARS:
        if arg_config.get(config_var_name):
            sso_config[config_var_name] = arg_config[config_var_name]
        elif config_var_name not in profile_config:
            missing_vars.append((friendly_name, config_var_name))
            sso_config[config_var_name] = None
        else:
            sso_config[config_var_name] = profile_config[config_var_name]

    required_vars = ['sso_start_url', 'sso_region', 'sso_account_id', 'sso_role_name']

    # TODO: enable when interactive account and role picker is implemented
    # interactive = sso_config.get('sso_interactive_auth') == 'true'
    # if interactive:
    #     required_vars = ['sso_start_url', 'sso_region']

    missing_requred_vars = [v[0] for v in missing_vars if v[1] in required_vars]
    if missing_requred_vars:
        raise InvalidSSOConfigError(
            'Missing ' + ', '.join(missing_requred_vars)
        )
    return sso_config


@click.command('credential-process')
@click.option('--profile', help='Extract settings from the given profile')
@click.option('--role-name')
@click.option('--account-id')
@click.option('--start-url')
@click.option('--region')

@click.option('--force-refresh', is_flag=True, help='Do not reuse cached AWS SSO token')
@click.option('--debug', is_flag=True, help='Write to the debugging log file')
def credential_process(
        profile,
        role_name,
        account_id,
        start_url,
        region,
        force_refresh,
        debug):

    if debug or os.environ.get('AWS_SSO_CREDENTIAL_PROCESS_DEBUG', '').lower() in ['1', 'true']:
        logging.basicConfig(level=logging.DEBUG, filename=LOG_FILE, filemode='w')
    else:
        logging.disable(logging.CRITICAL)

    LOGGER.info('Starting credential process at {}'.format(datetime.datetime.now().isoformat()))

    if role_name is None and os.environ.get('AWS_SSO_ROLE_NAME'):
        LOGGER.debug("Using role from env: {}".format(os.environ['AWS_SSO_ROLE_NAME']))
        role_name = os.environ['AWS_SSO_ROLE_NAME']

    if account_id is None and os.environ.get('AWS_SSO_ACCOUNT_ID'):
        LOGGER.debug("Using acccount from env: {}".format(os.environ['AWS_SSO_ACCOUNT_ID']))
        account_id = os.environ['AWS_SSO_ACCOUNT_ID']

    # if role_name and role_name.startswith('arn'):
    #     parts = role_name.split(':')
    #     account_id = parts[4]
    #     role_name = parts[5].split('/', 1)[1]

    if start_url is None and os.environ.get('AWS_SSO_START_URL'):
        start_url = os.environ['AWS_SSO_START_URL']

    if region is None and os.environ.get('AWS_SSO_REGION'):
        region = os.environ['AWS_SSO_REGION']

    session_kwargs = {}

    if profile:
        session_kwargs['profile'] = profile

    arg_config = {
        'sso_start_url': start_url,
        'sso_region': region,
        'sso_role_name': role_name,
        'sso_account_id': account_id,
    }

    LOGGER.info('CONFIG FROM ARGS: {}'.format(json.dumps(arg_config)))

    try:
        session = Session(**session_kwargs)

        if profile:
            profile_config = session.get_scoped_config()
            LOGGER.info('CONFIG FROM PROFILE: {}'.format(json.dumps(profile_config)))
        else:
            profile_config = {}

        config = get_config(arg_config, profile_config, logger=LOGGER)

        LOGGER.info('CONFIG: {}'.format(json.dumps(config)))

        if (config.get('sso_interactive_auth') or '').lower() == 'true':
            raise InvalidSSOConfigError('Interactive auth has been removed. See https://github.com/benkehoe/aws-sso-credential-process/issues/4')

        token_loader = get_token_loader(
            session=session,
            sso_region=config['sso_region'],
            force_refresh=force_refresh,
            logger=LOGGER,
        )

        if not config['sso_account_id']:
            #TODO: if interactive, prompt for account
            raise InvalidSSOConfigError('Missing account id')

        if not config['sso_role_name']:
            #TODO: if interactive, prompt for role
            raise InvalidSSOConfigError('Missing role')

        credentials = get_credentials(
            session=session,
            sso_region=config['sso_region'],
            start_url=config['sso_start_url'],
            account_id=config['sso_account_id'],
            role_name=config['sso_role_name'],
            token_loader=token_loader,
            logger=LOGGER,
        )

        output = {
            "Version": 1,
            "AccessKeyId": credentials['access_key'],
            "SecretAccessKey": credentials['secret_key'],
            "SessionToken": credentials['token'],
            # as provided the expiration isn't valid ISO8601 and that causes parsing errors for some SDKs
            "Expiration": credentials['expiry_time'].replace('UTC', 'Z'),
        }
        LOGGER.debug('CREDENTIALS: ' + json.dumps(output))

        print(json.dumps(output, separators=(',', ':')))
    except InteractiveAuthDisabledError as e:
        LOGGER.info('Auth needed but interactive auth disabled')
        print('Interactive auth disabled, use `aws sso login` and try again', file=sys.stderr)
        sys.exit(1)
    except InvalidSSOConfigError as e:
        LOGGER.error(e)
        print(e, file=sys.stderr)
        sys.exit(2)
    except AuthDispatchError as e:
        LOGGER.error(e)
        print(e, file=sys.stderr)
        sys.exit(3)
    except ClientError as e:
        LOGGER.error(e, exc_info=True)
        #TODO: print a different message for AccessDeniedException during CreateToken? -> user canceled login
        # boto_error_matches(e, 'CreateToken', 'AccessDeniedException')
        print('ERROR:', e, file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        LOGGER.error(e, exc_info=True)
        print('ERROR:', e, file=sys.stderr)
        sys.exit(5)

if __name__ == '__main__':
    credential_process(prog_name="python -m aws_sso_util.cli.credential_process")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
