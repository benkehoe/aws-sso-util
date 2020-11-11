import uuid
import random
import string

"""
instance arn: arn:aws:sso:::instance/ssoins- 16 hex
group: uuid
user: uuid
permission set: arn:aws:sso:::permissionSet/ssoins-X/ps- 16 hex
ou: ou- 4 alphanum - 8 alphanum
account: 123456789012
"""

hex = '0123456789abcdef'
alphanum = string.ascii_lowercase + string.digits

def sample(lst, length):
    return ''.join(random.choice(lst) for _ in range(length))

instance_id = 'ssoins-{}'.format(sample(hex, 16))

print('instance:       arn:aws:sso:::instance/{}'.format(instance_id))

print('user/group:     {}'.format(uuid.uuid4()))

print('permission-set: arn:aws:sso:::permissionSet/{}/ps-{}'.format(instance_id, sample(hex, 16)))

print('OU:             ou-{}-{}'.format(sample(alphanum, 4), sample(alphanum, 8)))

print('account:        {}'.format(sample(string.digits, 12)))


