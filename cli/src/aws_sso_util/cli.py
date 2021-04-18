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

import click

from . import __version__

from .assignments import assignments
from .cfn import generate_template
from .check import check
from .configure_profile import configure_profile
from .credential_process import credential_process
from .deploy_macro import deploy_macro
from .login import login
from .logout import logout
from .lookup import lookup
from .populate_profiles import populate_profiles
from .roles import roles

@click.group(name="aws-sso-util")
@click.version_option(version=__version__, message='%(version)s')
def cli():
    pass

@cli.group()
def configure():
    """Commands to set up ~/.aws/config."""
    pass

configure.add_command(configure_profile, "profile")
configure.add_command(populate_profiles, "populate")

cli.add_command(login)
cli.add_command(logout)
cli.add_command(roles)
cli.add_command(check)

@cli.group()
def admin():
    """Commands for AWS SSO administration."""
    pass

admin.add_command(lookup)
admin.add_command(assignments)

# admin.add_command(deploy_macro)
admin.add_command(generate_template, "cfn")

cli.add_command(credential_process)

_list_commands = cli.list_commands
def list_commands(ctx):
    return [c for c in _list_commands(ctx) if c != "credential-process"]

cli.list_commands = list_commands

