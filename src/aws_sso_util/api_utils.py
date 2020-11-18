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

import boto3

LOGGER = logging.getLogger(__name__)

class RetrievalError(Exception):
    pass

def get_accounts_for_ou(session, ou, recursive, refresh=False, cache=None):
    if not cache:
        cache = {}

    ou_children_key = f"{ou}#children"
    ou_accounts_key = f"{ou}#accounts"

    accounts = []

    if refresh or ou_accounts_key not in cache:
        LOGGER.info(f"Retrieving accounts for OU {ou}")
        client = session.client('organizations')

        ou_accounts = []

        paginator = client.get_paginator('list_accounts_for_parent')
        for response in paginator.paginate(ParentId=ou):
            ou_accounts.extend(response['Accounts'])

        cache[ou_accounts_key] = ou_accounts

        accounts.extend(ou_accounts)
    else:
        accounts.extend(cache[ou_accounts_key])

    if recursive:
        if refresh or ou_children_key not in cache:
            LOGGER.info(f"Retrieving child OUs for OU {ou}")
            client = session.client('organizations')

            ou_children = []

            paginator = client.get_paginator('list_organizational_units_for_parent')
            for response in paginator.paginate(ParentId=ou):
                sub_ous = [data['Id'] for data in response['OrganizationalUnits']]
                ou_children.extend(sub_ous)

            cache[ou_children_key] = ou_children

        for sub_ou_id in cache[ou_children_key]:
            accounts.extend(get_accounts_for_ou(session, sub_ou_id, True, refresh=refresh, cache=cache))

    return accounts

class LookupError(Exception):
    pass

class Ids:
    def __init__(self, session_fetcher, instance_arn=None, identity_store_id=None):
        if instance_arn and not instance_arn.startswith('arn:'):
            instance_arn = f"arn:aws:sso:::instance/{instance_arn}"

        self._session_fetcher = session_fetcher
        self._client = None
        self._instance_arn = instance_arn
        self._instance_arn_printed = False
        self._identity_store_id = identity_store_id
        self._identity_store_id_printed = False
        self.suppress_print = False

    def _get_client(self):
        if not self._client:
            self._client = self._session_fetcher().client('sso-admin')
        return self._client

    def _print(self, *args, **kwargs):
        if not self.suppress_print:
            print(*args, **kwargs)

    def instance_arn_matches(self, instance):
        if not self._instance_arn:
            return True
        if instance and not instance.startswith('arn:'):
            instance = f"arn:aws:sso:::instance/{instance}"
        return instance == self._instance_arn

    @property
    def instance_arn(self):
        if self._instance_arn:
            if not self._instance_arn_printed:
                self._print("Using SSO instance {}".format(self._instance_arn.split('/')[-1]))
                self._instance_arn_printed = True
            return self._instance_arn
        response = self._get_client().list_instances()
        if len(response['Instances']) == 0:
            raise LookupError("No SSO instance found, please specify with --instance-arn")
        elif len(response['Instances']) > 1:
            raise LookupError("{} SSO instances found, please specify with --instance-arn".format(len(response['Instances'])))
        else:
            instance_arn = response['Instances'][0]['InstanceArn']
            self._instance_arn = instance_arn
            self._print("Using SSO instance {}".format(self._instance_arn.split('/')[-1]))
            self._instance_arn_printed = True
            identity_store_id = response['Instances'][0]['IdentityStoreId']
            if self._identity_store_id and self._identity_store_id != identity_store_id:
                raise LookupError("SSO instance identity store {} does not match given identity store {}".format(identity_store_id, self._identity_store_id))
            else:
                self._identity_store_id = identity_store_id
        return self._instance_arn

    @property
    def instance_id(self):
        return self.instance_arn.split("/", 1)[1]

    @property
    def identity_store_id(self):
        if self._identity_store_id:
            if not self._identity_store_id_printed:
                self._print("Using SSO identity store {}".format(self._identity_store_id))
                self._identity_store_id_printed = True
            return self._identity_store_id
        response = self._get_client().list_instances()
        if len(response['Instances']) == 0:
            raise LookupError("No SSO instance found, please specify identity store with --identity-store-id or instance with --instance-arn")
        elif len(response['Instances']) > 1:
            raise LookupError("{} SSO instances found, please specify identity store with --identity-store-id or instance with --instance-arn".format(len(response['Instances'])))
        else:
            identity_store_id = response['Instances'][0]['IdentityStoreId']
            self._identity_store_id = identity_store_id
            self._print("Using SSO identity store {}".format(self._identity_store_id))
            self._identity_store_id_printed = True
            instance_arn = response['Instances'][0]['InstanceArn']
            instance_id = instance_arn.split('/')[-1]
            if self._instance_arn and self._instance_arn != instance_arn:
                raise LookupError("SSO instance {} does not match given instance {}".format(instance_id, self._instance_arn.split('/')[-1]))
            else:
                self._instance_arn = instance_arn
        return self._identity_store_id
