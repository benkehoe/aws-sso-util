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
import re
import math
from collections import OrderedDict, namedtuple
from pathlib import PurePath
import logging
import json
import numbers

from . import cfn_yaml_tags
from . import resources
from . import utils
from .config import GenerationConfig

LOGGER = logging.getLogger(__name__)

WritableTemplate = namedtuple("WritableTemplate", ["path", "template"])
TemplateCollection = namedtuple("TemplateCollection", [
    "parent",
    "children",
])
_ChildData = namedtuple("_ChildData", ["path_for_writing", "path_for_resource", "stem", "template"])

def is_name_in_template(name, template):
    for section in ["Parameters", "Conditions", "Resources"]:
        if name in template.get(section, {}):
            return True
    return False

def add_parameters_to_template(template,
        base_template: dict=None,
        template_parameters: dict=None,
        references: set=None):
    if "Parameters" not in template:
        template["Parameters"] = OrderedDict()

    if base_template and "Parameters" in base_template:
        template["Parameters"].update(base_template["Parameters"])

    if template_parameters:
        for parameter_name, default in template_parameters:
            if parameter_name not in template["Parameters"]:
                template["Parameters"][parameter_name] = OrderedDict({"Type": "String"})
            if default is not None:
                template["Parameters"][parameter_name]["Default"] = default

    if references:
        for reference_name in sorted(references):
            if not is_name_in_template(reference_name, template):
                template["Parameters"][reference_name] = OrderedDict({"Type": "String"})

    if not template["Parameters"]:
        del template["Parameters"]

def add_assignments_to_template(
        template,
        assignments: resources.AssignmentResources,
        child_stack,
        generation_config: GenerationConfig):
    max_concurrent_assignments = generation_config.max_concurrent_assignments

    assignment_resources = []
    for assignment in assignments:
        if max_concurrent_assignments and len(assignment_resources) >= max_concurrent_assignments:
            depends_on = assignment_resources[len(assignment_resources)-max_concurrent_assignments][0]
        else:
            depends_on = None

        assignment_resources.append((
            assignment.get_resource_name(),
            assignment.get_resource(
                child_stack=child_stack,
                depends_on=depends_on,
                principal_name_fetcher=generation_config.principal_name_fetcher,
                permission_set_name_fetcher=generation_config.permission_set_name_fetcher,
                target_name_fetcher=generation_config.target_name_fetcher
                )))

    if "Resources" not in template:
        template["Resources"] = OrderedDict()

    template["Resources"].update(assignment_resources)

class ChildTemplate:
    def __init__(self, assignments: resources.AssignmentResources):
        self.assignments = assignments

    def get_references(self):
        return self.assignments.references

    def get_template(self,
            generation_config: GenerationConfig,
            resource_name_prefix=None):
        if not self.assignments:
            return None

        template = OrderedDict({
            "AWSTemplateFormatVersion": "2010-09-09",
        })
        add_parameters_to_template(template, references=sorted(self.get_references()))
        template["Resources"] = OrderedDict(template.get("Resources", {}))

        add_assignments_to_template(template, self.assignments,
                generation_config=generation_config,
                child_stack=True)

        return template

class ParentTemplate:
    def __init__(self,
            assignments: resources.AssignmentResources=None,
            permission_sets: resources.PermissionSetResources=None,
            child_templates=None):
        self.assignments = assignments
        self.permission_sets = permission_sets
        self.child_templates = list(child_templates) if child_templates else []

    def _get_template(self,
            generation_config: GenerationConfig,
            child_templates=None,
            base_template=None,
            parameters=None):
        template = OrderedDict({
            "AWSTemplateFormatVersion": "2010-09-09",
        })

        references = set()
        for child in self.child_templates:
            references.update(child.get_references())
        for assignment in self.assignments:
            references.update(assignment.references)

        for permission_set in self.permission_sets:
            references.discard(permission_set.get_resource_name())

        if base_template:
            found_references = set()
            for name in references:
                if is_name_in_template(name, base_template):
                    found_references.add(name)
            references -= found_references

        add_parameters_to_template(template,
                base_template=base_template,
                template_parameters=parameters,
                references=references)

        if base_template:
            for key in base_template:
                if key in ["AWSTemplateFormatVersion", "Parameters"]:
                    continue
                template[key] = utils.to_ordered_dict(base_template[key])

        if "Resources" not in template:
            template["Resources"] = OrderedDict()

        if self.permission_sets:
            for permission_set in self.permission_sets:
                resource_name = permission_set.get_resource_name()
                if not resource_name:
                    continue
                template["Resources"][resource_name] = permission_set.get_resource()

        if self.assignments:
            add_assignments_to_template(template, self.assignments,
                    generation_config=generation_config,
                    child_stack=False)

        def get_reference(name):
            DATA = [
                (("AWS::SSO::PermissionSet"), "PermissionSetArn"),
            ]
            for resource_types, attr in DATA:
                if name in template["Resources"] and template["Resources"][name]["Type"] in resource_types:
                    if attr:
                        return utils.GETATT_TAG([name, attr])
            return utils.REF_TAG(name)

        if child_templates:
            child_resource_names = []
            for child in child_templates:
                if not child.template:
                    continue
                if generation_config.max_concurrent_assignments and child_resource_names:
                    depends_on = child_resource_names[-1]
                else:
                    depends_on = None

                resource_name = re.sub(r'[^a-zA-Z0-9]', '', child.stem)
                resource = OrderedDict({
                    "Type": "AWS::CloudFormation::Stack",
                })
                if depends_on:
                    resource["DependsOn"] = depends_on
                resource["Properties"] =  OrderedDict({
                    "TemplateURL": str(child.path_for_resource)
                })
                if "Parameters" in child.template and child.template["Parameters"]:
                    resource["Properties"]["Parameters"] = OrderedDict()
                    for parameter_name in child.template["Parameters"].keys():
                        resource["Properties"]["Parameters"][parameter_name] = get_reference(parameter_name)
                template["Resources"][resource_name] = resource

                child_resource_names.append(resource_name)

        for resource in template["Resources"].values():
            if resource["Type"] != "AWS::SSO::PermissionSet":
                continue
            process_permission_set_resource(resource, generation_config)

        return template

    def get_templates(self,
            base_path: str,
            child_base_path_for_resource: str,
            stem,
            template_file_suffix,
            generation_config,
            base_template=None,
            parameters=None,
            child_templates_in_subdir=True,
            path_joiner=None):
        if not path_joiner:
            path_joiner = os.path.join

        child_templates = []

        for i, child in enumerate(self.child_templates):
            child_path_for_writing = base_path
            child_path_for_resource = child_base_path_for_resource

            if child_templates_in_subdir:
                child_path_for_writing = path_joiner(child_path_for_writing, stem)
                child_path_for_resource = path_joiner(child_path_for_resource, stem)
            child_stem = f"{stem}-{i:03d}"
            child_path_for_writing = path_joiner(child_path_for_writing, f"{child_stem}{template_file_suffix}")
            child_path_for_resource = path_joiner(child_path_for_resource, f"{child_stem}{template_file_suffix}")
            child_templates.append(_ChildData(
                child_path_for_writing,
                child_path_for_resource,
                child_stem,
                child.get_template(generation_config=generation_config)))

        parent_path = path_joiner(base_path, f"{stem}{template_file_suffix}")
        parent_template = self._get_template(
            generation_config=generation_config,
            child_templates=child_templates,
            base_template=base_template,
            parameters=parameters)

        return TemplateCollection(
            parent=WritableTemplate(parent_path, parent_template),
            children=[WritableTemplate(c.path_for_writing, c.template) for c in child_templates if c.template]
        )

def resolve_templates(
        assignments: resources.AssignmentResources,
        permission_sets: resources.PermissionSetResources,
        generation_config: GenerationConfig,
        num_parent_resources: int=0) -> ParentTemplate:

    num_child_stacks = generation_config.num_child_stacks
    max_resources_per_template = generation_config.max_resources_per_template
    num_resources_to_add = assignments.num_resources() + permission_sets.num_resources()
    too_many_resources_for_parent = (num_resources_to_add + num_parent_resources > max_resources_per_template)

    if num_child_stacks is None:
        if too_many_resources_for_parent:
            raise ValueError(f"Too many assignments ({len(assignments)}) to fit into template, specify a number of child stacks")
        parent_assignments = assignments
        child_templates = []
    elif num_child_stacks == 0:
        if too_many_resources_for_parent:
            raise ValueError(f"Too many resources ({num_resources_to_add}) to fit into template")
        parent_assignments = assignments
        child_templates = []
    else:
        if num_child_stacks * max_resources_per_template < len(assignments):
            raise ValueError(f"Too many assignments ({len(assignments)}) to fit into {num_child_stacks} child templates")
        parent_assignments = resources.AssignmentResources([])
        child_templates = [ChildTemplate(c) for c in assignments.allocate(num_child_stacks)]

    if permission_sets.num_resources() and permission_sets.num_resources() + num_parent_resources > max_resources_per_template:
        raise ValueError(f"Too many permission sets {permission_sets.num_resources()} to fit into template")

    parent_template = ParentTemplate(parent_assignments,
            permission_sets=permission_sets,
            child_templates=child_templates)

    return parent_template

def _fmt_managed_policy(policy):
    if isinstance(policy, str) and not policy.startswith("arn:"):
        return f"arn:aws:iam::aws:policy/{policy}"
    else:
        return policy

def process_permission_set_resource(resource, generation_config):
    properties = resource["Properties"]

    if generation_config.default_session_duration and "SessionDuration" not in properties:
        properties["SessionDuration"] = str(generation_config.default_session_duration)
    # If it's a number, we don't know what units
    # elif "SessionDuration" in properties and isinstance(properties["SessionDuration"], numbers.Number):
    #     unit = ???
    #     properties["SessionDuration"] = f"P{properties["SessionDuration"]}{unit}"

    if "InlinePolicy" in properties and not isinstance(properties["InlinePolicy"], (str, cfn_yaml_tags.CloudFormationObject)):
        try:
            properties["InlinePolicy"] = json.dumps(properties["InlinePolicy"])
        except:
            pass

    if "InstanceArn" not in properties:
        properties["InstanceArn"] = generation_config.ids.instance_arn

    if "ManagedPolicies" in properties:
        if not isinstance(properties["ManagedPolicies"], (list, tuple)):
            properties["ManagedPolicies"] = [_fmt_managed_policy(properties["ManagedPolicies"])]
        else:
            properties["ManagedPolicies"] = [_fmt_managed_policy(p) for p in properties["ManagedPolicies"]]
