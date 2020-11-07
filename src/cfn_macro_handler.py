import os
import logging
import copy
import json

import boto3
import jsonschema

from aws_sso_util.cfn import resources, templates, utils
from aws_sso_util import api_utils

"""
https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-macros.html
Input:
{
    "region" : "us-east-1",
    "accountId" : "$ACCOUNT_ID",
    "fragment" : { ... },
    "transformId" : "$TRANSFORM_ID",
    "params" : { ... },
    "requestId" : "$REQUEST_ID",
    "templateParameterValues" : { ... }
}

Output:
{
    "requestId" : "$REQUEST_ID",
    "status" : "$STATUS",
    "fragment" : { ... }
}

Type: AWS::SSO::AssignmentGroup
Properties:
    Instance: ...
    Principal:
    - Type: GROUP
      Id:
      - fdafdsa
    PermissionSet:
    Target:
    - Type:
"""

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))

MAX_RESOURCES_PER_TEMPLATE = os.environ.get("MAX_RESOURCES_PER_TEMPLATE")
MAX_CONCURRENT_ASSIGNMENTS = os.environ.get("MAX_CONCURRENT_ASSIGNMENTS")

BUCKET_NAME = os.environ["BUCKET_NAME"]
KEY_PREFIX = os.environ.get("KEY_PREFIX", "")

S3_PUT_OBJECT_ARGS = json.loads(os.environ.get("S3_PUT_OBJECT_ARGS", "{}"))

RESOURCE_TYPE = "AWS::SSO::AssignmentGroup"

def _get_value(dct, keys, ensure_list=False):
    if not isinstance(keys, list):
        keys = [keys]
    for key in keys:
        if key in dct:
            value = dct[key]
            if ensure_list and not isinstance(value, list):
                value = [value]
            return value
    return None

def validate_resource(resource):
    pass

def resource_to_config(resource):
    properties = resource["Properties"]
    config = {}
    instance = _get_value(properties, ["Instance", "InstanceArn"])
    if instance is not None:
        config["Instance"] = instance

    principals = _get_value(properties, ["Principal", "Principals"], ensure_list=True)
    for principal_entry in principals:
        principal_type = _get_value(principal_entry, ["Type", "PrincipalType"])
        principal_ids = _get_value(principal_entry, ["Id", "PrincipalId"], ensure_list=True)
        if principal_type.upper() == "GROUP":
            config_key = "Groups"
        elif principal_type.upper() == "USER":
            config_key = "Users"
        else:
            raise ValueError(f"Invalid principal type: {principal_type}")
        if config_key not in config:
            config[config_key] = []
        config[config_key].append(principal_ids)

    permission_sets = _get_value(properties, ["PermissionSet", "PermissionSetArn", "PermissionSets", "PermissionSetArns"], ensure_list=True)
    config["PermissionSets"] = permission_sets

    targets = _get_value(properties, ["Target", "Targets"], ensure_list=True)
    for target_entry in targets:
        target_type = _get_value(target_entry, ["Type", "TargetType"])
        target_ids = _get_value(target_entry, ["Id", "TargetId"], ensure_list=True)
        if target_type.upper() == "GROUP":
            config_key = "Groups"
        elif target_type.upper() == "USER":
            config_key = "Users"
        else:
            raise ValueError(f"Invalid target type: {target_type}")
        if config_key not in config:
            config[config_key] = []
        config[config_key].append(target_ids)

    return config

def handler(event, context):
    request_id = event["requestId"]
    print(f"Request ID: {request_id}")

    bucket = boto3.resource("s3").Bucket(BUCKET_NAME)

    s3_base_path_parts = [
        "child_templates",
        f"{request_id}"
    ]
    if KEY_PREFIX:
        s3_base_path_parts.insert(1, KEY_PREFIX)
    s3_base_path = "/".join(s3_base_path_parts)

    input_template = event["fragment"]

    resource_keys = [k for k, v in input_template["Resources"] if v["Type"] == RESOURCE_TYPE]
    resources = {k: input_template["Resources"].pop(k) for k in resource_keys}

    for resource_name, resource in resources.items():
        try:
            jsonschema.validate(instance=resource, schema=SCHEMA)
        except jsonschema.ValidationError as e:
            raise

    output_template = copy.deepcopy(input_template)

    ou_accounts_cache = {}

    for resource_name, resource in resources.items():
        config = resource_to_config(resource)

        assignments, permission_sets = resources.get_resources_from_config(
            config,
            ou_fetcher=lambda ou: api_utils.get_accounts_for_ou(ou, cache=ou_accounts_cache, logger=LOGGER),
            logger=LOGGER)

        parent_template = templates.resolve_templates(
            assignments,
            permission_sets,
            max_resources_per_template=MAX_RESOURCES_PER_TEMPLATE,
        )

        templates_to_write = parent_template.get_templates(
            s3_base_path,
            request_id,
            ".yaml",
            base_template=output_template,
            resource_name_prefix=resource_name,
            max_concurrent_assignments=MAX_CONCURRENT_ASSIGNMENTS,
            path_joiner=lambda *args: "/".join(args)
        )

        output_template = templates_to_write[0][0]

        for child_template_key, child_template in templates_to_write[1:]:
            content = utils.dump_yaml(child_template)

            put_object_args = copy.deepcopy(S3_PUT_OBJECT_ARGS)

            put_object_args.update({
                "Key": child_template_key,
                "Body": content,
            })
            if "Content-Type" not in put_object_args:
                put_object_args["Content-Type"] = "text/plain"

            bucket.put_object(**put_object_args)

    output = {
        "requestId" : request_id,
        "status" : "success",
        "fragment" : output_template,
    }

    return output

_INSTANCE_SCHEMA = {
    "oneOf": [
        {"properties": {"Instance": { "type": "string"}}, "required": ["Instance"]},
        {"properties": {"InstanceArn": { "type": "string"}}, "required": ["InstanceArn"]},
    ]
}

SCHEMA = {
    "type": "object",
    "allOf": [
        _INSTANCE_SCHEMA,
    ],
}
