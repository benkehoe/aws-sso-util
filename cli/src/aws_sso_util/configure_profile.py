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
import logging
import textwrap

import botocore
from botocore.exceptions import ProfileNotFound

import click

from aws_sso_lib.config import find_instances, SSOInstance
from aws_sso_lib.config_file_writer import write_values
from aws_sso_lib.compat import shell_quote

from .utils import configure_logging, get_instance, GetInstanceError

LOGGER = logging.getLogger(__name__)

DEFAULT_START_URL_VARS  = ["AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL", "AWS_CONFIGURE_DEFAULT_SSO_START_URL"]
DEFAULT_SSO_REGION_VARS = ["AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION",    "AWS_CONFIGURE_DEFAULT_SSO_REGION"]
DEFAULT_REGION_VARS = ["AWS_CONFIGURE_DEFAULT_REGION", "AWS_DEFAULT_REGION"]
DISABLE_CREDENTIAL_PROCESS_VAR = "AWS_CONFIGURE_SSO_DISABLE_CREDENTIAL_PROCESS"

CREDENTIAL_PROCESS_NAME_VAR= "AWS_SSO_CREDENTIAL_PROCESS_NAME"

SET_CREDENTIAL_PROCESS_DEFAULT = True

@click.command("profile")
@click.argument("profile", metavar="PROFILE_NAME")
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account-id", "-a", "account", metavar="ACCOUNT", help="The AWS account for the profile")
@click.option("--role-name", "-r", "role", metavar="ROLE", help="The SSO role (also the Permission Set name) to assume in account")
@click.option("--region", metavar="REGION", help="The AWS region the profile will use")
@click.option("--output", "-o", metavar="CLI_OUTPUT_FORMAT", help="Set the CLI output format for the profile")
@click.option("--config-default", "-c", multiple=True, metavar="KEY=VALUE", help="Additional config field to set, can provide multiple times")
@click.option("--existing-config-action", type=click.Choice(["keep", "overwrite", "discard"]), default="keep", help="Action when config defaults conflict with existing settings")
@click.option("--interactive/--non-interactive", default=True, help="If not all required settings are provided, use an interactive prompt")
@click.option("--credential-process/--no-credential-process", default=None, help="Force enable/disable setting the credential process SDK helper")
@click.option("--verbose", "-v", count=True)
def configure_profile(
        profile,
        sso_start_url,
        sso_region,
        account,
        role,
        region,
        output,
        config_default,
        existing_config_action,
        interactive,
        credential_process,
        verbose):
    """Configure a single profile.

    You can set all the options for a profile, or let it prompt you interactively to select from available accounts and roles.

    \b
    The values required for a complete profile are:
    --sso-start-url
    --sso-region
    --account-id
    --role-name
    --region

    --sso-start-url and --sso-region are not needed if a single value can be found for them in your ~/.aws/config
    or in the environment variables AWS_DEFAULT_SSO_START_URL and AWS_DEFAULT_SSO_REGION.
    """
    configure_logging(LOGGER, verbose)

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
            sso_start_url_vars=DEFAULT_START_URL_VARS,
            sso_region_vars=DEFAULT_SSO_REGION_VARS,)
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    sso_start_url = instance.start_url if instance else None
    sso_region    = instance.region    if instance else None

    if config_default:
        config_default = dict(v.split("=", 1) for v in config_default)
    else:
        config_default = {}

    session = botocore.session.Session(profile=profile)

    config_values = {}
    existing_profile = False
    existing_config = {}
    if existing_config_action != "discard":
        try:
            existing_config = session.get_scoped_config()
            config_values.update(existing_config)
            existing_profile = True
        except ProfileNotFound:
            pass

    if sso_start_url:
        config_values["sso_start_url"] = sso_start_url

    if sso_region:
        config_values["sso_region"] = sso_region

    if account:
        config_values["sso_account_id"] = account

    if role:
        config_values["sso_role_name"] = role

    if region:
        config_values["region"] = region
    elif "region" not in config_values:
        for var_name in DEFAULT_REGION_VARS:
            value = os.environ.get(var_name)
            if value:
                LOGGER.debug(f"Got default region {value} from {var_name}")
                config_values["region"] = value
                break

    if output:
        config_values["output"] = output

    for k, v in config_default.items():
        if k in existing_config and existing_config_action in ["keep"]:
            continue
        config_values[k] = v

    if credential_process is not None:
        set_credential_process = credential_process
    elif os.environ.get(DISABLE_CREDENTIAL_PROCESS_VAR, "").lower() in ["1", "true"]:
        set_credential_process = False
    else:
        set_credential_process = SET_CREDENTIAL_PROCESS_DEFAULT

    if set_credential_process:
        credential_process_name = os.environ.get(CREDENTIAL_PROCESS_NAME_VAR) or "aws-sso-util credential-process"
        config_values["credential_process"] = f"{credential_process_name} --profile {shell_quote(profile)}"
    elif set_credential_process is False:
        config_values.pop("credential_process", None)

    required_keys = [
        "sso_start_url",
        "sso_region",
        "sso_account_id",
        "sso_role_name",
        "region"
    ]

    missing_keys = [k for k in required_keys if k not in config_values]

    if missing_keys and not interactive:
        LOGGER.error(f"Missing profile options {', '.join(missing_keys)}")
        sys.exit(1)
    else:
        LOGGER.debug(f"Missing keys: {', '.join(missing_keys)}")

    # discard because we've already loading the existing values
    write_values(session, profile, config_values, existing_config_action="discard")

    if not missing_keys:
        return

    try:
        result = subprocess.run(["aws", "--version"], capture_output=True)
        cli_version = parse_cli_version(result.stdout.decode("utf-8"))
        if cli_version.startswith("1."):
            LOGGER.warn(textwrap.dedent(f"""\
            Your profile has been written, but is not complete.
            You have the AWS CLI version {cli_version}, which does not support AWS SSO.
            If you install the AWS CLI v2, aws-sso-util configure profile can interactively
            prompt you for the necessary fields. Details here:
            https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"""))
            sys.exit(2)
    except FileNotFoundError:
        LOGGER.warn(textwrap.dedent("""\
            Your profile has been written, but is not complete.
            If you install the AWS CLI v2, aws-sso-util configure profile can interactively
            prompt you for the necessary fields. Details here:
            https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"""))
        sys.exit(2)

    result = subprocess.run(f"aws configure sso --profile {shell_quote(profile)}", shell=True)

    if result.returncode:
        # this doesn't appear to work
        # LOGGER.error(f"Interactive configuration existed without success, restoring previous values")
        # write_values(session, profile, existing_config)
        sys.exit(10+result.returncode)

def parse_cli_version(output):
    d = dict(part.split("/", 1) for part in output.split(" "))
    LOGGER.debug(f"AWS CLI version info: {d}")
    return d.get("aws-cli", "UNKNOWN")

if __name__ == "__main__":
    configure_profile(prog_name="python -m aws_sso_util.configure_profile")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
