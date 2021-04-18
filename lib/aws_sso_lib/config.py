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
import re
from collections import namedtuple

import botocore
from botocore.exceptions import ProfileNotFound

LOGGER = logging.getLogger(__name__)

def _get(names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value, name
    return None, None

START_URL_VARS = ["AWS_DEFAULT_SSO_START_URL"]
REGION_VARS    = ["AWS_DEFAULT_SSO_REGION"]

class SSOInstance(namedtuple("SSOInstance", ["start_url", "region", "start_url_source", "region_source"])):
    def to_str(self, region=None):
        if region is None:
            region_str = "[NO_REGION]" if not self.region else ""
        elif region:
            region_str = f"[{self.region}]"
        else:
            region_str = ""
        return f"{self.start_url}{region_str}"

    def __str__(self):
        return self.to_str()

    def __bool__(self):
        return bool(self.start_url) or bool(self.region)

    @classmethod
    def to_strs(cls, instances, region=None):
        return ", ".join(i.to_str(region=region) for i in instances)

def _get_instance_from_profile(profile_name, scoped_config: dict, missing_ok=False) -> SSOInstance:
    start_url = scoped_config.get("sso_start_url")
    region = scoped_config.get("sso_region")
    if not (start_url and region):
        if not missing_ok:
            LOGGER.debug(f"Did not find config in profile {profile_name}")
        return None
    instance = SSOInstance(start_url, region, "profile", "profile")
    LOGGER.debug(f"Profile {profile_name} has instance {instance.to_str(region=True)}")
    return instance

def _get_all_instances_from_config(full_config: dict):
    instances = {}
    for profile_name, scoped_config in full_config.get("profiles", {}).items():
        instance = _get_instance_from_profile(profile_name, scoped_config, missing_ok=True)
        if not instance:
            continue
        if instance.start_url in instances and instance.region != instances[instance.start_url].region:
            regions = f"{instance.region}, {instances[instance.start_url].region}"
            LOGGER.warning(f"Region mismatch in config for {instance.start_url}: {regions}")
        else:
            instances[instance.start_url] = instance

    return sorted(instances.values(), key=lambda i: i.start_url)

def _validate_instance(instance: SSOInstance, source, start_url, start_url_source, region, region_source):
    if start_url and instance.start_url != start_url:
        message = f"start URL {instance.start_url} does not match {start_url} from {start_url_source}"
        LOGGER.warn(message)
    if region and instance.region != region:
        message = f"region {instance.region} does not match {region} from {region_source}"
        LOGGER.warn(message)

def _find_instance_from_profile(
        profile_name=None,
        profile_source=None,
        start_url=None,
        start_url_source=None,
        region=None,
        region_source=None):
    try:
        session = botocore.session.Session(profile=profile_name)
        instance = _get_instance_from_profile(profile_name, session.get_scoped_config())
    except ProfileNotFound:
        return None
    if not instance:
        return None
    _validate_instance(instance, profile_source, start_url, start_url_source, region, region_source)
    return instance

def _get_specifier(
        start_url=None,
        start_url_source=None,
        region=None,
        region_source=None,
        start_url_vars=None,
        region_vars=None):

    if start_url is None and region is None:
        if start_url_vars:
            start_url, start_url_source = _get(start_url_vars)
        if region_vars:
            region, region_source = _get(region_vars)

    if start_url is None and region is None:
        start_url, start_url_source = _get(START_URL_VARS)
        region, region_source = _get(REGION_VARS)

    return SSOInstance(start_url, region, start_url_source, region_source)

def _specifier_matches(specifier, instance):
    if specifier.start_url:
        if specifier.start_url.startswith("http"):
            if not specifier.start_url == instance.start_url:
                return False, "does not match literal start URL"
        elif not re.search(specifier.start_url, instance.start_url):
            return False, "does not match regex start URL"
        if specifier.region and specifier.region != instance.region:
            LOGGER.warn(
                f"Instance {instance.start_url} " +
                f"from {instance.start_url_source} " +
                f"has region {instance.region} " +
                f"which does not match {specifier.region} " +
                f"from {specifier.region_source}"
            )

    if specifier.region and specifier.region != instance.region:
        return False, "does not match region"

    if specifier.start_url:
        if specifier.start_url.startswith("http"):
            if specifier.region:
                return True, "matches literal start URL and region"
            else:
                return True, "matches literal start URL and region"
        elif specifier.region:
            return True, "matches regex start URL and region"
        else:
            return True, "matches regex start URL"
    else:
        return True, "matches region"


def find_instances(
        profile_name=None,
        profile_source=None,
        start_url=None,
        start_url_source=None,
        region=None,
        region_source=None,
        start_url_vars=None,
        region_vars=None):
    if profile_name:
        LOGGER.debug(f"Finding instance from profile {profile_name}")
        instance = _find_instance_from_profile(
            profile_name=profile_name,
            profile_source=profile_source,
            start_url=start_url,
            start_url_source=start_url_source,
            region=region,
            region_source=region_source
        )
        if instance:
            return [instance], None, [instance]
        else:
            LOGGER.debug("No instance found in profile")
            return [], None, []

    specifier = _get_specifier(
        start_url=start_url,
        start_url_source=start_url_source,
        region=region,
        region_source=region_source,
        start_url_vars=start_url_vars,
        region_vars=region_vars,
    )

    if specifier:
        parts = [
            f"Using AWS SSO instance specifier"
        ]
        if specifier.start_url:
            parts.extend([
                f"{specifier.start_url}",
                f"from {specifier.start_url_source}"
            ])
        if specifier.region:
            if specifier.start_url:
                parts.append("with")
            parts.extend([
                "region",
                f"{specifier.region}",
                f"from {specifier.region_source}"
            ])
        LOGGER.info(" ".join(parts))
    else:
        LOGGER.debug("No AWS SSO instance specifier found")

    if specifier.start_url and specifier.region and specifier.start_url.startswith("http"):
        LOGGER.debug("Specifier has literal start URL and region, not searching for instances")
        return [specifier], specifier, [specifier]

    session = botocore.session.Session()
    all_instances = _get_all_instances_from_config(session.full_config)

    LOGGER.debug(f"Found instances: {SSOInstance.to_strs(all_instances, region=True)}")

    if not specifier:
        LOGGER.debug("No specifier, returning all instances")
        return all_instances, specifier, all_instances

    instances = []
    for instance in all_instances:
        match, reason = _specifier_matches(specifier, instance)
        if match:
            LOGGER.debug(f"Instance {instance} {reason}")
            instances.append(instance)
        else:
            LOGGER.debug(f"Instance {instance} {reason}")

    LOGGER.debug(f"Matching instances: {SSOInstance.to_strs(instances)}")

    return instances, specifier, all_instances
