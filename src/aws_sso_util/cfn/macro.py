import os
import logging
import copy
import json

import boto3

from .config import Config, validate_resource
from . import resources, templates, utils
from .. import api_utils

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
"""
RESOURCE_TYPE = "Custom::SSO::AssignmentGroup"

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))
logging.basicConfig()

MAX_RESOURCES_PER_TEMPLATE = int(os.environ["MAX_RESOURCES_PER_TEMPLATE"]) if "MAX_RESOURCES_PER_TEMPLATE" in os.environ else None
MAX_CONCURRENT_ASSIGNMENTS = int(os.environ["MAX_CONCURRENT_ASSIGNMENTS"]) if "MAX_CONCURRENT_ASSIGNMENTS" in os.environ else None

BUCKET_NAME = os.environ["BUCKET_NAME"]
KEY_PREFIX = os.environ.get("KEY_PREFIX", "")

S3_PUT_OBJECT_ARGS = json.loads(os.environ.get("S3_PUT_OBJECT_ARGS", "{}"))


def handler(event, context, put_object=None):
    request_id = event["requestId"]
    LOGGER.info(f"Request ID: {request_id}")

    bucket = boto3.resource("s3").Bucket(BUCKET_NAME)

    s3_base_path_parts = [
        "templates",
        f"{request_id}",
    ]
    if KEY_PREFIX:
        s3_base_path_parts.insert(1, KEY_PREFIX)
    s3_base_path = "/".join(s3_base_path_parts)

    input_template = event["fragment"]

    if "Resources" not in input_template:
        raise TypeError("AWS-SSO-Util-2020-11-08 can only be used as a template-level transform")

    resource_keys = [k for k, v in input_template["Resources"].items() if v["Type"] == RESOURCE_TYPE]
    resource_dict = {k: input_template["Resources"].pop(k) for k in resource_keys}

    for resource_name, resource in resource_dict.items():
        validate_resource(resource)

    output_template = copy.deepcopy(input_template)

    ou_accounts_cache = {}

    for resource_name, resource in resource_dict.items():
        config = Config(resource_properties=resource["Properties"])

        if not config.instance:
            config.instance = api_utils.get_sso_instance(logger=LOGGER)

        config.resource_name_prefix = resource_name

        assignments, permission_sets = resources.get_resources_from_config(
            config,
            ou_fetcher=lambda ou: api_utils.get_accounts_for_ou(ou, cache=ou_accounts_cache, logger=LOGGER),
            logger=LOGGER)

        num_parent_resources = len(output_template["Resources"])

        parent_template = templates.resolve_templates(
            assignments,
            permission_sets,
            max_resources_per_template=MAX_RESOURCES_PER_TEMPLATE,
            num_parent_resources=num_parent_resources,
        )

        parent_template_to_write, child_templates_to_write = parent_template.get_templates(
            s3_base_path,
            resource_name,
            ".yaml",
            base_template=output_template,
            max_concurrent_assignments=MAX_CONCURRENT_ASSIGNMENTS,
            path_joiner=lambda *args: "/".join(args)

        )
        output_template = parent_template_to_write[1]
        print("output template", utils.dump_yaml(output_template, indent=2))

        for child_template_key, child_template in child_templates_to_write:
            content = utils.dump_yaml(child_template)

            put_object_args = copy.deepcopy(S3_PUT_OBJECT_ARGS)

            put_object_args.update({
                "Key": child_template_key,
                "Body": content,
            })
            if "ContentType" not in put_object_args:
                put_object_args["ContentType"] = "text/plain"

            if put_object:
                put_object(**put_object_args)
            else:
                bucket.put_object(**put_object_args)

    output = {
        "requestId" : request_id,
        "status" : "success",
        "fragment" : output_template,
    }

    return output

