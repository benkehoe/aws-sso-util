import os
import re
import math
from collections import OrderedDict, namedtuple
from pathlib import PurePath

from . import resources
from . import utils

MAX_RESOURCES_PER_TEMPLATE = 500
MAX_CONCURRENT_ASSIGNMENTS = 20

WritableTemplate = namedtuple("WritableTemplate", ["path", "template"])
TemplateCollection = namedtuple("TemplateCollection", [
    "parent",
    "children",
])

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

def add_assignments_to_template(
        template,
        assignments: resources.AssignmentResources,
        max_concurrent_assignments=None):
    if not max_concurrent_assignments:
        max_concurrent_assignments = MAX_CONCURRENT_ASSIGNMENTS

    assignment_resources = []
    index_in_template = 0
    for assignment in assignments:
        if max_concurrent_assignments and len(assignment_resources) >= max_concurrent_assignments:
            depends_on = assignment_resources[index_in_template-max_concurrent_assignments][0]
        else:
            depends_on = None

        assignment_resources.append((
            assignment.get_resource_name(),
            assignment.get_resource(depends_on=depends_on)))

    if "Resources" not in template:
        template["Resources"] = OrderedDict()

    template["Resources"].update(assignment_resources)

class ChildTemplate:
    def __init__(self, assignments: resources.AssignmentResources):
        self.assignments = assignments

    def get_references(self):
        return self.assignments.references

    def get_template(self,
            max_concurrent_assignments=None,
            resource_name_prefix=None):
        template = OrderedDict({
            "AWSTemplateFormatVersion": "2010-09-09",
        })
        add_parameters_to_template(template, references=sorted(self.get_references()))
        template["Resources"] = OrderedDict(template.get("Resources", {}))

        add_assignments_to_template(template, self.assignments,
                max_concurrent_assignments=max_concurrent_assignments)

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
            child_templates=None,
            base_template=None,
            parameters=None,
            max_concurrent_assignments=None):
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
                template[key] = OrderedDict(base_template[key])

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
                    max_concurrent_assignments=max_concurrent_assignments)

        if child_templates:
            for child_path, child_stem, child_template in child_templates:
                resource_name = re.sub(r'[^a-zA-Z0-9]', '', child_stem)
                resource = OrderedDict({
                    "Type": "AWS::CloudFormation::Stack",
                    "Properties": OrderedDict({
                        "TemplateURL": str(child_path)
                    })
                })
                if "Parameters" in child_template and child_template["Parameters"]:
                    resource["Properties"]["Parameters"] = OrderedDict()
                    for parameter_name in child_template["Parameters"].keys():
                        resource["Properties"]["Parameters"][parameter_name] = utils.REF_TAG(parameter_name)
                template["Resources"][resource_name] = resource

        return template

    def get_templates(self,
            base_path: PurePath,
            stem,
            template_file_suffix,
            base_template=None,
            parameters=None,
            max_concurrent_assignments=None,
            child_templates_in_subdir=True,
            path_joiner=None):
        if not path_joiner:
            path_joiner = os.path.join

        child_templates = []

        for i, child in enumerate(self.child_templates):
            child_path = base_path
            if child_templates_in_subdir:
                child_path = path_joiner(child_path, stem)
            child_stem = f"{stem}{i:02d}"
            child_path = path_joiner(child_path, f"{child_stem}{template_file_suffix}")
            child_templates.append((
                child_path,
                child_stem,
                child.get_template(
                    max_concurrent_assignments=max_concurrent_assignments)))

        parent_path = path_joiner(base_path, f"{stem}{template_file_suffix}")
        parent_template = self._get_template(
            child_templates=child_templates,
            base_template=base_template,
            parameters=parameters,
            max_concurrent_assignments=max_concurrent_assignments)

        return TemplateCollection(
            parent=WritableTemplate(parent_path, parent_template),
            children=[WritableTemplate(c[0], c[2]) for c in child_templates]
        )

def resolve_templates(
        assignments: resources.AssignmentResources,
        permission_sets: resources.PermissionSetResources,
        max_resources_per_template: int=None,
        num_parent_resources: int=0) -> ParentTemplate:

    if not max_resources_per_template:
        max_resources_per_template = MAX_RESOURCES_PER_TEMPLATE
    if len(assignments) + len(permission_sets) + num_parent_resources > max_resources_per_template:
        child_templates = [ChildTemplate(c) for c in assignments.chunk(max_resources_per_template)]
        parent_assignments = resources.AssignmentResources([])
    else:
        parent_assignments = assignments
        child_templates = []

    parent_template = ParentTemplate(parent_assignments,
            permission_sets=permission_sets,
            child_templates=child_templates)

    return parent_template

def get_max_number_of_child_stacks(num_resources, max_resources_per_template=None):
    max_per_template = max_resources_per_template or MAX_RESOURCES_PER_TEMPLATE

    return math.ceil(num_resources/max_per_template)
