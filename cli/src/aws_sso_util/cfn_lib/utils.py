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

import logging
import json
import hashlib
from collections import OrderedDict

import yaml

from . import cfn_yaml_tags
cfn_yaml_tags.mark_safe()

from aws_sso_lib import lookup
from aws_sso_lib import format as _format

def to_ordered_dict(obj):
    if isinstance(obj, dict):
        return OrderedDict((k, to_ordered_dict(v)) for k, v in obj.items())
    elif isinstance(obj, list):
        return [to_ordered_dict(v) for v in obj]
    else:
        return obj

def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)

yaml.add_representer(OrderedDict, represent_ordereddict, Dumper=yaml.SafeDumper)
yaml.SafeDumper.ignore_aliases = lambda *args : True

def load_yaml(*args, **kwargs):
    return yaml.safe_load(*args, **kwargs)

def dump_yaml(*args, **kwargs):
    return yaml.safe_dump(*args, **kwargs)

def get_instance_id_from_arn(instance_arn):
    return instance_arn.split('/', 1)[1]

REF_TAG = getattr(cfn_yaml_tags, "Ref")
GETATT_TAG = getattr(cfn_yaml_tags, "GetAtt")
def get_references(value):
    references = set()
    if isinstance(value, REF_TAG):
        references.add(value.data)
    elif isinstance(value, dict) and "Ref" in value and len(value) == 1:
        references.add(value["Ref"].split(".")[0])
    elif isinstance(value, dict) and "Fn::GetAtt" in value and len(value) == 1:
        get_att_value = value["Fn::GetAtt"]
        if isinstance(get_att_value, str):
            references.add(get_att_value.split(".")[0])
        else:
            references.add(get_att_value[0])
    elif isinstance(value, cfn_yaml_tags.CloudFormationObject):
        value_json = value.to_json()
        references.update(get_references(value_json))
    elif isinstance(value, (list, set)):
        for v in value:
            references.update(get_references(v))
    elif isinstance(value, dict):
        for v in value.values():
            references.update(get_references(v))
    return references

def is_reference(value):
    if isinstance(value, cfn_yaml_tags.CloudFormationObject):
        return True
    elif isinstance(value, dict) and "Ref" in value and len(value) == 1:
        return True
    elif isinstance(value, dict) and "Fn::GetAtt" in value and len(value) == 1:
        return True
    else:
        return False

def get_hash_key(value):
    value = cfn_yaml_tags.to_json(value)
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True)
    return value.encode('utf-8')

def chunk_list_generator(lst, chunk_length):
    for i in range(0, len(lst), chunk_length):
        yield lst[i:i + chunk_length]

def hash_obj(obj):
    hasher = hashlib.md5()
    hasher.update(json.dumps(obj, sort_keys=True))
    return hasher.hexdigest()

def get_principal_name_fetcher(session, ids, cache):
    def fetcher(type, id):
        try:
            if type == "GROUP":
                group = lookup.lookup_group_by_id(session, ids, id, cache=cache)
                return group["DisplayName"]
            elif type == "USER":
                user = lookup.lookup_user_by_id(session, ids, id, cache=cache)
                return user["UserName"]
            else:
                raise ValueError(f"Unknown principal type {type}")
        except lookup.LookupError:
            return None
    return fetcher

def get_permission_set_name_fetcher(session, ids, cache):
    def fetcher(arn):
        try:
            ps = lookup.lookup_permission_set_by_id(session, ids, arn, cache=cache)
            return ps["Name"]
        except (lookup.LookupError, _format.FormatError):
            return None
    return fetcher

def get_target_name_fetcher(session, ids, cache):
    def fetcher(type, id):
        try:
            account = lookup.lookup_account_by_id(session, id, cache=cache)
            return account["Name"]
        except lookup.LookupError:
            return None
    return fetcher
