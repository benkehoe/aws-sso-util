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

from ..config import find_instances, SSOInstance
from ..vendored_botocore.config_file_writer import write_values
from .utils import configure_logging

LOGGER = logging.getLogger(__name__)

DEFAULT_START_URL_VARS  = ["AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL", "AWS_CONFIGURE_DEFAULT_SSO_START_URL"]
DEFAULT_SSO_REGION_VARS = ["AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION",    "AWS_CONFIGURE_DEFAULT_SSO_REGION"]
DEFAULT_REGION_VARS = ["AWS_CONFIGURE_DEFAULT_REGION", "AWS_DEFAULT_REGION"]
DISABLE_CREDENTIAL_PROCESS_VAR = "AWS_CONFIGURE_SSO_DISABLE_CREDENTIAL_PROCESS"

@click.command("configure-profile")
@click.argument("profile")
@click.option("--sso-start-url", "-u")
@click.option("--sso-region")
@click.option("--account-id", "-a")
@click.option("--role-name", "-r")
@click.option("--region")
@click.option("--output", "-o")
@click.option("--config-default", "-c", multiple=True)
@click.option("--existing-config-action", type=click.Choice(["keep", "overwrite", "discard"]), default="keep")
@click.option("--interactive/--non-interactive", default=True)
@click.option("--credential-process/--no-credential-process", default=None)
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
    configure_logging(LOGGER, verbose)

    instances, specifier, all_instances = find_instances(
        profile_name=None,
        profile_source=None,
        start_url=sso_start_url,
        start_url_source="CLI input",
        region=sso_region,
        region_source="CLI input",
        start_url_vars=DEFAULT_START_URL_VARS,
        region_vars=DEFAULT_SSO_REGION_VARS,
    )

    if not instances and all_instances:
        LOGGER.fatal((
            f"No AWS SSO config matched {specifier.to_str(region=True)} " +
            f"from {SSOInstance.to_strs(all_instances)}"))
        sys.exit(1)


    if len(instances) > 1:
        LOGGER.fatal(f"Found {len(instances)} SSO configs, please specify one or use --all: {SSOInstance.to_strs(instances)}")
        sys.exit(1)

    instance = instances[0] if instances else None

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
    elif os.environ.get(DISABLE_CREDENTIAL_PROCESS_VAR):
        set_credential_process = os.environ.get(DISABLE_CREDENTIAL_PROCESS_VAR, "").lower() not in ["1", "true"]
    else:
        set_credential_process = None

    if set_credential_process:
        config_values["credential_process"] = f"aws-sso-util credential-process --profile {profile}"
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

    write_values(session, profile, config_values)

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

    result = subprocess.run(f"aws configure sso --profile {profile}", shell=True)

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
    configure_profile(prog_name="python -m aws_sso_util.cli.configure_profile")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
