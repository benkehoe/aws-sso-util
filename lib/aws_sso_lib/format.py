# Copyright 2022 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import numbers

from .lookup import Ids

class FormatError(Exception):
    pass

def format_account_id(account_id):
    if isinstance(account_id, numbers.Number):
        account_id = str(int(account_id))
    if isinstance(account_id, str) and len(account_id) < 12:
        account_id = account_id.rjust(12, "0")
    return account_id

def format_permission_set_arn(ids: Ids, permission_set_id, raise_on_unknown=False):
    if isinstance(permission_set_id, str):
        if permission_set_id.startswith('arn'):
            return permission_set_id
        if permission_set_id.startswith('ssoins-') or permission_set_id.startswith('ins-'):
            return f"arn:aws:sso:::permissionSet/{permission_set_id}"
        if permission_set_id.startswith('ps-'):
            return f"arn:aws:sso:::permissionSet/{ids.instance_id}/{permission_set_id}"
        if raise_on_unknown:
            raise FormatError(f"Unrecognized PermissionSet ID format: {permission_set_id}")
    return permission_set_id
