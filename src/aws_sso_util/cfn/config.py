import numbers
import jsonschema

from . import utils, cfn_yaml_tags

class ConfigError(Exception):
    pass

def _get_value(dct, keys, ensure_list=False):
    if not isinstance(keys, list):
        keys = [keys]
    for key in keys:
        if key in dct:
            value = dct[key]
            if ensure_list and not isinstance(value, list):
                value = [value]
            return key, value
    if ensure_list:
        return None, []
    else:
        return None, None

class Config:
    def __init__(self, data=None, resource_properties=None, resource_name_prefix=None):
        self.instance = None

        self.groups = []
        self.users = []

        self.permission_sets = []

        self.ous = []
        self.recursive_ous = []
        self.accounts = []

        self.resource_name_prefix = resource_name_prefix

        if data:
            self.load(data)
        if resource_properties:
            self.load_resource_properties(resource_properties)

    def load(self, data, logger=None):
        logger = utils.get_logger(logger, "config")

        for name in ["Instance", "InstanceArn", "InstanceARN"]:
            if name in data:
                self.instance = data[name]
                break

        def get(names):
            for name in names:
                if name in data:
                    value = data[name]
                    if not isinstance(value, list):
                        value = [value]
                    return value
            return []

        self.groups.extend(get(["Groups", "Group"]))
        self.users.extend(get(["Users", "User"]))

        self.permission_sets.extend(get(["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"]))

        self.ous.extend(get(["OUs", "Ous", "OU", "Ou"]))
        self.recursive_ous.extend(get(["RecursiveOUs", "RecursiveOus", "RecursiveOU", "RecursiveOu"]))
        for account in get(["Accounts", "Account"]):
            if isinstance(account, (str, numbers.Number)):
                account = str(int(account)).rjust(12, '0')
            self.accounts.append(account)


    def load_resource_properties(self, resource_properties, logger=None):
        logger = utils.get_logger(logger, "config")

        data = {}
        _, instance = _get_value(resource_properties, ["Instance", "InstanceArn", "InstanceARN"])
        if instance is not None:
            data["Instance"] = instance

        _, principals = _get_value(resource_properties, ["Principal", "Principals"], ensure_list=True)
        for principal_entry in principals:
            _, principal_type = _get_value(principal_entry, ["Type", "PrincipalType"])
            _, principal_ids = _get_value(principal_entry, ["Id", "PrincipalId", "Ids", "PrincipalIds"], ensure_list=True)
            if principal_type.upper() == "GROUP":
                config_key = "Groups"
            elif principal_type.upper() == "USER":
                config_key = "Users"
            else:
                raise ValueError(f"Invalid principal type: {principal_type}")
            if config_key not in data:
                data[config_key] = []
            data[config_key].extend(principal_ids)

        _, permission_sets = _get_value(resource_properties, ["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"], ensure_list=True)
        data["PermissionSets"] = permission_sets

        _, targets = _get_value(resource_properties, ["Target", "Targets"], ensure_list=True)
        for target_entry in targets:
            _, target_type = _get_value(target_entry, ["Type", "TargetType"])
            _, target_ids = _get_value(target_entry, ["Id", "TargetId", "Ids", "TargetIds"], ensure_list=True)
            if target_type.upper() == "AWS_OU":
                if target_entry.get("Recursive", False):
                    config_key = "RecursiveOus"
                else:
                    config_key = "Ous"
            elif target_type.upper() == "AWS_ACCOUNT":
                config_key = "Accounts"
            else:
                raise ValueError(f"Invalid target type: {target_type}")
            if config_key not in data:
                data[config_key] = []
            data[config_key].extend(target_ids)

        import yaml

        self.load(data, logger=logger)

FUNC_SCHEMA = {
    "type": "object",
    "patternProperties": {
        "Ref|Fn::.*": {},
    },
    "minProperties": 1,
    "maxProperties": 1,
}

def _opt_func(schema):
    return {
        "oneOf": [
            schema,
            FUNC_SCHEMA,
        ]
    }

def _opt_list(schema, func=False):
    if func:
        return {
            "oneOf": [
                schema,
                {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            schema,
                            FUNC_SCHEMA,
                        ]
                    }
                },
                FUNC_SCHEMA,
            ]
        }
    else:
        return {
            "oneOf": [
                schema,
                {
                    "type": "array",
                    "items": schema,
                },
            ]
        }

PRINCIPAL_SCHEMA = {
    "type": "object",
    "patternProperties": {
        "(Principal)?Type": _opt_func({
            "type": "string",
            "enum": ["GROUP", "USER"],
        }),
        "(Principal)?Id(s)?": _opt_list({"type": "string"}, func=True),
    }
}

PERMISSION_SET_SCHEMA = _opt_func({
    "type": "string",
})

TARGET_SCHEMA = {
    "type": "object",
    "patternProperties": {
        "(Target)?Type": _opt_func({
            "type": "string",
            "enum": ["AWS_OU", "AWS_ACCOUNT"],
        }),
        "(Target)?Id(s)?": _opt_list({"type": ["string", "integer"]}, func=True),
        "Recursive": {"type": "boolean"},
    }
}

RESOURCE_PROPERTY_SCHEMA = {
    "type": "object",
    "patternProperties": {
        "Name": _opt_func({"type": "string"}),
        "Instance(Arn|ARN)?": _opt_func({"type": "string"}),
        "Principal(s)?": _opt_list(PRINCIPAL_SCHEMA),
        "PermissionSet(Arn)?(s)?": _opt_list(PERMISSION_SET_SCHEMA),
        "Target(s)?": _opt_list(TARGET_SCHEMA),
        "UpdateNonce": _opt_func({"type": "string"}),
    },
    "additionalProperties": False,
}

def _check(properties, keys, required=True, parent="Resource"):
    found_keys = [k for k in keys if k in properties]
    if len(found_keys) > 1:
        raise ConfigError(f"{parent} must have only one of {', '.join(found_keys)}")
    if required and len(found_keys) == 0:
        raise ConfigError(f"{parent} must have one of {', '.join(keys)}")

def validate_resource(resource):
    resource = cfn_yaml_tags.to_json(resource)
    properties = resource.get("Properties", {})
    try:
        jsonschema.validate(
            schema=RESOURCE_PROPERTY_SCHEMA,
            instance=properties)
    except jsonschema.ValidationError as e:
        raise ConfigError(f"Resource is invalid: {e!s}")

    _check(properties, ["Instance", "InstanceArn", "InstanceARN"], required=False)

    _check(properties, ["Principal", "Principals"])

    name, principals = _get_value(properties, ["Principal", "Principals"], ensure_list=True)
    for principal_entry in principals:
        _check(principal_entry, ["Type", "PrincipalType"], parent=name)
        _check(principal_entry, ["Id", "PrincipalId", "Ids", "PrincipalIds"], parent=name)

    _check(properties, ["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"])

    name, targets = _get_value(properties, ["Target", "Targets"], ensure_list=True)
    for target_entry in targets:
        _check(target_entry, ["Type", "TargetType"], parent=name)
        _check(target_entry, ["Id", "TargetId", "Ids", "TargetIds"], parent=name)

def validate_config(config, sso_instance, instance_fetcher, logger=None):
    logger = utils.get_logger(logger, "config")
    if config.instance and sso_instance and config.instance != sso_instance:
        logger.warning(f"Config instance {config.instance} does not match input instance {sso_instance}")
    if not config.instance:
        config.instance = instance_fetcher(logger=logger)

    if not (config.groups or config.users):
       raise ConfigError("No principals specified")
    if not config.permission_sets:
        raise ConfigError("No permission sets specified")
    if not (config.ous or config.accounts):
        raise ConfigError("No targets specified")
