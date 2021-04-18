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

import os
import logging
import copy
import json
import math
import datetime
from collections import namedtuple

import boto3

from aws_sso_lib import lookup

from .config import Config, validate_resource, GenerationConfig
from . import resources, templates, utils, cfn_yaml_tags

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
TRANSFORM_NAME_20201108 = "AWS-SSO-Util-2020-11-08"
ASSIGNMENT_GROUP_RESOURCE_TYPE = "SSOUtil::SSO::AssignmentGroup"
PERMISSION_SET_RESOURCE_TYPE = "SSOUtil::SSO::PermissionSet"

LOGGER = logging.getLogger(__name__)

def is_macro_template(template):
    if "Transform" not in template:
        return False
    transform = template["Transform"]
    if transform == TRANSFORM_NAME_20201108:
        return True
    if isinstance(transform, list) and TRANSFORM_NAME_20201108 in transform:
        return True
    return False

def process_template(template,
        session,
        ids: lookup.Ids,
        generation_config: GenerationConfig,
        generation_config_template_priority: bool,
        ou_accounts_cache=None):
    base_template = copy.deepcopy(template)

    generation_config.load(base_template.get("Metadata", {}).get("SSO", {}), overwrite=generation_config_template_priority)
    LOGGER.debug(f"generation_config: {generation_config!s}")

    if "Transform" in base_template:
        if base_template["Transform"] == TRANSFORM_NAME_20201108:
            del base_template["Transform"]
        else:
            base_template["Transform"] = [t for t in base_template["Transform"] if t != TRANSFORM_NAME_20201108]

    for resource_name, resource in base_template["Resources"].items():
        if resource["Type"] == PERMISSION_SET_RESOURCE_TYPE:
            resource["Type"] = "AWS::SSO::PermissionSet"

    resource_keys = [k for k, v in base_template["Resources"].items() if v["Type"] == ASSIGNMENT_GROUP_RESOURCE_TYPE]
    resource_dict = {k: base_template["Resources"].pop(k) for k in resource_keys}
    LOGGER.debug(f"Found AssignmentGroup resources: {', '.join(resource_keys)}")

    configs = {}

    for resource_name, resource in resource_dict.items():
        validate_resource(resource)
        config = Config()
        config.load_resource_properties(resource["Properties"])
        config.resource_name_prefix = resource_name

        if not config.instance:
            config.instance = ids.instance_arn

        configs[resource_name] = config

    resource_collection_dict = {}
    max_stack_resources = 0
    ou_fetcher = lambda ou, recursive: lookup.lookup_accounts_for_ou(session, ou,
            recursive=recursive,
            cache=ou_accounts_cache,
            exclude_org_mgmt_acct=True)

    for resource_name, config in configs.items():
        resource_collection = resources.get_resources_from_config(
            config,
            assignment_metadata={"AssignmentGroupResourceName": resource_name},
            ou_fetcher=ou_fetcher)

        max_stack_resources += generation_config.get_max_number_of_child_stacks(resource_collection.num_resources)

        resource_collection_dict[resource_name] = resource_collection

    return base_template, max_stack_resources, resource_collection_dict

HANDLER_INITIALIZED = False

SESSION = None
IDS = None

LOOKUP_NAMES = None
CHILD_TEMPLATES_IN_YAML = None

MAX_RESOURCES_PER_TEMPLATE = None
MAX_CONCURRENT_ASSIGNMENTS = None
MAX_ASSIGNMENTS_ALLOCATION = None
NUM_CHILD_STACKS = None
DEFAULT_SESSION_DURATION = None

BUCKET_NAME = None
KEY_PREFIX = None

S3_PUT_OBJECT_ARGS = None

def handler_init():
    global HANDLER_INITIALIZED, \
        SESSION, \
        IDS, \
        LOOKUP_NAMES, \
        CHILD_TEMPLATES_IN_YAML, \
        MAX_RESOURCES_PER_TEMPLATE, \
        MAX_CONCURRENT_ASSIGNMENTS, \
        MAX_ASSIGNMENTS_ALLOCATION, \
        NUM_CHILD_STACKS, \
        DEFAULT_SESSION_DURATION, \
        BUCKET_NAME, \
        KEY_PREFIX, \
        S3_PUT_OBJECT_ARGS
    if HANDLER_INITIALIZED:
        return

    logging.getLogger("aws_sso_util").setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))
    logging.basicConfig()

    LOGGER.info("Initializing handler")

    SESSION = boto3.Session()
    IDS = lookup.Ids(lambda: SESSION)

    LOOKUP_NAMES = os.environ.get("LOOKUP_NAMES", "false").lower() in ["true", "1"]
    CHILD_TEMPLATES_IN_YAML = os.environ.get("CHILD_TEMPLATES_IN_YAML", "false").lower() in ["true", "1"]

    MAX_RESOURCES_PER_TEMPLATE = int(os.environ["MAX_RESOURCES_PER_TEMPLATE"]) if os.environ.get("MAX_RESOURCES_PER_TEMPLATE") else None
    MAX_CONCURRENT_ASSIGNMENTS = int(os.environ["MAX_CONCURRENT_ASSIGNMENTS"]) if os.environ.get("MAX_CONCURRENT_ASSIGNMENTS") else None
    MAX_ASSIGNMENTS_ALLOCATION = int(os.environ["MAX_ASSIGNMENTS_ALLOCATION"]) if os.environ.get("MAX_ASSIGNMENTS_ALLOCATION") else None
    NUM_CHILD_STACKS = int(os.environ["NUM_CHILD_STACKS"]) if os.environ.get("NUM_CHILD_STACKS") else None
    DEFAULT_SESSION_DURATION = os.environ["DEFAULT_SESSION_DURATION"] if os.environ.get("DEFAULT_SESSION_DURATION") else None

    BUCKET_NAME = os.environ["BUCKET_NAME"]
    KEY_PREFIX = os.environ.get("KEY_PREFIX", "")

    try:
        S3_PUT_OBJECT_ARGS = json.loads(os.environ["S3_PUT_OBJECT_ARGS"]) if os.environ.get("S3_PUT_OBJECT_ARGS") else {}
    except:
        LOGGER.exception("Error parsing S3_PUT_OBJECT_ARGS")

    HANDLER_INITIALIZED = True

def handler(event, context, put_object=None):
    request_id = event["requestId"]
    LOGGER.info(f"Request ID: {request_id}")

    try:
        handler_init()

        input_template = event["fragment"]

        LOGGER.debug(f"Input template:\n{utils.dump_yaml(input_template)}")

        if "Resources" not in input_template:
            raise TypeError(f"{TRANSFORM_NAME_20201108} can only be used as a template-level transform")

        lookup_cache = {}

        if LOOKUP_NAMES:
            principal_name_fetcher = utils.get_principal_name_fetcher(SESSION, IDS, lookup_cache)
            permission_set_name_fetcher = utils.get_permission_set_name_fetcher(SESSION, IDS, lookup_cache)
            target_name_fetcher = utils.get_target_name_fetcher(SESSION, IDS, lookup_cache)
        else:
            principal_name_fetcher = None
            permission_set_name_fetcher = None
            target_name_fetcher = None

        generation_config = GenerationConfig(
            IDS,
            principal_name_fetcher=principal_name_fetcher,
            permission_set_name_fetcher=permission_set_name_fetcher,
            target_name_fetcher=target_name_fetcher
        )
        generation_config.set(
            max_resources_per_template=MAX_RESOURCES_PER_TEMPLATE,
            max_concurrent_assignments=MAX_CONCURRENT_ASSIGNMENTS,
            max_assignments_allocation=MAX_ASSIGNMENTS_ALLOCATION,
            num_child_stacks=NUM_CHILD_STACKS,
            default_session_duration=DEFAULT_SESSION_DURATION,
        )

        ou_accounts_cache = {}

        LOGGER.info("Extracting resources from template")
        output_template, max_stack_resources, resource_collection_dict = process_template(input_template,
                session=SESSION,
                ids=IDS,
                generation_config=generation_config,
                generation_config_template_priority=True,
                ou_accounts_cache=ou_accounts_cache)

        num_assignments = sum(len(rc.assignments) for rc in resource_collection_dict.values())
        LOGGER.info(f"Generated {num_assignments} assignments from {len(resource_collection_dict)} resources")

        all_child_templates_to_write = []

        s3_base_path_parts = [
            "templates",
            f"{datetime.datetime.utcnow().isoformat()[:16]}_{request_id}",
        ]
        if KEY_PREFIX:
            s3_base_path_parts.insert(1, KEY_PREFIX)
        s3_base_path = "/".join(s3_base_path_parts)

        if not resource_collection_dict:
            LOGGER.debug(f"No assignment groups, processing permission sets")
            for resource in output_template["Resources"].values():
                if resource["Type"] != "AWS::SSO::PermissionSet":
                    continue
                templates.process_permission_set_resource(resource, generation_config)
        else:
            for resource_name, resource_collection in resource_collection_dict.items():
                num_parent_resources = len(output_template["Resources"]) + max_stack_resources

                parent_template = templates.resolve_templates(
                    resource_collection.assignments,
                    resource_collection.permission_sets,
                    generation_config=generation_config,
                    num_parent_resources=num_parent_resources,
                )

                suffix = ".yaml" if CHILD_TEMPLATES_IN_YAML else ".json"

                template_collection = parent_template.get_templates(
                    s3_base_path,
                    f"https://s3.amazonaws.com/{BUCKET_NAME}/{s3_base_path}",
                    resource_name,
                    suffix,
                    generation_config=generation_config,
                    base_template=output_template,
                    path_joiner=lambda *args: "/".join(args)

                )
                output_template = template_collection.parent.template
                LOGGER.debug(f"Intermediate output template:\n{utils.dump_yaml(output_template)}")

                all_child_templates_to_write.extend(template_collection.children)

        LOGGER.info(f"Writing {len(all_child_templates_to_write)} child templates")

        bucket = boto3.resource("s3").Bucket(BUCKET_NAME)

        for child_template_key, child_template in all_child_templates_to_write:
            LOGGER.debug(f"Writing child template {child_template_key}")
            if CHILD_TEMPLATES_IN_YAML:
                content = utils.dump_yaml(child_template)
            else:
                child_template = cfn_yaml_tags.to_json(child_template)
                content = json.dumps(child_template, indent=2)

            put_object_args = copy.deepcopy(S3_PUT_OBJECT_ARGS)

            put_object_args.update({
                "Key": child_template_key,
                "Body": content,
            })
            if "ContentType" not in put_object_args:
                content_type = "text/plain" if CHILD_TEMPLATES_IN_YAML else "application/json"
                put_object_args["ContentType"] = content_type

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
    except Exception as e:
        LOGGER.exception(f"An error occurred: {e}")
        output = {
            "requestId" : request_id,
            "status" : "failure",
            "fragment" : {},
            "errorMessage": str(e),
        }

