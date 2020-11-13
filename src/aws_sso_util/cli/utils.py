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

def configure_logging(logger, verbose, **config_args):
    if verbose in [False, None]:
        verbose = 0
    elif verbose == True:
        verbose = 1

    logging.basicConfig(**config_args)

    if verbose == 0:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

    aws_sso_util_logger = logging.getLogger("aws_sso_util")
    if verbose >= 1:
        aws_sso_util_logger.setLevel(logging.DEBUG)
    else:
        aws_sso_util_logger.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    if verbose >= 2:
        root_logger.setLevel(logging.DEBUG)

