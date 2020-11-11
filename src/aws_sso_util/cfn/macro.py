import os
import logging
import copy
import json
import math

import boto3

from .config import Config, validate_resource
from . import resources, templates, utils, cfn_yaml_tags
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
TRANSFORM_NAME = "AWS-SSO-Util-2020-11-08"
RESOURCE_TYPE = "SSOUtil::SSO::AssignmentGroup"

LOGGER = logging.getLogger(__name__)

def is_macro_template(template):
    if "Transform" not in template:
        return False
    transform = template["Transform"]
    if transform == TRANSFORM_NAME:
        return True
    if isinstance(transform, list) and TRANSFORM_NAME in transform:
        return True
    return False

def process_template(template, instance_fetcher,
        ou_accounts_cache=None,
        max_resources_per_template=None,
        logger=None):
    logger = utils.get_logger(logger, "macro")

    base_template = copy.deepcopy(template)

    if "Transform" in base_template:
        if base_template["Transform"] == TRANSFORM_NAME:
            del base_template["Transform"]
        else:
            base_template["Transform"] = [t for t in base_template["Transform"] if t != TRANSFORM_NAME]

    resource_keys = [k for k, v in base_template["Resources"].items() if v["Type"] == RESOURCE_TYPE]
    resource_dict = {k: base_template["Resources"].pop(k) for k in resource_keys}
    logger.debug(f"Found AssignmentGroup resources: {', '.join(resource_keys)}")

    configs = {}

    for resource_name, resource in resource_dict.items():
        validate_resource(resource)
        config = Config()
        config.load_resource_properties(resource["Properties"], logger=LOGGER)
        config.resource_name_prefix = resource_name

        if not config.instance:
            config.instance = instance_fetcher(logger=LOGGER)

        configs[resource_name] = config

    resource_collection_dict = {}
    max_stack_resources = 0
    for resource_name, config in configs.items():
        resource_collection = resources.get_resources_from_config(
            config,
            ou_fetcher=lambda ou, recursive: api_utils.get_accounts_for_ou(ou, recursive, cache=ou_accounts_cache, logger=LOGGER),
            logger=LOGGER)

        max_stack_resources += templates.get_max_number_of_child_stacks(resource_collection.num_resources, max_resources_per_template=max_resources_per_template)

        resource_collection_dict[resource_name] = resource_collection

    return base_template, max_stack_resources, resource_collection_dict


def handler(event, context, put_object=None):
    LOGGER.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))
    logging.basicConfig()

    MAX_RESOURCES_PER_TEMPLATE = int(os.environ["MAX_RESOURCES_PER_TEMPLATE"]) if os.environ.get("MAX_RESOURCES_PER_TEMPLATE") else None
    MAX_CONCURRENT_ASSIGNMENTS = int(os.environ["MAX_CONCURRENT_ASSIGNMENTS"]) if os.environ.get("MAX_CONCURRENT_ASSIGNMENTS") else None

    BUCKET_NAME = os.environ["BUCKET_NAME"]
    KEY_PREFIX = os.environ.get("KEY_PREFIX", "")

    try:
        S3_PUT_OBJECT_ARGS = json.loads(os.environ["S3_PUT_OBJECT_ARGS"]) if os.environ.get("S3_PUT_OBJECT_ARGS") else {}
    except:
        LOGGER.exception("Error parsing S3_PUT_OBJECT_ARGS")

    request_id = event["requestId"]
    LOGGER.info(f"Request ID: {request_id}")

    input_template = event["fragment"]

    LOGGER.debug(f"Input template:\n{utils.dump_yaml(input_template)}")

    if "Resources" not in input_template:
        raise TypeError(f"{TRANSFORM_NAME} can only be used as a template-level transform")

    ou_accounts_cache = {}

    LOGGER.info("Extracting resources from template")
    output_template, max_stack_resources, resource_collection_dict = process_template(input_template,
            instance_fetcher=api_utils.get_sso_instance,
            ou_accounts_cache=ou_accounts_cache,
            max_resources_per_template=MAX_RESOURCES_PER_TEMPLATE,
            logger=LOGGER)

    all_child_templates_to_write = []

    s3_base_path_parts = [
        "templates",
        f"{request_id}",
    ]
    if KEY_PREFIX:
        s3_base_path_parts.insert(1, KEY_PREFIX)
    s3_base_path = "/".join(s3_base_path_parts)

    LOGGER.info(f"Processing {len(resource_collection_dict)} resources")
    for resource_name, resource_collection in resource_collection_dict.items():
        num_parent_resources = len(output_template["Resources"]) + max_stack_resources

        parent_template = templates.resolve_templates(
            resource_collection.assignments,
            resource_collection.permission_sets,
            max_resources_per_template=MAX_RESOURCES_PER_TEMPLATE,
            num_parent_resources=num_parent_resources,
        )

        parent_template_to_write, child_templates_to_write = parent_template.get_templates(
            s3_base_path,
            f"https://s3.amazonaws.com/{BUCKET_NAME}/{s3_base_path}",
            resource_name,
            ".yaml",
            base_template=output_template,
            max_concurrent_assignments=MAX_CONCURRENT_ASSIGNMENTS,
            path_joiner=lambda *args: "/".join(args)

        )
        output_template = parent_template_to_write.template
        LOGGER.debug(f"Intermediate output template:\n{utils.dump_yaml(output_template)}")

        all_child_templates_to_write.extend(child_templates_to_write)

    LOGGER.info(f"Writing {len(all_child_templates_to_write)} child templates")

    bucket = boto3.resource("s3").Bucket(BUCKET_NAME)

    for child_template_key, child_template in all_child_templates_to_write:
        LOGGER.debug(f"Writing child template {child_template_key}")
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

    output_template = cfn_yaml_tags.to_json(output_template)

    LOGGER.debug(f"Final output template:\n{utils.dump_yaml(output_template)}")

    output = {
        "requestId" : request_id,
        "status" : "success",
        "fragment" : output_template,
    }

    return output

