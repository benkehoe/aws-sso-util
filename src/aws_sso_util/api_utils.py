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
        session = get_session()

    if not logger:
        logger = LOGGER
    else:
        logger = logger.getChild("api_utils")

    global SSO_INSTANCE
    if not SSO_INSTANCE:
        logger.info(f"Retrieving SSO instance")
        response = get_session().client('sso-admin').list_instances()
        if len(response['Instances']) == 0:
            raise RetrievalError("No SSO instance found, please specify with --instance")
        elif len(response['Instances']) > 1:
            raise RetrievalError("{} SSO instances found, please specify with --instance".format(len(response['Instances'])))
        else:
            instance_arn = response['Instances'][0]['InstanceArn']
            instance_id = instance_arn.split('/')[-1]
            print("Using SSO instance {}".format(instance_id))
            SSO_INSTANCE = instance_arn
    if SSO_INSTANCE.startswith('ssoins-') or SSO_INSTANCE.startswith('ins-'):
        SSO_INSTANCE = f"arn:aws:sso:::instance/{SSO_INSTANCE}"
    return SSO_INSTANCE

OU_ACCOUNTS_CACHE = {}
def get_accounts_for_ou(ou, refresh=False, session=None, cache=None, logger=None):
    if not session:
        session = get_session()

    if not logger:
        logger = LOGGER
    else:
        logger = logger.getChild("api_utils")

    global OU_ACCOUNTS_CACHE
    if not cache:
        cache = OU_ACCOUNTS_CACHE

    if refresh or ou not in cache:
        logger.info(f"Retrieving accounts for OU {ou}")
        client = session.client('organizations')

        accounts = []

        paginator = client.get_paginator('list_organizational_units_for_parent')
        for response in paginator.paginate(ParentId=ou):
            sub_ous = [data['Id'] for data in response['OrganizationalUnits']]
            for sub_ou_id in sub_ous:
                accounts.extend(get_accounts_for_ou(sub_ou_id))

        paginator = client.get_paginator('list_accounts_for_parent')
        for response in paginator.paginate(ParentId=ou):
            accounts.extend(data['Id'] for data in response['Accounts'])

        cache[ou] = accounts
    return cache[ou]
