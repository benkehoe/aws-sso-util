import os
import subprocess
from pathlib import Path
import tempfile
import json
import csv
import dataclasses
import sys

import yaml

import click

def clean_stack_name(name):
    #TODO: flesh out
    return str(name).replace("/", "-")

@dataclasses.dataclass
class Config:
    path: Path
    stack_name: str
    template_path: Path = None

@click.command("cfn")
@click.argument("path")
@click.argument("result_file")
@click.option("--mode", type=click.Choice(["package", "deploy"]), required=True)
@click.option("--config-type", "-c", type=click.Choice(["macro", "local-macro", "local-config"]), default="macro")
@click.option("--order", type=click.Choice(["new", "alpha"]), default="new")
@click.option("--cfn-lint/--no-cfn-lint", default=None)
@click.option("--validate-schema/--no-validate-schema", default=None)
def deploy(
        path,
        result_file,
        mode,
        config_type,
        order,
        cfn_lint,
        validate_schema,
        local_build):
    if config_type == "local-config":
        if cfn_lint:
            raise click.UsageError("Cannot use --cfn-lint with --config-type local-config")
        if validate_schema:
            raise click.UsageError("Cannot use --validate-schema with --config-type local-config")
    else:
        if cfn_lint is None:
            cfn_lint = True
        if validate_schema is None:
            validate_schema = True

    # Gather
    path = Path(path)

    if path.is_file():
        stack_name = clean_stack_name(path.stem)
        configs = [Config(path, stack_name)]
    else:
        input_paths = []
        for root, dirs, files in os.walk(path):
            root = Path(root).relative_to(path)
            for f in files:
                f_path = root / f
                if f_path.suffix == ".yaml":
                    stack_name = clean_stack_name(root / f_path.stem)
                    input_paths.append(Config(f_path, stack_name))

    if order == "new":
        input_paths.sort(key=lambda p: p.stat().st_mtime)
    elif order == "alpha":
        input_paths.sort(key=lambda p: str(p))
    else:
        raise RuntimeError(f"Invalid order param {order}")

    if cfn_lint:
        results = run_cfn_lint(configs)
        if any(r.returncode for r in results):
            print(f"cfn-lint errors in {', '.join(c.path for c, r in zip(configs, results) if r.returncode != 0)}", file=sys.stderr)
            sys.exit(1)

    if validate_schema:
        results = run_validate_schema(configs)
        raise NotImplementedError

    if config_type == "macro":
        for c in configs:
            c.template_path = c.path
    else:
        build_local(configs, config_type)

    # Build/deploy
    raise NotImplementedError

def run_cfn_lint(configs):
    with tempfile.NamedTemporaryFile(mode="w") as rules_file:
        json.dump(RULES, rules_file)
        rules_file.flush()

        args = ["cfn-lint"]
        args.extend(["--override-spec", rules_file.name])
        # args.extend(["--format", "json"])

        results = []
        for config in configs:
            result = subprocess.run(args + [str(config.path)], capture_output=False)

            results.append(result)

        return results

def run_validate_schema(configs):
    raise NotImplementedError

def build_local(configs, config_type):
    raise NotImplementedError

def package(configs):
    raise NotImplementedError

def deploy(configs):
    raise NotImplementedError

def get_permission_sets(configs):
    raise NotImplementedError

def get_assignments(path):
    with tempfile.NamedTemporaryFile(mode="r") as assignments_file:
        args = ["aws-sso-util", "admin", "cfn"]
        args.append("--macro")
        args.extend(["--assignments-csv", assignments_file.name])
        args.append("--assignments-csv-only")
        args.append(str(path))

        result = subprocess.run(args, capture_output=True)

        result.check_returncode()

        permission_sets = set()

        assignments_data = csv.reader(assignments_file)
        permission_set_index = None
        for row in assignments_data:
            if permission_set_index is None:
                permission_set_index = row.index("permission_set_arn")
            else:
                permission_sets.add(row[permission_set_index])

        print(list(permission_sets))

RULES = {
    "ResourceTypes": {
        "AWS::SSO::PermissionSet": {
            "Properties": {
                "InstanceArn": {
                    "Required": False
                },
                "InlinePolicy": {
                    "PrimitiveType": "Json"
                }
            }
        },
        "SSOUtil::SSO::AssignmentGroup": {
            "Properties": {
                "InstanceArn": {
                    "PrimitiveType": "String",
                    "Required": True,
                    "UpdateType": "Immutable"
                },
                "Name": {
                    "PrimitiveType": "String",
                    "Required": False,
                    "UpdateType": "Immutable"
                },
                "Principal": {
                    "Required": True,
                    "UpdateType": "Mutable"
                },
                "PermissionSet": {
                    "Required": True,
                    "UpdateType": "Mutable"
                },
                "Target": {
                    "Required": True,
                    "UpdateType": "Mutable"
                }
            }
        }
    }
}


if __name__ == "__main__":
    deploy(prog_name="python -m aws_sso_util.cfn_deploy")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter

