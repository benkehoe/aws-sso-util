import os
import argparse
import logging
import json
import subprocess
import shlex
from collections import namedtuple

import botocore
from botocore.session import Session
from botocore.exceptions import ClientError, ProfileNotFound

import click

from ..sso import get_token_loader
from ..vendored_botocore.config_file_writer import ConfigFileWriter, write_values, get_config_filename

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
def generate_profile_name_format(input, separator):
    def process_component(c):
        if c in KNOWN_COMPONENTS:
            return "{" + c + "}"
        else:
            return c
    region_format = separator.join(process_component(c) for c in input.split(","))
    no_region_format = separator.join(process_component(c) for c in input.split(",") if c not in ["region", "short_region"])
    return region_format, no_region_format

def get_formatter(style, region_format, no_region_format):
    def proc_kwargs(kwargs):
        kwargs["short_region"] = get_short_region(kwargs["region"])
        kwargs["account_number"] = kwargs["account_id"]
        return kwargs
    if style == "default":
        def formatter(i, **kwargs):
            kwargs = proc_kwargs(kwargs)
            if i == 0:
                return no_region_format.format(**kwargs)
            else:
                return region_format.format(**kwargs)
        return formatter
    elif style == "always":
        def formatter(i, **kwargs):
            kwargs = proc_kwargs(kwargs)
            return region_format.format(**kwargs)
        return formatter
    else:
        raise KeyError("Unknown style {}".format(style))

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
        run_args = [command]
        for component in PROCESS_FORMATTER_ARGS:
            run_args.append(shlex.quote(kwargs[component]))
        try:
            result = subprocess.run(' '.join(run_args), shell=True, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            lines = [
                "Profile name process failed ({})".format(e.returncode)
            ]
            if e.stdout:
                lines.append(e.stdout.decode('utf-8'))
            if e.stderr:
                lines.append(e.stderr.decode('utf-8'))
            LOGGER.error("\n".join(lines))
            raise e
        return result.stdout.decode('utf-8').strip()
    return formatter

@click.command()
@click.option("--sso-start-url")
@click.option("--sso-region")

@click.option("--region", "-r", "regions", multiple=True)

@click.option("--config-defaults", "-d", multiple=True)
@click.option("--existing-config-action", type=click.Choice(["keep", "overwrite", "discard"]), default="keep")

@click.option("--profile-name-components", default="account_name,role_name,short_region")
@click.option("--profile-name-separator", "--sep", default="_")
@click.option("--profile-name-region-style", type=click.Choice(["default", "always"]), default="default")
@click.option("--profile-name-process")

@click.option("--force-refresh", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--debug", is_flag=True)
def populate_profiles(
        sso_start_url,
        sso_region,
        regions,
        config_defaults,
        existing_config_action,
        profile_name_components,
        profile_name_separator,
        profile_name_region_style,
        profile_name_process,
        force_refresh,
        dry_run,
        debug):

    logging.basicConfig()
    LOGGER.setLevel(logging.DEBUG if debug else logging.INFO)

    missing = []

    if not sso_start_url:
        sso_start_url = os.environ.get("AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL", os.environ.get("AWS_CONFIGURE_DEFAULT_SSO_START_URL"))
    if not sso_start_url:
        missing.append("--start-url")

    if not sso_region:
        sso_region = os.environ.get("AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION", os.environ.get("AWS_CONFIGURE_DEFAULT_SSO_REGION"))
    if not sso_region:
        missing.append("--sso-region")

    if not regions and "AWS_CONFIG_DEFAULT_REGION" in os.environ:
        regions = [os.environ["AWS_CONFIGURE_DEFAULT_REGION"]]
    if not regions:
        missing.append("--region")

    if missing:
        raise click.UsageError("Missing arguments: {}".format(", ".join(missing)))

    if config_defaults:
        config_defaults = dict(v.split("=", 1) for v in config_defaults)
    else:
        config_defaults = {}

    if profile_name_process:
        profile_name_formatter = get_process_formatter(profile_name_process)
    else:
        region_format, no_region_format = generate_profile_name_format(profile_name_components, profile_name_separator)
        LOGGER.debug("Profile name format (region):    {}".format(region_format))
        LOGGER.debug("Profile name format (no region): {}".format(no_region_format))
        profile_name_formatter = get_formatter(profile_name_region_style, region_format, no_region_format)

    try:
        profile_name_formatter(0, account_name='foo', account_id='bar', role_name='baz', region='us-east-1')
    except Exception as e:
        raise click.UsageError("Invalid profile name format: {}".format(e))

    session = Session()

    token_loader = get_token_loader(session,
            sso_region,
            interactive=True,
            force_refresh=force_refresh,
            logger=LOGGER)

    LOGGER.info("Logging in")
    token = token_loader(sso_start_url)

    LOGGER.debug("Token: {}".format(token))

    config = botocore.config.Config(
        region_name=sso_region,
        signature_version=botocore.UNSIGNED,
    )
    client = session.create_client("sso", config=config)

    LOGGER.info("Gathering accounts and roles")
    accounts = []
    list_accounts_args = {
        "accessToken": token
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
        LOGGER.debug("Getting roles for {}".format(account["accountId"]))
        list_role_args = {
            "accessToken": token,
            "accountId": account["accountId"],
        }

        while True:
            response = client.list_account_roles(**list_role_args)

            for role in response["roleList"]:
                for i, region in enumerate(regions):
                    profile_name = profile_name_formatter(i,
                        account_name=account["accountName"],
                        account_id=account["accountId"],
                        role_name=role["roleName"],
                        region=region,
                    )
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
            write_values(session, config.profile_name, config_values, config_file_writer=config_writer)
    else:
        LOGGER.info("Dry run for {} profiles".format(len(configs)))
        def write_config(profile_name, config_values):
            lines = [
                "[profile {}]".format(profile_name)
            ]
            for key, value in config_values.items():
                lines.append("{} = {}".format(key, value))
            lines.append("")
            print("\n".join(lines))

    for config in configs:
        LOGGER.debug("Processing config: {}".format(config))

        existing_values = {}
        if existing_config_action != "discard":
            try:
                existing_values = Session(profile=config.profile_name).get_scoped_config()
            except ProfileNotFound:
                pass

        config_values = {
            "sso_account_name": config.account_name,
            "sso_account_id": config.account_id,
            "sso_role_name": config.role_name,
            "sso_start_url": sso_start_url,
            "sso_region": sso_region,
            "region": config.region,
        }


        for k, v in config_defaults.items():
            if k in existing_values and existing_config_action in ["keep"]:
                continue
            config_values[k] = v

        LOGGER.debug("Config values for profile {}: {}".format(config.profile_name, config_values))

        write_config(config.profile_name, config_values)


if __name__ == "__main__":
    populate_profiles(prog_name="python -m aws_sso_util.cli.populate_profiles")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
