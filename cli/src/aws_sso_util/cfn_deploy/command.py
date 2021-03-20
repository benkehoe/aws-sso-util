import dataclasses
from pathlib import Path

import click

from .config import ConfigType, Order, get_configs
from .validate import validate

@click.command("build")
@click.argument("mode", type=click.Choice(["validate", "package", "deploy"]), required=True)
@click.argument("path", type=Path)
@click.option("--result_file", type=Path)
@click.option("--local-macro/--no-local-macro")
@click.option("--order", type=click.Choice(["new", "alpha"]), default="new")
@click.option("--validate/--no-validate", default=True)
@click.option("--provision-permission-sets", is_flag=True)
@click.option("--stack-name-prefix", help="Defaults to aws-sso")
@click.option("--base-path", type=Path, default=Path.cwd())
def build(
        mode,
        path,
        result_file,
        local_macro,
        order,
        validate,
        stack_name_prefix,
        base_path):
    order = Order[order]

    if mode == "validate" and not validate:
        raise click.UsageError("Cannot specify --no-validate")
    package = mode in ["package", "deploy"]
    deploy = mode in ["deploy"]

    configs = get_configs(path,
        base_path=base_path,
        order=order,
        stack_name_prefix=stack_name_prefix,
    )

    output = {}

    if validate:
        results = validate(configs)

    if package:
        results = package(configs)

    if deploy:
        results = deploy(configs)
