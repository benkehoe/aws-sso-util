import logging

import boto3

LOGGER = logging.getLogger(__name__)

class RetrievalError(Exception):
    pass

PROFILE = None
SESSION = None
def get_session(logger=None):
    if not logger:
        logger = LOGGER
    else:
        logger = logger.getChild("api_utils")

    global PROFILE, SESSION
    if not SESSION:
        if PROFILE:
            logger.debug(f"Creating session with profile {PROFILE}")
        else:
            logger.debug(f"Creating session")
        SESSION = boto3.Session(profile_name=PROFILE)
    return SESSION

SSO_INSTANCE = None
def get_sso_instance(session=None, logger=None):
    if not session:
        session = get_session(logger=logger)

    if not logger:
        logger = LOGGER
    else:
        logger = logger.getChild("api_utils")

    global SSO_INSTANCE
    if not SSO_INSTANCE:
        logger.info(f"Retrieving SSO instance")
        response = get_session().client('sso-admin').list_instances()
        if len(response['Instances']) == 0:
            raise RetrievalError("No SSO instance found, must specify instance")
        elif len(response['Instances']) > 1:
            raise RetrievalError("{} SSO instances found, must specify instance".format(len(response['Instances'])))
        else:
            instance_arn = response['Instances'][0]['InstanceArn']
            instance_id = instance_arn.split('/')[-1]
            logger.info("Using SSO instance {}".format(instance_id))
            SSO_INSTANCE = instance_arn
    if SSO_INSTANCE.startswith('ssoins-') or SSO_INSTANCE.startswith('ins-'):
        SSO_INSTANCE = f"arn:aws:sso:::instance/{SSO_INSTANCE}"
    return SSO_INSTANCE

OU_CACHE = {}
def get_accounts_for_ou(ou, recursive, refresh=False, session=None, cache=None, logger=None):
    if not session:
        session = get_session(logger=logger)

    if not logger:
        logger = LOGGER
    else:
        logger = logger.getChild("api_utils")

    global OU_CACHE
    if not cache:
        cache = OU_CACHE

    ou_children_key = f"{ou}#children"
    ou_accounts_key = f"{ou}#accounts"

    accounts = []

    if refresh or ou_accounts_key not in cache:
        logger.info(f"Retrieving accounts for OU {ou}")
        client = session.client('organizations')

        ou_accounts = []

        paginator = client.get_paginator('list_accounts_for_parent')
        for response in paginator.paginate(ParentId=ou):
            ou_accounts.extend(data['Id'] for data in response['Accounts'])

        cache[ou_accounts_key] = ou_accounts

        accounts.extend(ou_accounts)
    else:
        accounts.extend(cache[ou_accounts_key])

    if recursive:
        if refresh or ou_children_key not in cache:
            logger.info(f"Retrieving child OUs for OU {ou}")
            client = session.client('organizations')

            ou_children = []

            paginator = client.get_paginator('list_organizational_units_for_parent')
            for response in paginator.paginate(ParentId=ou):
                sub_ous = [data['Id'] for data in response['OrganizationalUnits']]
                ou_children.extend(sub_ous)

            cache[ou_children_key] = ou_children

        for sub_ou_id in cache[ou_children_key]:
            accounts.extend(get_accounts_for_ou(sub_ou_id, True, refresh=refresh, session=session, cache=cache, logger=logger))

    return accounts

class LookupError(Exception):
    pass

class Ids:
    def __init__(self, session, instance_arn, identity_store_id):
        self._client = session.client('sso-admin')
        self._instance_arn = instance_arn
        self._instance_arn_printed = False
        self._identity_store_id = identity_store_id
        self._identity_store_id_printed = False
        self.suppress_print = False

    def _print(self, *args, **kwargs):
        if not self.suppress_print:
            print(*args, **kwargs)

    @property
    def instance_arn(self):
        if self._instance_arn:
            if not self._instance_arn_printed:
                self._print("Using SSO instance {}".format(self._instance_arn.split('/')[-1]))
                self._instance_arn_printed = True
            return self._instance_arn
        response = self._client.list_instances()
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
    def identity_store_id(self):
        if self._identity_store_id:
            if not self._identity_store_id_printed:
                self._print("Using SSO identity store {}".format(self._identity_store_id))
                self._identity_store_id_printed = True
            return self._identity_store_id
        response = self._client.list_instances()
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
