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

from aws_sso_lib.config import find_instances, SSOInstance

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

class Printer:
    def __init__(self, *,
            separator,
            default_separator,
            header_fields,
            disable_header=False,
            skip_repeated_values=False,
            sort_key=None,
            printer=None):
        self.separator = separator
        self.default_separator = default_separator
        self._sep = separator if separator is not None else default_separator
        self._header_sep = separator if separator is not None else " " * len(default_separator)
        self._justify = separator is None

        self.sort_key = sort_key

        self.header_fields = header_fields
        self.disable_header = disable_header

        self.skip_repeated_values = skip_repeated_values

        self.print_along = self.separator and not self.sort_key
        self.rows = [] if not self.print_along else None

        self.printer = printer or print

    def print_header_before(self):
        if self.print_along and not self.disable_header:
            self.printer(self._header_sep.join(self.header_fields))

    def add_row(self, row):
        if self.print_along:
            self.printer(self._sep.join(row))
        else:
            self.rows.append(row)

    def _process_row_skip(self, row, prev_row):
        if self.skip_repeated_values is True:
            proc = lambda v, pv: "" if v == pv else v
            return [proc(v, pv) for v, pv in zip(row, prev_row)]
        else:
            proc = lambda s, v, pv: "" if s and v == pv else v
            return [proc(s, v, pv) for s, v, pv in zip(self.skip_repeated_values, row, prev_row)]

    def print_after(self):
        if self.print_along:
            return
        if self.sort_key:
            self.rows.sort(key=self.sort_key)

        if self.disable_header:
            col_widths = [0 for _ in self.header_fields]
        else:
            col_widths = [len(h) for h in self.header_fields]

        for row in self.rows:
            col_widths = [max(cw, len(v)) for cw, v in zip(col_widths, row)]

        def just(row):
            if not self._justify:
                return row
            else:
                return [v.ljust(cw) for cw, v in zip(col_widths, row)]

        if not self.disable_header:
            self.printer(self._header_sep.join(just(self.header_fields)))

        first_loop = True
        prev_row = None
        for row in self.rows:
            if not first_loop and self.skip_repeated_values:
                row_to_print = self._process_row_skip(row, prev_row)
            else:
                row_to_print = row

            self.printer(self._sep.join(just(row_to_print)))

            prev_row = row
            first_loop = False
