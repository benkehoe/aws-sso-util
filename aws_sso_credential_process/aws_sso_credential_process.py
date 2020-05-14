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
import webbrowser
import json
import traceback
import logging
import datetime
import io
import textwrap
import collections

#TODO: use getpass functionality to get around captured stdout & stderr
def print_tty(message):
    print(message, file=sys.stderr)
def prompt_tty(message):
    raise NotImplementedError

from botocore.session import Session
from botocore.credentials import JSONFileCache
from botocore.exceptions import ClientError

from .utils import SSOTokenFetcher
from .credentials import SSOCredentialFetcher

__version__ = '0.2.2'

class InvalidSSOConfigError(Exception):
    pass

class AuthDispatchError(Exception):
    pass

class InteractiveAuthDisabledError(Exception):
    pass

# https://gist.github.com/benkehoe/c61337ddb0c213bb35d05aaa8fad2577
BotoErrorInfo = collections.namedtuple('BotoErrorInfo', ['code', 'message', 'http_status_code', 'operation_name'])
def get_error_info(client_error):
    return BotoErrorInfo(client_error.response.get('Error', {}).get('Code'), client_error.response.get('Error', {}).get('Message'), client_error.response.get('ResponseMetadata', {}).get('HTTPStatusCode'), client_error.operation_name)

def boto_error_matches(client_error, *args):
    errs = tuple(e for e in (client_error.response.get('Error', {}).get('Code'), client_error.response.get('Error', {}).get('Message'), client_error.response.get('ResponseMetadata', {}).get('HTTPStatusCode'), client_error.operation_name) if e is not None)
    return any(arg in errs for arg in args)

SSO_TOKEN_DIR = os.path.expanduser(
    os.path.join('~', '.aws', 'sso', 'cache')
)

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

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('--profile', help='Extract settings from the given profile')

    parser.add_argument('--role-name')
    parser.add_argument('--account-id')
    parser.add_argument('--start-url')
    parser.add_argument('--region')

    interactive_group = parser.add_mutually_exclusive_group()
    interactive_group.add_argument('--interactive', '-i', action='store_const', const=True, dest='interactive', help='Enable interactive auth')
    interactive_group.add_argument('--noninteractive', '-n', action='store_const', const=False, dest='interactive', help='Disable interactive auth')

    parser.add_argument('--force-refresh', action='store_true', help='Do not reuse cached AWS SSO token')
    parser.add_argument('--debug', action='store_true', help='Write to the debugging log file')

    parser.add_argument('--version', action='store_true')

    args = parser.parse_args()

    if args.version:
        print(__version__)
        parser.exit()

    if args.debug or os.environ.get('AWS_SSO_CREDENTIAL_PROCESS_DEBUG', '').lower() in ['1', 'true']:
        logging.basicConfig(level=logging.DEBUG, filename=LOG_FILE, filemode='w')
    else:
        logging.disable(logging.CRITICAL)

    LOGGER.info(f'Starting credential process at {datetime.datetime.now().isoformat()}')

    if args.role_name is None and os.environ.get('AWS_SSO_ROLE_NAME'):
        LOGGER.debug(f"Using role from env: {os.environ['AWS_SSO_ROLE_NAME']}")
        args.role_name = os.environ['AWS_SSO_ROLE_NAME']

    if args.account_id is None and os.environ.get('AWS_SSO_ACCOUNT_ID'):
        LOGGER.debug(f"Using acccount from env: {os.environ['AWS_SSO_ACCOUNT_ID']}")
        args.account_id = os.environ['AWS_SSO_ACCOUNT_ID']

    # if args.role_name and args.role_name.startswith('arn'):
    #     parts = args.role_name.split(':')
    #     args.account_id = parts[4]
    #     args.role_name = parts[5].split('/', 1)[1]

    if args.start_url is None and os.environ.get('AWS_SSO_START_URL'):
        args.start_url = os.environ['AWS_SSO_START_URL']

    if args.region is None and os.environ.get('AWS_SSO_REGION'):
        args.region = os.environ['AWS_SSO_REGION']

    if args.interactive is None:
        if os.environ.get('AWS_SSO_INTERACTIVE_AUTH'):
            LOGGER.debug(f"Setting interactive auth from env: {os.environ['AWS_SSO_INTERACTIVE_AUTH']}")
            args.interactive = os.environ['AWS_SSO_INTERACTIVE_AUTH'].lower() in ['true', '1']
        else:
            args.interactive = False

    session_kwargs = {}

    if args.profile:
        session_kwargs['profile'] = args.profile

    arg_config = {
        'sso_start_url': args.start_url,
        'sso_region': args.region,
        'sso_role_name': args.role_name,
        'sso_account_id': args.account_id,
        'sso_interactive_auth': 'true' if args.interactive else 'false',
    }

    LOGGER.info(f'CONFIG FROM ARGS: {json.dumps(arg_config)}')

    try:
        session = Session(**session_kwargs)

        if args.profile:
            profile_config = session.get_scoped_config()
            LOGGER.info(f'CONFIG FROM PROFILE: {json.dumps(profile_config)}')
        else:
            profile_config = {}

        config = get_config(arg_config, profile_config)

        LOGGER.info(f'CONFIG: {json.dumps(config)}')

        interactive = config['sso_interactive_auth'].lower() == 'true'

        token_loader = get_token_loader(
            session=session,
            sso_region=config['sso_region'],
            interactive=interactive,
            force_refresh=args.force_refresh,
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
            token_loader=token_loader
        )

        output = {
            "Version": 1,
            "AccessKeyId": credentials['access_key'],
            "SecretAccessKey": credentials['secret_key'],
            "SessionToken": credentials['token'],
            "Expiration": credentials['expiry_time']
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

def get_config(arg_config, profile_config):
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

class OpenBrowserHandler(object):
    def __init__(self, outfile=None, open_browser=None):
        self._outfile = outfile or sys.stderr
        if open_browser is None:
            open_browser = webbrowser.open_new_tab
        self._open_browser = open_browser

    def __call__(self, userCode, verificationUri,
                 verificationUriComplete, **kwargs):
        message = textwrap.dedent(f"""\
        AWS SSO login required.
        Attempting to open the SSO authorization page in your default browser.
        If the browser does not open or you wish to use a different device to
        authorize this request, open the following URL:

        {verificationUri}

        Then enter the code:

        {userCode}
        """)

        print_tty(message)

        if self._open_browser:
            try:
                return self._open_browser(verificationUriComplete)
            except InteractiveAuthDisabledError:
                raise
            except Exception as e:
                raise AuthDispatchError('Failed to open browser') from e
                # LOG.debug('Failed to open browser:', exc_info=True)

def _non_interactive_auth_raiser(*args, **kwargs):
    raise InteractiveAuthDisabledError

def get_token_loader(session, sso_region, interactive=False, token_cache=None,
                 on_pending_authorization=None, force_refresh=False):

    if token_cache is None:
        token_cache = JSONFileCache(SSO_TOKEN_DIR)

    if on_pending_authorization is None:
        if interactive:
            on_pending_authorization = OpenBrowserHandler(
                outfile=sys.stderr,
                open_browser=webbrowser.open_new_tab,
            )
        else:
            on_pending_authorization = _non_interactive_auth_raiser

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
        LOGGER.debug(f'TOKEN RESPONSE: {token_response}')
        return token_response['accessToken']

    return token_loader


def get_credentials(session, sso_region, start_url, account_id, role_name, token_loader, cache=None):

    if cache is None:
        cache = JSONFileCache(SSO_TOKEN_DIR)

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
