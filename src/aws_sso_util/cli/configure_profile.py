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

import argparse
import os
import subprocess
import sys

import click

@click.command('configure-profile')
@click.argument('profile')
@click.option('--sso-start-url')
@click.option('--sso-region')
@click.option("--credential-process/--no-credential-process", default=None)
def configure_profile(
        profile,
        sso_start_url,
        sso_region,
        credential_process):
    def get(name):
        return subprocess.run(['aws', 'configure', 'get', 'profile.{}.{}'.format(profile, name)], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def set(name, value):
        subprocess.run(['aws', 'configure', 'set', 'profile.{}.{}'.format(profile, name), value or ''], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    default_sso_start_url =  os.environ.get('AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL',  os.environ.get('AWS_CONFIGURE_DEFAULT_SSO_START_URL'))
    default_sso_region    =  os.environ.get('AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION',     os.environ.get('AWS_CONFIGURE_DEFAULT_SSO_REGION'))

    if sso_start_url:
        set('sso_start_url', sso_start_url)
    elif not get('sso_start_url') and default_sso_start_url:
        set('sso_start_url', default_sso_start_url)

    if sso_region:
        set('sso_region', sso_region)
    elif not get('sso_region') and default_sso_region:
        set('sso_region', default_sso_region)

    result = subprocess.run('aws configure sso --profile {}'.format(profile), shell=True).returncode

    if result:
        sys.exit(result)

    add_credential_process = os.environ.get('AWS_CONFIGURE_SSO_DISABLE_CREDENTIAL_PROCESS', '').lower() not in ['1', 'true']
    if credential_process is not None:
        add_credential_process = credential_process

    if add_credential_process:
        credential_process_opts = ''
        set('credential_process', 'aws-sso-util credential-process --profile {profile}{opts}'.format(profile=profile, opts=credential_process_opts))

if __name__ == '__main__':
    configure_profile(prog_name="python -m aws_sso_util.cli.configure_profile")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter

