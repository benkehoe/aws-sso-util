import argparse
from collections import namedtuple, OrderedDict
from pathlib import Path
import logging
import sys

import boto3

import click

from .. import api_utils
from ..cfn.config import Config
from ..cfn import resources, templates, utils

LOGGER = logging.getLogger("sso_cfn")

def param_loader(ctx, param, value):
    if not value:
        return {}
    d = []
    for p in value.split(","):
        if "=" in p:
            d.append((p.split("=", 1)))
        else:
            d.append((p, None))
    return dict(d)

@click.command()
@click.argument("config_file", required=True, nargs=-1, type=click.File("r"))

@click.option("--profile", help="AWS profile to use to retrieve SSO instance and/or accounts from OUs")
@click.option("--sso-instance", "--ins", help="If not provided, will be retrieved from your account")

@click.option("--template-file-suffix")
@click.option("--output-dir")

@click.option("--base-template-file", type=click.File("r"), help="Base template to build from")
@click.option("--template-parameters", callback=param_loader, help="String-type parameters on the template")

@click.option("--max-resources-per-template", type=int, default=templates.MAX_RESOURCES_PER_TEMPLATE)
@click.option("--max-concurrent-assignments", type=int, default=templates.MAX_CONCURRENT_ASSIGNMENTS)

@click.option("--verbose", "-v", count=True)

def generate_template(
        config_file,
        profile,
        sso_instance,
        template_file_suffix,
        output_dir,
        base_template_file,
        template_parameters,
        max_resources_per_template,
        max_concurrent_assignments,
        verbose):
    logging.basicConfig(format="{message}", style="{")
    if verbose >= 1:
        LOGGER.setLevel(logging.DEBUG)
    else:
        LOGGER.setLevel(logging.INFO)
    if verbose == 2:
        logging.getLogger().setLevel(logging.INFO)
    elif verbose == 3:
        logging.getLogger().setLevel(logging.DEBUG)

    api_utils.PROFILE = profile
    api_utils.SSO_INSTANCE = sso_instance

    if not template_file_suffix:
        template_file_suffix = ".yaml"
    elif not template_file_suffix.endswith(".yaml"):
        template_file_suffix = template_file_suffix + ".yaml"

    if base_template_file:
        base_template = utils.load_yaml(base_template_file)
    else:
        base_template = None

    Input = namedtuple("Input", ["base_path", "stem", "assignments", "permission_sets"])
    inputs = []

    for config_file_fp in config_file:
        LOGGER.info(f"Loading config file {config_file_fp.name}")
        config_file_path = Path(config_file_fp.name)
        base_path = config_file_path.parent
        stem = config_file_path.stem

        data = utils.load_yaml(config_file_fp)
        LOGGER.debug(f"Config file contents:\n{utils.dump_yaml(data)}")

        config = Config()
        config.load(data, logger=LOGGER)

        if config.instance and sso_instance and config.instance != sso_instance:
            LOGGER.warning(f"Config instance {config.instance} does not match input instance {sso_instance}")
        if not config.instance:
            config.instance = api_utils.get_sso_instance(logger=LOGGER)

        if not (config.groups or config.users):
            LOGGER.fatal(f"No principals specified in {config_file_path}")
            sys.exit(1)
        if not config.permission_sets:
            LOGGER.fatal(f"No permission sets specified in {config_file_path}")
            sys.exit(1)
        if not (config.ous or config.accounts):
            LOGGER.fatal(f"No targets specified in {config_file_path}")
            sys.exit(1)

        assignments, permission_sets = resources.get_resources_from_config(
            config,
            ou_fetcher=lambda ou: api_utils.get_accounts_for_ou(ou, logger=LOGGER),
            logger=LOGGER)

        LOGGER.debug(f"assignment refs {assignments.references}")
        LOGGER.debug(f"ps refs {permission_sets.references}")

        LOGGER.debug(f"assignment res {utils.dump_yaml(OrderedDict({v.get_resource_name(): v.get_resource() for v in assignments if v.get_resource_name()}))}")
        LOGGER.debug(f"ps res {utils.dump_yaml(OrderedDict({v.get_resource_name(): v.get_resource() for v in permission_sets if v.get_resource_name()}))}")

        if output_dir:
            base_path = Path(output_dir)
        else:
            base_path = base_path / "templates"

        inputs.append(Input(
            base_path=base_path,
            stem=stem,
            assignments=assignments,
            permission_sets=permission_sets,
        ))

    for input in inputs:
        LOGGER.debug(f"input: {input}")

        if base_template:
            num_parent_resources = len(base_template.get("Resources", {}))
        else:
            num_parent_resources = 0

        parent_template = templates.resolve_templates(
            input.assignments,
            input.permission_sets,
            max_resources_per_template=max_resources_per_template,
            num_parent_resources=num_parent_resources,
        )

        parent_template_to_write, child_templates_to_write = parent_template.get_templates(
            input.base_path,
            input.stem,
            template_file_suffix,
            base_template=base_template,
            parameters=template_parameters,
            max_concurrent_assignments=max_concurrent_assignments
        )

        parent_path, parent_data = parent_template_to_write
        LOGGER.info(f"Writing template at path {parent_path}")
        Path(parent_path).parent.mkdir(parents=True, exist_ok=True)
        with open(parent_path, "w") as fp:
            utils.dump_yaml(parent_data, fp)

        for child_path, child_data in child_templates_to_write:
            LOGGER.info(f"Writing child template at path {child_path}")
            Path(child_path).parent.mkdir(parents=True, exist_ok=True)
            with open(child_path, "w") as fp:
                utils.dump_yaml(child_data, fp)

if __name__ == "__main__":
    generate_template(prog_name="python -m aws_sso_util.cli.cfn")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
