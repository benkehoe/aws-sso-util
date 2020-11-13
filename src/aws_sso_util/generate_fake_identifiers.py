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

import uuid
import random
import string

"""
instance arn: arn:aws:sso:::instance/ssoins-{16 hex}
identity store: d-{10 hex}
start url: https://d-X.awsapps.com/start
group: uuid
user: uuid
permission set: arn:aws:sso:::permissionSet/ssoins-X/ps-{16 hex}
ou: ou- 4 alphanum - 8 alphanum
account: 123456789012
"""

hex = '0123456789abcdef'
alphanum = string.ascii_lowercase + string.digits

def sample(lst, length):
    return ''.join(random.choice(lst) for _ in range(length))

instance_id = 'ssoins-{}'.format(sample(hex, 16))
identity_store = 'd-{}'.format(sample(hex, 10))

print('instance:       arn:aws:sso:::instance/{}'.format(instance_id))

print('identity store: {}'.format(identity_store))

print('start url:      https://{}.awsapps.com/start'.format(identity_store))

print('user/group:     {}'.format(uuid.uuid4()))

print('permission-set: arn:aws:sso:::permissionSet/{}/ps-{}'.format(instance_id, sample(hex, 16)))

print('OU:             ou-{}-{}'.format(sample(alphanum, 4), sample(alphanum, 8)))

print('account:        {}'.format(sample(string.digits, 12)))


