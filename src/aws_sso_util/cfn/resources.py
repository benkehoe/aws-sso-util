import enum
import logging
import hashlib
from collections import OrderedDict, namedtuple

from .config import Config
from . import utils
from . import cfn_yaml_tags

class Principal:
    class Type(enum.Enum):
        GROUP = 'GROUP'
        USER = 'USER'

    def __init__(self, type: 'Principal.Type', name):
        self.type = type
        self.name = name

        self.references = utils.get_references(self.name)

    @property
    def hash_key(self):
        return f"{self.type.value}:{utils.get_hash_key(self.name)}".encode('utf-8')

    def __str__(self):
        return f"{self.type.name}:{self.name}"

    def __repr__(self):
        return f"{self.__class__.__name__}({self.type!r}, {self.name!r})"

class PermissionSet:
    RESOURCE_NAME_PREFIX = "PermSet"

    class _Type(enum.Enum):
        ARN = 'ARN'
        SHORT_ARN = 'SHORT_ARN'
        ID = 'ID'
        REFERENCE = 'REF'
        RESOURCE = 'RESOURCE'

    @classmethod
    def _get_type(cls, value):
        if utils.is_reference(value):
            return cls._Type.REFERENCE
        if isinstance(value, dict):
            return cls._Type.RESOURCE
        if isinstance(value, str) and value.startswith('arn'):
            return cls._Type.ARN
        if isinstance(value, str) and (value.startswith('ssoins-') or value.startswith('ins-')):
            return cls._Type.SHORT_ARN
        if isinstance(value, str) and value.startswith('ps-'):
            return cls._Type.ID
        raise TypeError(f"Unknown permission set type {type(value)} for {value}")

    def __init__(self, value, instance, resource_name_prefix=None):
        self._instance = instance

        self._type = self._get_type(value)
        self._value = value
        self._arn = None

        self._resource_name_prefix = resource_name_prefix

        self.references = utils.get_references(self._value)
        if self._type == self._Type.RESOURCE:
            self.references.add(self.get_resource_name())

    @property
    def hash_key(self):
        return utils.get_hash_key(self.get_arn())

    def get_arn(self, force_ref=False):
        if self._type == self._Type.RESOURCE:
            if force_ref:
                utils.REF_TAG(self.get_resource_name())
            else:
                return utils.GETATT_TAG(f"{self.get_resource_name()}.PermissionSetArn")
        if self._type == self._Type.REFERENCE:
            if force_ref:
                references = utils.get_references(self._value)
                if len(references) != 1:
                    raise ValueError(f"Cannot convert to ref: {self._value}")
                return utils.REF_TAG(list(references)[0])
            return self._value
        if self._type == self._Type.ARN:
            return self._value
        if self._type == self._Type.SHORT_ARN:
            return f"arn:aws:sso:::permissionSet/{self._value}"
        if self._type == self._Type.ID:
            instance_id = utils.get_instance_id_from_arn(self._instance)
            return f"arn:aws:sso:::permissionSet/{instance_id}/{self._value}"
        raise TypeError(f"Invalid PermissionSet type {self._type}")

    def get_resource_name(self):
        prefix = self._resource_name_prefix or ''
        if self._type == self._Type.RESOURCE:
            return f"{prefix}{self.RESOURCE_NAME_PREFIX}{self._get_name()}"
        else:
            return None

    def get_resource(self):
        if self._type != self._Type.RESOURCE:
            return {}

        if "Type" in self._value:
            resource = self._value
        else:
            properties = OrderedDict()
            if "InstanceArn" not in self._value:
                properties["InstanceArn"] = self._instance
            properties.update(self._value)
            resource = OrderedDict({
                "Type": "AWS::SSO::PermissionSet",
                "Properties": properties
            })
        return resource

    def _get_name(self):
        if self._type != self._Type.RESOURCE:
            raise TypeError("PermissionSet._get_name() called when not a resource")
        if "Type" in self._value:
            return self._value["Properties"]["Name"]
        else:
            return self._value["Name"]

    def __str__(self):
        if self._type in [self._Type.ARN, self._Type.SHORT_ARN, self._Type.ID]:
            return self._value
        if self._type == self._Type.REFERENCE:
            return str(self._value)
        if self._type == self._Type.RESOURCE:
            return f"{{{self._get_name()}}}"
        raise TypeError(f"Invalid PermissionSet type {self._type}")

    def __repr__(self):
        return f"{self.__class__.__name__}({self._value!r})"

class Target:
    class Type(enum.Enum):
        OU = 'AWS_OU'
        ACCOUNT = 'AWS_ACCOUNT'

    def __init__(self, type: 'Target.Type', name: str, source_ou=None):
        self.type = type
        self.name = name
        self.source_ou = None

        self.references = utils.get_references(self.name)

    @property
    def hash_key(self):
        return f"{self.type.value}:{utils.get_hash_key(self.name)}".encode('utf-8')

    def __str__(self):
        s = f"{self.type.name}:{self.name}"
        if self.source_ou:
            s += f"[{self.source_ou}]"
        return s

    def __repr__(self):
        if self.source_ou:
            ou_str = f", source_ou={self.source_ou!r}"
        else:
            ou_str = ""
        return f"{self.__class__.__name__}({self.type!r}, {self.name!r}{ou_str})"

class Assignment:
    RESOURCE_NAME_PREFIX = "Assignment"

    def __init__(self, instance, principal, permission_set, target, resource_name_prefix=None):
        self.instance = instance
        self.principal = principal
        self.permission_set = permission_set
        self.target = target

        self._resource_name_prefix = resource_name_prefix

        self.references = utils.get_references(self.instance) | self.principal.references | self.permission_set.references | self.target.references

    def get_resource_name(self):
        prefix = self._resource_name_prefix or ''
        hasher = hashlib.md5()
        hasher.update(utils.get_hash_key(self.instance))
        hasher.update(self.principal.hash_key)
        hasher.update(self.permission_set.hash_key)
        hasher.update(self.target.hash_key)
        hash_value = hasher.hexdigest()[:6].upper()
        return f"{prefix}{self.RESOURCE_NAME_PREFIX}{hash_value}"

    def get_resource(self, child_stack, depends_on=None):
        resource = OrderedDict({
            "Type": "AWS::SSO::Assignment"
        })
        if self.target.source_ou:
            resource["Metadata"] = OrderedDict({
                "AccountSourceOU": self.target.source_ou
            })
        if depends_on:
            resource["DependsOn"] = depends_on
        resource["Properties"] = OrderedDict({
            "InstanceArn": self.instance,
            "PrincipalType": self.principal.type.value,
            "PrincipalId": self.principal.name,
            "PermissionSetArn": self.permission_set.get_arn(force_ref=child_stack),
            "TargetType": self.target.type.value,
            "TargetId": self.target.name
        })

        return resource

    def __str__(self):
        return f"<{self.principal!s}|{self.permission_set!s}|{self.target!s}>"

    def __repr__(self):
        return f"{self.__class__.__name__}({self.instance!r}, {self.principal!r}, {self.permission_set!r}, {self.target!r})"

class ResourceList:
    def __init__(self, resources):
        self._resources = list(resources)
        self.references = set()

        self._init(resources)

    def _init(self, resources):
        for resource in resources:
            self.references.update(resource.references)

    def chunk(self, max_resources):
        return [self.__class__(chunk) for chunk in utils.chunk_list_generator(self._resources, max_resources)]

    def __str__(self):
        return f"[{', '.join(str(v) for v in self._resources)}]"

    def __repr__(self):
        return f"{self.__class__.__name__}({self._resources!r})"

    def __len__(self):
        return len(self._resources)

    def __iter__(self):
        return iter(self._resources)

    def extend(self, resources):
        if isinstance(resources, ResourceList):
            resources = resources._resources
        self._resources.extend(resources)
        self._init(resources)

class AssignmentResources(ResourceList):
    def __init__(self, assignments):
        super().__init__(assignments)

    def num_resources(self):
        return len(self._resources)

class PermissionSetResources(ResourceList):
    def __init__(self, permission_sets):
        super().__init__(permission_sets)

    def num_resources(self):
        return len([r for r in self._resources if r._type == PermissionSet._Type.RESOURCE])

ResourceCollection = namedtuple("ResourceCollection", ["num_resources", "assignments", "permission_sets"])

def get_resources_from_config(config: Config, ou_fetcher=None, logger=None) -> ResourceCollection:
    logger = utils.get_logger(logger, "resources")

    if config.instance is None:
        raise ValueError("SSO instance is not set on config")

    num_resources = 0

    principals = []
    for group in config.groups:
        logger.debug(f"Group: {group!s} {group!r}")
        principals.append(Principal(Principal.Type.GROUP, group))
    for user in config.users:
        principals.append(Principal(Principal.Type.USER, user))
    logger.debug(f"Got principals: [{', '.join(str(v) for v in principals)}]")

    permission_sets = [
        PermissionSet(ps, instance=config.instance, resource_name_prefix=config.resource_name_prefix)
        for ps in config.permission_sets
    ]
    logger.debug(f"Got permission sets: [{', '.join(str(v) for v in permission_sets)}]")

    targets = []

    if (config.ous or config.recursive_ous) and not ou_fetcher:
        logger.error("OU specified but ou_fetcher not provided")
        raise ValueError("OU specified but ou_fetcher not provided")

    for ou in config.ous:
        logger.debug(f"Translating OU {ou} to accounts")
        accounts = ou_fetcher(ou, recursive=False)

        for account in accounts:
            targets.append(Target(Target.Type.ACCOUNT, account, source_ou=ou))

    for ou in config.recursive_ous:
        logger.debug(f"Translating OU {ou} recursively to accounts")
        accounts = ou_fetcher(ou, recursive=True)

        for account in accounts:
            targets.append(Target(Target.Type.ACCOUNT, account, source_ou=ou))

        for account in accounts:
            targets.append(Target(Target.Type.ACCOUNT, account, source_ou=ou))

    for account in config.accounts:
        targets.append(Target(Target.Type.ACCOUNT, account))
    logger.debug(f"Got targets: [{', '.join(str(v) for v in targets)}]")

    assignments = []
    for principal in principals:
        for permission_set in permission_sets:
            for target in targets:
                assignments.append(Assignment(
                    config.instance,
                    principal,
                    permission_set,
                    target,
                    resource_name_prefix=config.resource_name_prefix,
                ))
    logger.debug(f"Got assignments: [{', '.join(str(v) for v in assignments)}]")
    logger.info(f"Generated {len(assignments)} assignments")

    ar = AssignmentResources(assignments)
    psr = PermissionSetResources(permission_sets)
    num_resources = ar.num_resources() + psr.num_resources()

    logger.info(f"{num_resources} total resources")

    return ResourceCollection(num_resources, ar, psr)
