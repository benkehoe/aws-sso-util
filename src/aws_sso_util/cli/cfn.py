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

import argparse
from collections import namedtuple, OrderedDict
from pathlib import Path
import logging
import sys
import os

import boto3

import click

from .. import api_utils
from ..cfn.config import Config, ConfigError, validate_config, GenerationConfig
from ..cfn import resources, templates, macro, utils

from .utils import configure_logging

Input = namedtuple("Input", ["base_path", "stem", "assignments", "permission_sets", "base_template"])

TemplateProcessInput = namedtuple("TemplateProcessInput", [
    "base_path",
    "base_stem",
    "base_template",
    "generation_config",
    "max_stack_resources",
    "items"
])
TemplateProcessInputItem = namedtuple("TemplateProcessInput", [
    "stem",
    "resource_collection",
])

LOGGER = logging.getLogger(__name__)

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

@click.option("--macro", is_flag=True, help="Process templates with macro")

@click.option("--profile", help="AWS profile to use to retrieve SSO instance and/or accounts from OUs")
@click.option("--sso-instance", "--ins", help="If not provided, will be retrieved from your account")

@click.option("--template-file-suffix")
@click.option("--output-dir")

@click.option("--base-template-file", type=click.File("r"), help="Base template to build from")
@click.option("--template-parameters", callback=param_loader, help="String-type parameters on the template")

@click.option("--max-resources-per-template", type=int)
@click.option("--max-concurrent-assignments", type=int)
@click.option("--max-assignments-allocation", type=int)
@click.option("--num-child-stacks", type=int)

@click.option("--verbose", "-v", count=True)
def generate_template(
        config_file,
        macro,
        profile,
        sso_instance,
        template_file_suffix,
        output_dir,
        base_template_file,
        template_parameters,
        max_resources_per_template,
        max_concurrent_assignments,
        max_assignments_allocation,
        num_child_stacks,
        verbose):
    configure_logging(LOGGER, verbose)

    if macro and base_template_file:
        raise click.UsageError("--base-template-file not allowed with --macro")
    if macro and template_parameters:
        raise click.UsageError("--template-parameters not allowed with --macro")

    generation_config = GenerationConfig()

    generation_config.set(
        max_resources_per_template=max_resources_per_template,
        max_concurrent_assignments=max_concurrent_assignments,
        max_assignments_allocation=max_assignments_allocation,
        num_child_stacks=num_child_stacks,
    )

    session = boto3.Session(profile_name=profile)

    ids = api_utils.Ids(lambda: session, sso_instance, identity_store_id=None)

    ou_fetcher = lambda ou, recursive: [a["Id"] for a in api_utils.get_accounts_for_ou(session, ou, recursive)]

    if not template_file_suffix:
        template_file_suffix = ".yaml"
    elif not template_file_suffix.endswith(".yaml"):
        template_file_suffix = template_file_suffix + ".yaml"

    if base_template_file:
        base_template = utils.load_yaml(base_template_file)
        base_template_path = Path(base_template_file.name).resolve()
        prev_len = len(config_file)
        config_file = [c for c in config_file if Path(c.name).resolve() != base_template_path]
        if len(config_file) != prev_len:
            LOGGER.debug("Removed base template file from list of config files")
    else:
        base_template = None

    if macro:
        template_process_inputs = process_macro(
            config_file=config_file,
            session=session,
            ids=ids,
            ou_fetcher=ou_fetcher,
            template_file_suffix=template_file_suffix,
            output_dir=output_dir,
            base_generation_config=generation_config,
        )
    else:
        template_process_inputs = process_config(
            config_file=config_file,
            session=session,
            ids=ids,
            ou_fetcher=ou_fetcher,
            template_file_suffix=template_file_suffix,
            output_dir=output_dir,
            base_template=base_template,
            base_generation_config=generation_config,
        )

    templates_to_write = process_templates(
        template_process_inputs=template_process_inputs,
        template_file_suffix=template_file_suffix,
    )

    write_templates(templates_to_write)

def process_config(
    config_file,
    session,
    ids,
    ou_fetcher,
    template_file_suffix,
    output_dir,
    base_template,
    base_generation_config):
    template_process_inputs = {}

    for config_file_fp in config_file:
        LOGGER.info(f"Loading config file {config_file_fp.name}")
        config_file_path = Path(config_file_fp.name)
        if output_dir:
            base_path = Path(output_dir)
        else:
            base_path = config_file_path.parent / "templates"
        stem = config_file_path.stem

        data = utils.load_yaml(config_file_fp)
        LOGGER.debug(f"Config file contents:\n{utils.dump_yaml(data)}")

        config = Config()
        config.load(data)

        generation_config = base_generation_config.copy()
        generation_config.load(data)

        try:
            validate_config(config, ids)
        except ConfigError as e:
            LOGGER.fatal(f"{e!s} in {config_file_path}")
            sys.exit(1)

        resource_collection = resources.get_resources_from_config(
            config,
            ou_fetcher=ou_fetcher)

        LOGGER.info(f"Generated {len(resource_collection.assignments)} assignments")

        max_stack_resources = generation_config.get_max_number_of_child_stacks(resource_collection.num_resources)

        template_process_inputs[config_file_path] = TemplateProcessInput(
            base_path=base_path,
            base_stem=stem,
            base_template=base_template,
            generation_config=generation_config,
            max_stack_resources=max_stack_resources,
            items=[TemplateProcessInputItem(
                stem=stem,
                resource_collection=resource_collection
            )]
        )
    return template_process_inputs

def process_macro(
        config_file,
        session,
        ids,
        ou_fetcher,
        template_file_suffix,
        output_dir,
        base_generation_config):

    template_process_inputs = {}

    for config_file_fp in config_file:
        LOGGER.info(f"Loading template file {config_file_fp.name}")
        config_file_path = Path(config_file_fp.name)
        if output_dir:
            base_path = Path(output_dir)
        else:
            base_path = config_file_path.parent / "templates"
        stem = config_file_path.stem

        input_template = utils.load_yaml(config_file_fp)
        LOGGER.debug(f"Input template:\n{utils.dump_yaml(input_template)}")

        generation_config = base_generation_config.copy()

        LOGGER.info("Extracting resources from template")
        base_template, max_stack_resources, resource_collection_dict = macro.process_template(input_template,
                session=session,
                ids=ids,
                generation_config=generation_config,
                generation_config_template_priority=False)

        template_process_inputs[config_file_path] = TemplateProcessInput(
            base_path=base_path,
            base_stem=stem,
            base_template=base_template,
            generation_config=generation_config,
            max_stack_resources=max_stack_resources,
            items=[TemplateProcessInputItem(
                stem=resource_name,
                resource_collection=resource_collection
            ) for resource_name, resource_collection in resource_collection_dict.items()]
        )

    return template_process_inputs

def process_templates(
        template_process_inputs,
        template_file_suffix):
    templates_to_write = {}

    for name, template_process_input in template_process_inputs.items():
        LOGGER.info(f"Generating templates for {name}")
        parent_template_to_write = template_process_input.base_template or {}
        all_children = []
        for template_process_input_item in template_process_input.items:
            num_parent_resources = len(parent_template_to_write.get("Resources", {})) + template_process_input.max_stack_resources

            parent_template = templates.resolve_templates(
                template_process_input_item.resource_collection.assignments,
                template_process_input_item.resource_collection.permission_sets,
                generation_config=template_process_input.generation_config,
                num_parent_resources=num_parent_resources,
            )

            template_collection = parent_template.get_templates(
                template_process_input.base_path,
                ".",
                template_process_input_item.stem,
                template_file_suffix,
                base_template=parent_template_to_write,
                parameters=None,
                generation_config=template_process_input.generation_config,
                path_joiner=os.path.join

            )
            parent_template_to_write = template_collection.parent.template
            LOGGER.debug(f"Intermediate parent template\n{utils.dump_yaml(parent_template_to_write)}")

            all_children.extend(template_collection.children)

        templates_to_write[name] = templates.TemplateCollection(
            parent=templates.WritableTemplate(
                path=os.path.join(
                    template_process_input.base_path,
                    f"{template_process_input.base_stem}{template_file_suffix}"),
                template=parent_template_to_write,
            ),
            children=all_children
        )
    return templates_to_write

def write_templates(templates_to_write):
    for name, template_collection_to_write in templates_to_write.items():
        parent_path = template_collection_to_write.parent.path
        parent_data = template_collection_to_write.parent.template

        for child_path, child_data in template_collection_to_write.children:
            LOGGER.info(f"Writing child template at path {child_path}")
            Path(child_path).parent.mkdir(parents=True, exist_ok=True)
            with open(child_path, "w") as fp:
                utils.dump_yaml(child_data, fp)

        LOGGER.info(f"Writing template for {name} at path {parent_path}")
        Path(parent_path).parent.mkdir(parents=True, exist_ok=True)
        with open(parent_path, "w") as fp:
            utils.dump_yaml(parent_data, fp)


if __name__ == "__main__":
    generate_template(prog_name="python -m aws_sso_util.cli.cfn")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
