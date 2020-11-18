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
import logging.handlers

from ..config import find_instances, SSOInstance

def configure_logging(logger, verbose, **config_args):
    if verbose in [False, None]:
        verbose = 0
    elif verbose == True:
        verbose = 1

    logging.basicConfig(**config_args)

    aws_sso_util_logger = logging.getLogger("aws_sso_util")
    root_logger = logging.getLogger()

    if verbose == 0:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)
    elif verbose == 1:
        logger.setLevel(logging.DEBUG)
        aws_sso_util_logger.setLevel(logging.INFO)
    elif verbose == 2:
        logger.setLevel(logging.DEBUG)
        aws_sso_util_logger.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.INFO)
    elif verbose >= 3:
        logger.setLevel(logging.DEBUG)
        aws_sso_util_logger.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.DEBUG)

class GetInstanceError(Exception):
    pass

def get_instance(sso_start_url, sso_region, sso_start_url_vars=None, sso_region_vars=None):
    instances, specifier, all_instances = find_instances(
        profile_name=None,
        profile_source=None,
        start_url=sso_start_url,
        start_url_source="CLI input",
        region=sso_region,
        region_source="CLI input",
        start_url_vars=sso_start_url_vars,
        region_vars=sso_region_vars
    )

    if not instances:
        if all_instances:
            raise GetInstanceError(
                f"No AWS SSO config matched {specifier.to_str(region=True)} " +
                f"from {SSOInstance.to_strs(all_instances)}")
        else:
            GetInstanceError("No AWS SSO config found")

    if len(instances) > 1:
        GetInstanceError(f"Found {len(instances)} SSO configs, please specify one: {SSOInstance.to_strs(instances)}")

    return instances[0]
