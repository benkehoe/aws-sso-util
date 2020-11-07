import logging
from collections import OrderedDict

import yaml
from . import cfn_yaml_tags
cfn_yaml_tags.mark_safe()

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

def get_logger(parent, name) -> logging.Logger:
    if parent:
        return parent.getChild(name)
    else:
        return logging.getLogger(name)

def get_instance_id_from_arn(instance_arn):
    return instance_arn.split('/', 1)[1]

REF_TAG = getattr(cfn_yaml_tags, "Ref")
def get_references(value, references=None):
    if not references:
        references = set()
    if isinstance(value, REF_TAG):
        references.add(value.data)
    elif isinstance(value, (list, set)):
        for v in value:
            references.update(get_references(v, references))
    elif isinstance(value, dict):
        for v in value.values():
            references.update(get_references(v, references))
    return references

def get_hash_key(value):
    if isinstance(value, REF_TAG):
        return f"!Ref={value}".encode('utf-8')
    else:
        return value.encode('utf-8')

def chunk_list_generator(lst, chunk_length):
    for i in range(0, len(lst), chunk_length):
        yield lst[i:i + chunk_length]
