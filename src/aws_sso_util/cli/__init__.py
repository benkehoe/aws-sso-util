import click

from .. import __version__

from .cfn import generate_template
from .configure_profile import configure_profile
from .credential_process import credential_process
from .populate_profiles import populate_profiles
from .lookup import lookup
from .assignments import assignments

@click.group(name="aws-sso-util")
@click.version_option(version=__version__, message='%(version)s')
def cli():
    pass

@cli.group()
def configure():
    pass

configure.add_command(configure_profile, "profile")
configure.add_command(populate_profiles, "populate")

cli.add_command(lookup)
cli.add_command(assignments)

cli.add_command(generate_template, "cfn")

cli.add_command(credential_process)

