import typing
import subprocess
import logging
import pkg_resources
import json
import tempfile
import io
import dataclasses

from .config import Config, ConfigType

CFN_LINT_SPEC = json.load(pkg_resources.resource_stream(__name__, "cfn-lint-spec.json"))

LOGGER = logging.getLogger(__name__)

@dataclasses.dataclass
class ConfigValidationResult:
    pass

@dataclasses.dataclass
class ValidationResults:
    pass

def validate(configs: typing.List[Config]) -> ValidationResults:
    if any(c.type == ConfigType.TEMPLATE for c in configs):
        result = subprocess.run(["cfn-lint", "--version"])
        if result.returncode != 0:
            return ["cfn-lint is missing"]

    if any(c.has_macro for c in configs):
        cfn_lint_spec_file = tempfile.NamedTemporaryFile(mode="w")
    else:
        cfn_lint_spec_file = io.StringIO()
        cfn_lint_spec_file.name = None

    with cfn_lint_spec_file:
        json.dump(CFN_LINT_SPEC, cfn_lint_spec_file)
        cfn_lint_spec_file.flush()

        results = []

        for config in configs:
            if c.type == ConfigType.TEMPLATE:
                result = validate_template(config, spec_file_name)
            else:
                result = validate_config(config)
            results.append(result)

    raise NotImplementedError

def validate_template(config: Config, spec_file_name) -> ConfigValidationResult:
    cfn_lint_args = ["cfn-lint", "--format", "json"]
    if config.has_macro:
        cfn_lint_args.extend(["--override-spec", spec_file_name])
    cfn_lint_args.append(config.path)

    result = subprocess.run(cfn_lint_args, capture, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    cfn_lint_results = json.loads(result.stdout)

def validate_config(config: Config) -> ConfigValidationResult:
    raise NotImplementedError
