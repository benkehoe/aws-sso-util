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

import jsonschema
import logging
import math

from aws_sso_lib import lookup
from aws_sso_lib.format import format_account_id

from . import utils, cfn_yaml_tags

LOGGER = logging.getLogger(__name__)

class ConfigError(Exception):
    pass

def _get_value(dct, keys, ensure_list=False, type=None):
    if not isinstance(keys, list):
        keys = [keys]
    found_key = None
    found_value = [] if ensure_list else None
    for key in keys:
        if key in dct:
            value = dct[key]
            if value is None:
                continue
            if ensure_list and not isinstance(value, list):
                value = [value]
            found_key = key
            found_value = value
            break
    if type is not None:
        if ensure_list:
            found_value = [type(v) for v in found_value]
        elif found_value is not None:
            found_value = type(found_value)
    return found_key, found_value

class GenerationConfig:
    DEFAULT_MAX_RESOURCES_PER_TEMPLATE = 500
    DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 20
    DEFAULT_NUM_CHILD_STACKS = None

    def __init__(self,
            ids: lookup.Ids,
            principal_name_fetcher=None,
            permission_set_name_fetcher=None,
            target_name_fetcher=None):
        self.ids = ids
        self._max_resources_per_template = None
        self._max_concurrent_assignments = None
        self._max_assignments_allocation = None
        self._num_child_stacks = None

        self._default_session_duration = None

        self.principal_name_fetcher = principal_name_fetcher
        self.permission_set_name_fetcher = permission_set_name_fetcher
        self.target_name_fetcher = target_name_fetcher

    def __str__(self):
        return str({
            "max_resources_per_template": self.max_resources_per_template,
            "max_concurrent_assignments": self.max_concurrent_assignments,
            "num_child_stacks": self.num_child_stacks,
            "default_session_duration": self.default_session_duration,
            "internal": {
                "max_resources_per_template": self._max_resources_per_template,
                "max_concurrent_assignments": self._max_concurrent_assignments,
                "max_assignments_allocation": self._max_assignments_allocation,
                "num_child_stacks": self._num_child_stacks,
                "default_session_duration": self._default_session_duration,
            },
        })

    def copy(self):
        obj = self.__class__(
            self.ids,
            principal_name_fetcher=self.principal_name_fetcher,
            permission_set_name_fetcher=self.permission_set_name_fetcher,
            target_name_fetcher=self.target_name_fetcher
        )
        obj.set(
            max_resources_per_template=self._max_resources_per_template,
            max_concurrent_assignments=self._max_concurrent_assignments,
            max_assignments_allocation=self._max_assignments_allocation,
            num_child_stacks=self._num_child_stacks,
            default_session_duration=self._default_session_duration,
        )
        return obj

    @property
    def max_resources_per_template(self):
        if self._max_resources_per_template is None or self._max_resources_per_template < 1:
            return self.DEFAULT_MAX_RESOURCES_PER_TEMPLATE
        else:
            return self._max_resources_per_template

    @property
    def max_concurrent_assignments(self):
        if self._max_concurrent_assignments is None or self._max_concurrent_assignments < 1:
            return self.DEFAULT_MAX_CONCURRENT_ASSIGNMENTS
        else:
            return self._max_concurrent_assignments

    @property
    def num_child_stacks(self):
        num_stacks_1 = None
        if self._max_assignments_allocation is not None and self._max_assignments_allocation >= 1:
            num_stacks_1 = math.ceil(self._max_assignments_allocation / self.max_resources_per_template)

        num_stacks_2 = None
        if self._num_child_stacks is not None and self._num_child_stacks >= 0:
            num_stacks_2 = self._num_child_stacks

        if num_stacks_1 is not None and num_stacks_2 is not None:
            return max(num_stacks_1, num_stacks_2)
        elif num_stacks_1 is not None:
            return num_stacks_1
        elif num_stacks_2 is not None:
            return num_stacks_2
        else:
            return self.DEFAULT_NUM_CHILD_STACKS

    def get_max_number_of_child_stacks(self, num_resources):
        num_child_stacks = self.num_child_stacks
        if num_child_stacks is not None:
            return num_child_stacks
        return math.ceil(num_resources / self.max_resources_per_template)

    @property
    def default_session_duration(self):
        if not self._default_session_duration:
            return None
        else:
            return self._default_session_duration

    def set(self,
            max_resources_per_template=None,
            max_concurrent_assignments=None,
            max_assignments_allocation=None,
            num_child_stacks=None,
            default_session_duration=None,
            overwrite=False):

        if self._max_resources_per_template is None or (max_resources_per_template is not None and overwrite):
            self._max_resources_per_template = max_resources_per_template

        if self._max_concurrent_assignments is None or (max_concurrent_assignments is not None and overwrite):
            self._max_concurrent_assignments = max_concurrent_assignments

        if self._max_assignments_allocation is None or (max_assignments_allocation is not None and overwrite):
            self._max_assignments_allocation = max_assignments_allocation

        if self._num_child_stacks is None or (num_child_stacks is not None and overwrite):
            self._num_child_stacks = num_child_stacks

        if default_session_duration and (self._default_session_duration is None or overwrite):
            self._default_session_duration = default_session_duration

    def load(self, data, overwrite=False):
        max_resources_per_template = _get_value(data, ["MaxResourcesPerTemplate"], type=int)[1]
        max_concurrent_assignments = _get_value(data, ["MaxConcurrentAssignments"], type=int)[1]
        max_assignments_allocation = _get_value(data, ["MaxAssignmentsAllocation"], type=int)[1]
        num_child_stacks = _get_value(data, ["NumChildStacks", "NumChildTemplates"], type=int)[1]
        default_session_duration = _get_value(data, ["DefaultSessionDuration"])[1]

        self.set(
            max_resources_per_template=max_resources_per_template,
            max_concurrent_assignments=max_concurrent_assignments,
            max_assignments_allocation=max_assignments_allocation,
            num_child_stacks=num_child_stacks,
            default_session_duration=default_session_duration,
            overwrite=overwrite
        )

class Config:
    def __init__(self, data=None, resource_properties=None, resource_name_prefix=None):
        self.instance = None

        self.groups = []
        self.users = []

        self.permission_sets = []

        self.ous = []
        self.recursive_ous = []
        self.accounts = []

        self.assignment_group_name = None

        self.resource_name_prefix = resource_name_prefix

        if data:
            self.load(data)
        if resource_properties:
            self.load_resource_properties(resource_properties)

    def load(self, data):
        self.assignment_group_name = _get_value(data, ["AssignmentGroupName"])[1]

        self.instance = _get_value(data, ["Instance", "InstanceArn", "InstanceARN"])[1]

        def get(names):
            return _get_value(data, names, ensure_list=True)[1]

        self.groups.extend(get(["Groups", "Group"]))
        self.users.extend(get(["Users", "User"]))

        self.permission_sets.extend(get(["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"]))

        self.ous.extend(get(["OUs", "Ous", "OU", "Ou"]))
        self.recursive_ous.extend(get(["RecursiveOUs", "RecursiveOus", "RecursiveOU", "RecursiveOu"]))
        for account in get(["Accounts", "Account"]):
            self.accounts.append(format_account_id(account))

    def load_resource_properties(self, resource_properties):
        data = {}

        name = _get_value(resource_properties, ["Name"])[1]
        if name is not None and isinstance(name, str):
            data["AssignmentGroupName"] = resource_properties["Name"]

        instance = _get_value(resource_properties, ["Instance", "InstanceArn", "InstanceARN"])[1]
        if instance is not None:
            data["Instance"] = instance

        principals = _get_value(resource_properties, ["Principal", "Principals"], ensure_list=True)[1]
        for principal_entry in principals:
            principal_type = _get_value(principal_entry, ["Type", "PrincipalType"])[1]
            principal_ids = _get_value(principal_entry, ["Id", "PrincipalId", "Ids", "PrincipalIds"], ensure_list=True)[1]
            if principal_type.upper() == "GROUP":
                config_key = "Groups"
            elif principal_type.upper() == "USER":
                config_key = "Users"
            else:
                raise ValueError(f"Invalid principal type: {principal_type}")
            if config_key not in data:
                data[config_key] = []
            data[config_key].extend(principal_ids)

        permission_sets = _get_value(resource_properties, ["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"], ensure_list=True)[1]
        data["PermissionSets"] = permission_sets

        targets = _get_value(resource_properties, ["Target", "Targets"], ensure_list=True)[1]
        for target_entry in targets:
            target_type = _get_value(target_entry, ["Type", "TargetType"])[1]
            target_ids = _get_value(target_entry, ["Id", "TargetId", "Ids", "TargetIds"], ensure_list=True)[1]
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

        self.load(data)

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

def validate_config(config, ids: lookup.Ids):
    if not config.instance:
        config.instance = ids.instance_arn
    elif not ids.instance_arn_matches(config.instance):
        LOGGER.warning(f"Config instance {config.instance} does not match {ids.instance_arn}")

    if not (config.groups or config.users):
       raise ConfigError("No principals specified")
    if not config.permission_sets:
        raise ConfigError("No permission sets specified")
    if not (config.ous or config.accounts):
        raise ConfigError("No targets specified")
