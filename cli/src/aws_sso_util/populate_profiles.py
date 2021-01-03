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

import sys
import os
import argparse
import logging
import json
import subprocess
import re
import shlex
from collections import namedtuple

import botocore
from botocore.session import Session
from botocore.exceptions import ClientError, ProfileNotFound
from botocore.compat import compat_shell_split as shell_split

import click

from aws_sso_lib.sso import get_token_fetcher
from aws_sso_lib.config import find_instances, SSOInstance
from aws_sso_lib.config_file_writer import ConfigFileWriter, write_values, get_config_filename, process_profile_name
from aws_sso_lib.compat import shell_quote, shell_join

from .utils import configure_logging, get_instance, GetInstanceError

from .configure_profile import (
    DEFAULT_START_URL_VARS,
    DEFAULT_SSO_REGION_VARS,
    DEFAULT_REGION_VARS,
    DISABLE_CREDENTIAL_PROCESS_VAR,
    CREDENTIAL_PROCESS_NAME_VAR,
    SET_CREDENTIAL_PROCESS_DEFAULT
)

DEFAULT_SEPARATOR = "."

LOGGER = logging.getLogger(__name__)

ConfigParams = namedtuple("ConfigParams", ["profile_name", "account_name", "account_id", "role_name", "region"])

def get_short_region(region):
    area, direction, num = region.split("-")
    dir_abbr = {
        "north": "no",
        "northeast": "ne",
        "east": "ea",
        "southeast": "se",
        "south": "so",
        "southwest": "sw",
        "west": "we",
        "northwest": "nw",
        "central": "ce",
    }
    return "".join([area, dir_abbr.get(direction, direction), num])

KNOWN_COMPONENTS = [
    "account_name",
    "account_id",
    "account_number",
    "role_name",
    "region",
    "short_region",
]
def generate_profile_name_format(input, separator, region_style):
    def process_component(c):
        if c == "default_style_region":
            if region_style == "short":
                c = "short_region"
            else:
                c = "region"
        if c in KNOWN_COMPONENTS:
            return "{" + c + "}"
        else:
            return c
    region_format = separator.join(process_component(c) for c in input.split(","))
    no_region_format = separator.join(process_component(c) for c in input.split(",") if c not in ["default_style_region", "region", "short_region"])
    return region_format, no_region_format

def get_formatter(include_region, region_format, no_region_format):
    def proc_kwargs(kwargs):
        kwargs["short_region"] = get_short_region(kwargs["region"])
        kwargs["account_number"] = kwargs["account_id"]
        return kwargs
    if include_region == "default":
        def formatter(i, **kwargs):
            kwargs = proc_kwargs(kwargs)
            if i == 0:
                return no_region_format.format(**kwargs)
            else:
                return region_format.format(**kwargs)
        return formatter
    elif include_region == "always":
        def formatter(i, **kwargs):
            kwargs = proc_kwargs(kwargs)
            return region_format.format(**kwargs)
        return formatter
    else:
        raise ValueError("Unknown include_region value {}".format(include_region))

PROCESS_FORMATTER_ARGS = [
    "account_name",
    "account_id",
    "role_name",
    "region",
    "short_region",
    "region_index",
]
def get_process_formatter(command):
    def formatter(i, **kwargs):
        kwargs["region_index"] = str(i)
        kwargs["short_region"] = get_short_region(kwargs["region"])
        run_args = shell_split(command)
        for component in PROCESS_FORMATTER_ARGS:
            run_args.append(kwargs[component])
        try:
            result = subprocess.run(shell_join(run_args), shell=True, stdout=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as e:
            lines = [
                "Profile name process failed ({})".format(e.returncode)
            ]
            if e.stdout:
                lines.append(e.stdout.decode("utf-8"))
            if e.stderr:
                lines.append(e.stderr.decode("utf-8"))
            LOGGER.error("\n".join(lines))
            raise e
        return result.stdout.decode("utf-8").strip()
    return formatter

def get_trim_formatter(account_name_patterns, role_name_patterns, formatter):
    def trim_formatter(i, **kwargs):
        for pattern in account_name_patterns:
            kwargs["account_name"] = re.sub(pattern, "", kwargs["account_name"])
        for pattern in role_name_patterns:
            kwargs["role_name"] = re.sub(pattern, "", kwargs["role_name"])
        return formatter(i, **kwargs)
    return trim_formatter

def get_safe_account_name(name):
    return re.sub(r"[\s]+", "-", name)

@click.command("populate")
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", help="The AWS region your AWS SSO instance is deployed in")

@click.option("--region", "-r", "regions", multiple=True, metavar="REGION", help="AWS region for the profiles, can provide multiple times")

@click.option("--dry-run", is_flag=True, help="Print the config to stdout instead of writing to your config file")

@click.option("--config-default", "-c", multiple=True, metavar="KEY=VALUE", help="Additional config field to set, can provide multiple times")
@click.option("--existing-config-action", type=click.Choice(["keep", "overwrite", "discard"]), default="keep", help="Action when config defaults conflict with existing settings")

@click.option("--components", "profile_name_components", metavar="VALUE,VALUE,...", default="account_name,role_name,default_style_region", help="Profile name components to join (comma-separated)")
@click.option("--separator", "--sep", "profile_name_separator", metavar="SEP", help=f"Separator for profile name components, default is '{DEFAULT_SEPARATOR}'")
@click.option("--include-region", "profile_name_include_region", type=click.Choice(["default", "always"]), default="default", help="By default, the first region is left off the profile name")
@click.option("--region-style", "profile_name_region_style", type=click.Choice(["short", "long"]), default="short", help="Default is five character region abbreviations")
@click.option("--trim-account-name", "profile_name_trim_account_name_patterns", multiple=True, default=[], help="Regex to remove from account names, can provide multiple times")
@click.option("--trim-role-name", "profile_name_trim_role_name_patterns", multiple=True, default=[], help="Regex to remove from role names, can provide multiple times")
@click.option("--profile-name-process")
@click.option("--safe-account-names/--raw-account-names", default=True, help="In profiles, replace any character sequences not in A-Za-z0-9-._ with a single -")

@click.option("--credential-process/--no-credential-process", default=None, help="Force enable/disable setting the credential process SDK helper")

@click.option("--force-refresh", is_flag=True, help="Re-login")
@click.option("--verbose", "-v", count=True)
def populate_profiles(
        sso_start_url,
        sso_region,
        regions,
        dry_run,
        config_default,
        existing_config_action,
        profile_name_components,
        profile_name_separator,
        profile_name_include_region,
        profile_name_region_style,
        profile_name_trim_account_name_patterns,
        profile_name_trim_role_name_patterns,
        profile_name_process,
        safe_account_names,
        credential_process,
        force_refresh,
        verbose):
    """Configure profiles for all accounts and roles.

    Writes a profile to your AWS config file (~/.aws/config) for every account and role you have access to,
    for the regions you specify.
    """

    configure_logging(LOGGER, verbose)

    missing = []

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
            sso_start_url_vars=DEFAULT_START_URL_VARS,
            sso_region_vars=DEFAULT_SSO_REGION_VARS,)
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    if not regions:
        for var_name in DEFAULT_REGION_VARS:
            value = os.environ.get(var_name)
            if value:
                LOGGER.debug(f"Got default region {value} from {var_name}")
                regions = [value]
                break
    if not regions:
        missing.append("--region")

    if missing:
        raise click.UsageError("Missing arguments: {}".format(", ".join(missing)))

    if config_default:
        config_default = dict(v.split("=", 1) for v in config_default)
    else:
        config_default = {}

    if not profile_name_separator:
        profile_name_separator = os.environ.get("AWS_CONFIGURE_SSO_DEFAULT_PROFILE_NAME_SEPARATOR") or DEFAULT_SEPARATOR

    if profile_name_process:
        profile_name_formatter = get_process_formatter(profile_name_process)
    else:
        region_format, no_region_format = generate_profile_name_format(profile_name_components, profile_name_separator, profile_name_region_style)
        LOGGER.debug("Profile name format (region):    {}".format(region_format))
        LOGGER.debug("Profile name format (no region): {}".format(no_region_format))
        profile_name_formatter = get_formatter(profile_name_include_region, region_format, no_region_format)
        if profile_name_trim_account_name_patterns or profile_name_trim_role_name_patterns:
            profile_name_formatter = get_trim_formatter(profile_name_trim_account_name_patterns, profile_name_trim_role_name_patterns, profile_name_formatter)

    try:
        profile_name_formatter(0, account_name="foo", account_id="bar", role_name="baz", region="us-east-1")
    except Exception as e:
        raise click.UsageError("Invalid profile name format: {}".format(e))

    session = Session()

    token_fetcher = get_token_fetcher(session,
            instance.region,
            interactive=True,
            )

    LOGGER.info(f"Logging in to {instance.start_url}")
    token = token_fetcher.fetch_token(instance.start_url, force_refresh=force_refresh)

    LOGGER.debug("Token: {}".format(token))

    config = botocore.config.Config(
        region_name=instance.region,
        signature_version=botocore.UNSIGNED,
    )
    client = session.create_client("sso", config=config)

    LOGGER.info("Gathering accounts and roles")
    accounts = []
    list_accounts_args = {
        "accessToken": token["accessToken"]
    }
    while True:
        response = client.list_accounts(**list_accounts_args)

        accounts.extend(response["accountList"])

        next_token = response.get("nextToken")
        if not next_token:
            break
        else:
            list_accounts_args["nextToken"] = response["nextToken"]

    LOGGER.debug("Account list: {} {}".format(len(accounts), accounts))

    configs = []
    for account in accounts:
        if not account.get("accountName"):
            account["accountName"] = account["accountId"]

        LOGGER.debug("Getting roles for {}".format(account["accountId"]))
        list_role_args = {
            "accessToken": token["accessToken"],
            "accountId": account["accountId"],
        }

        while True:
            response = client.list_account_roles(**list_role_args)

            for role in response["roleList"]:
                for i, region in enumerate(regions):
                    if safe_account_names:
                        account_name_for_profile = get_safe_account_name(account["accountName"])
                    else:
                        account_name_for_profile = account["accountName"]

                    profile_name = profile_name_formatter(i,
                        account_name=account_name_for_profile,
                        account_id=account["accountId"],
                        role_name=role["roleName"],
                        region=region,
                    )
                    if profile_name == "SKIP":
                        continue
                    configs.append(ConfigParams(profile_name, account["accountName"], account["accountId"], role["roleName"], region))

            next_token = response.get("nextToken")
            if not next_token:
                break
            else:
                list_role_args["nextToken"] = response["nextToken"]


    configs.sort(key=lambda v: v.profile_name)

    LOGGER.debug("Got configs: {}".format(configs))

    if not dry_run:
        LOGGER.info("Writing {} profiles to {}".format(len(configs), get_config_filename(session)))

        config_writer = ConfigFileWriter()
        def write_config(profile_name, config_values):
            # discard because we're already loading the existing values
            write_values(session, profile_name, config_values, existing_config_action="discard", config_file_writer=config_writer)
    else:
        LOGGER.info("Dry run for {} profiles".format(len(configs)))
        def write_config(profile_name, config_values):
            lines = [
                "[profile {}]".format(process_profile_name(profile_name))
            ]
            for key, value in config_values.items():
                lines.append("{} = {}".format(key, value))
            lines.append("")
            print("\n".join(lines))

    for config in configs:
        LOGGER.debug("Processing config: {}".format(config))

        config_values = {}
        existing_profile = False
        existing_config = {}
        if existing_config_action != "discard":
            try:
                existing_config = Session(profile=config.profile_name).get_scoped_config()
                config_values.update(existing_config)
                existing_profile = True
            except ProfileNotFound:
                pass

        config_values.update({
            "sso_start_url": instance.start_url,
            "sso_region": instance.region,
        })
        if config.account_name != config.account_id:
            config_values["sso_account_name"] = config.account_name
        config_values.update({
            "sso_account_id": config.account_id,
            "sso_role_name": config.role_name,
            "region": config.region,
        })

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
            config_values["credential_process"] = f"{credential_process_name} --profile {shell_quote(config.profile_name)}"
        elif set_credential_process is False:
            config_values.pop("credential_process", None)

        config_values["sso_auto_populated"] = "true"

        LOGGER.debug("Config values for profile {}: {}".format(config.profile_name, config_values))

        write_config(config.profile_name, config_values)


if __name__ == "__main__":
    populate_profiles(prog_name="python -m aws_sso_util.populate_profiles")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
