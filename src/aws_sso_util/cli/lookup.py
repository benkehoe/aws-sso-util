import argparse
import sys
from collections import namedtuple

import boto3

import click

from ..api_utils import Ids

@click.command('lookup')
@click.argument('type', type=click.Choice(['instance', 'identity-store', 'group', 'user', 'permission-set']))
@click.argument('value', nargs=-1)

@click.option('--instance-arn', '--ins')
@click.option('--identity-store-id', '--ids')

@click.option('--profile')

@click.option('--error-if-not-found', '-e', is_flag=True)
@click.option('--show-id/--hide-id', default=False, help='Print SSO instance/identity store id being used')
@click.option('--separator', '--sep', default=': ')
def lookup(
        type,
        value,
        instance_arn,
        identity_store_id,
        profile,
        error_if_not_found,
        show_id,
        separator):

    session = boto3.Session(profile_name=profile)

    ids = Ids(session, instance_arn, identity_store_id)
    ids.suppress_print = not show_id

    try:
        if type == 'instance':
            ids.suppress_print = True
            print(ids.instance_arn)
        elif type == 'identity-store':
            ids.suppress_print = True
            print(ids.identity_store_id)
        elif type in 'group':
            if not value:
                raise click.UsageError("Group name is required")
            lines = []
            for name in value:
                try:
                    group_id = lookup_group_by_name(session, ids, name)
                except LookupError as e:
                    if error_if_not_found:
                        print(format_lines(lines, separator))
                        print("Group {} not found".format(name), file=sys.stderr)
                        sys.exit(1)
                    group_id = 'NOT_FOUND'
                lines.append((name, group_id))
            print(format_lines(lines, separator))
        elif type == 'user':
            if not value:
                raise click.UsageError("User name is required")
            lines = []
            for name in value:
                try:
                    user_id = lookup_user_by_name(session, ids, name)
                except LookupError as e:
                    if error_if_not_found:
                        print(format_lines(lines, separator))
                        print("User {} not found".format(name), file=sys.stderr)
                        sys.exit(1)
                    user_id = 'NOT_FOUND'
                lines.append((name, user_id))
            print(format_lines(lines, separator))
        elif type == 'permission-set':
            if not value:
                raise click.UsageError("Permission set name is required")
            lookup = PermissionSetArnLookup(session, ids)
            lines = []
            for name in value:
                try:
                    permission_set_arn = lookup.lookup_permission_set_arn(name)
                except LookupError as e:
                    if error_if_not_found:
                        print(format_lines(lines, separator))
                        print("Permission set {} not found".format(name), file=sys.stderr)
                        sys.exit(1)
                    permission_set_arn = 'NOT_FOUND'
                lines.append((name, permission_set_arn))
            print(format_lines(lines, separator))

    except LookupError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

def format_lines(lines, separator):
    max_len = max(len(l[0]) for l in lines)
    return '\n'.join("{}{}{}".format(l[0].ljust(max_len), separator, l[1]) for l in lines)

def lookup_group_by_name(session, ids, name):
    identity_store_client = session.client('identitystore')
    filters=[{'AttributePath': 'DisplayName', 'AttributeValue': name}]
    try:
        response = identity_store_client.list_groups(IdentityStoreId=ids.identity_store_id, Filters=filters)
        if len(response['Groups']) == 0:
            raise LookupError("No group named {} found".format(name))
        elif len(response['Groups']) > 1:
            raise LookupError("{} groups named {} found".format(len(response['Groups']), name))
        return response['Groups'][0]['GroupId']
    except:
        raise

def lookup_user_by_name(session, ids, name):
    identity_store_client = session.client('identitystore')
    filters=[{'AttributePath': 'UserName', 'AttributeValue': name}]
    try:
        response = identity_store_client.list_users(IdentityStoreId=ids.identity_store_id, Filters=filters)
        if len(response['Users']) == 0:
            raise LookupError("No user named {} found".format(name))
        elif len(response['Users']) > 1:
            raise LookupError("{} users named {} found".format(len(response['Users']), name))
        return response['Users'][0]['UserId']
    except:
        raise

class PermissionSetArnLookup:
    def __init__(self, session, ids):
        self.client = session.client('sso-admin')
        self.paginator = self.client.get_paginator('list_permission_sets')
        self.instance_arn = ids.instance_arn
        self.cache = {}

    def lookup_permission_set_arn(self, name):
        if name in self.cache:
            return self.cache[name]
        for response in self.paginator.paginate(InstanceArn=self.instance_arn):
            for permission_set_arn in response['PermissionSets']:
                ps_description = self.client.describe_permission_set(InstanceArn=self.instance_arn, PermissionSetArn=permission_set_arn)
                self.cache[ps_description['PermissionSet']['Name']] = permission_set_arn
            if name in self.cache:
                return self.cache[name]
        raise LookupError("No permission set named {} found".format(name))

if __name__ == '__main__':
    lookup(prog_name="python -m aws_sso_util.cli.lookup")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
