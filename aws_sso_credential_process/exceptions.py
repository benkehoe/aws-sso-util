# Copyright (c) 2012-2013 Mitch Garnaat http://garnaat.org/
# Copyright 2012-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

# this is the new content of botocore.exceptions in the v2 branch

from botocore.exceptions import BotoCoreError

class SSOError(BotoCoreError):
    fmt = "An unspecified error happened when resolving SSO credentials"


class PendingAuthorizationExpiredError(SSOError):
    fmt = (
        "The pending authorization to retrieve an SSO token has expired. The "
        "device authorization flow to retrieve an SSO token must be restarted."
    )


class SSOTokenLoadError(SSOError):
    fmt = "Error loading SSO Token: {error_msg}"


class UnauthorizedSSOTokenError(SSOError):
    fmt = (
        "The SSO session associated with this profile has expired or is "
        "otherwise invalid. To refresh this SSO session run aws2 sso login "
        "with the corresponding profile."
    )
