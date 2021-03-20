import dataclasses
import typing
import enum
from pathlib import Path

import yaml

from ..cfn_lib import cfn_yaml_tags
from ..cfn_lib.macro import TRANSFORM_NAME

def clean_stack_name(name):
    #TODO: flesh out
    return str(name).replace("/", "-")

class EnumBase(enum.Enum):
    def _generate_next_value_(name, start, count, last_values):
        return name.lower()

    @classmethod
    def get(cls, name: str):
        name = name.upper().replace("-", "_")
        return getattr(cls, name)


class ConfigType(EnumBase):
    TEMPLATE = enum.auto()
    CONFIG = enum.auto()

class Order(EnumBase):
    NEW = enum.auto()
    ALPHA = enum.auto()

DEFAULT_STACK_NAME_PREFIX = "aws-sso"
DEFAULT_STACK_NAME_SEPARATOR = "-"

@dataclasses.dataclass
class Config:
    path: Path
    type: ConfigType = dataclasses.field(init=False)
    has_macro: bool = dataclasses.field(init=False)
    stack_name: str = dataclasses.field(init=False)
    template_path: Path = dataclasses.field(init=False)

    base_path: dataclasses.InitVar[str]
    stack_name_prefix: dataclasses.InitVar[str] = None
    stack_name_separator: dataclasses.InitVar[str] = None

    def __post_init__(self, base_path: Path, stack_name_prefix: str, stack_name_separator: str):
        with open(self.path) as fp:
            data = yaml.load(fp)
            if "Resources" in data:
                self.type = ConfigType.TEMPLATE
                transform = data.get("Transform")
                try:
                    self.has_macro = (transform == TRANSFORM_NAME or TRANSFORM_NAME in transform)
                except:
                    self.has_macro = False
            else:
                self.type = ConfigType.CONFIG
                self.has_macro = None

            if stack_name_prefix is None:
                stack_prefix = DEFAULT_STACK_NAME_PREFIX
            if stack_name_separator is None:
                stack_name_separator = DEFAULT_STACK_NAME_SEPARATOR

            def proc(name):
                if not stack_name_prefix:
                    return name
                else:
                    return stack_name_separator.join([stack_name_prefix, name])

            if data.get("StackName"):
                self.stack_name = proc(data["StackName"])
            elif data.get("Metadata", {}).get("StackName"):
                self.stack_name = proc(data["Metadata"]["StackName"])
            else:
                self.stack_name = proc(self.get_stack_name(base_path, self.path, stack_name_separator))

            self.template_path = None

    @classmethod
    def get_stack_name(cls, base_path: Path, path: Path, stack_name_separator: str):
        path = path.relative_to(base_path)
        components = path.parent.parts
        components.append(path.stem)
        return stack_name_separator.join(components)

def get_configs(path: Path, base_path: Path, order: Order, stack_name_prefix: str=None, stack_name_separator: str: None) -> typing.List[Config]:
    kwargs = {
        "base_path": base_path,
        "stack_name_prefix": stack_name_prefix,
        "stack_name_separator": stack_name_separator,
    }

    if path.is_file():
        configs = [Config(path, **kwargs)]
    else:
        configs = []
        root_path = path
        #TODO: ignorelib
        for cur_dir, subdirs, files in os.walk(root_path):
            cur_dir = Path(cur_dir).relative_to(root_path)
            for f in files:
                f_path = cur_dir / f
                if f_path.suffix == ".yaml":
                    configs.append(Config(f_path, **kwargs))

    if order == Order.NEW:
        configs.sort(key=lambda p: p.stat().st_mtime)
    elif order == Order.ALPHA:
        configs.sort(key=lambda p: str(p))
    else:
        raise RuntimeError(f"Invalid order param {order}")

    return configs
