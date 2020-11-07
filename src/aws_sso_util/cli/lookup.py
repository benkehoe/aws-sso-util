import argparse
import sys

import boto3

import click

class LookupError(Exception):
    pass

class Ids:
    def __init__(self, sso_admin_client, instance_arn, identity_store_id):
        self._client = sso_admin_client
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
                self._print("Using SSO identity store {}".format(identity_store_id))
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
            self._print("Using SSO identity store {}".format(identity_store_id))
            self._identity_store_id_printed = True
            instance_arn = response['Instances'][0]['InstanceArn']
            instance_id = instance_arn.split('/')[-1]
            if self._instance_arn and self._instance_arn != identity_store_id:
                raise LookupError("SSO instance {} does not match given instance {}".format(instance_id, self._instance_arn.split('/')[-1]))
            else:
                self._instance_arn = instance_arn
        return self._identity_store_id

@click.command('lookup')
@click.argument('type', type=click.Choice(['instance', 'identity-store', 'groups', 'users', 'permission-sets']))
@click.argument('value', nargs=-1)

@click.option('--instance-arn', '--ins')
@click.option('--identity-store-id', '--ids')

@click.option('--profile')

@click.option('--error-if-not-found', '-e', is_flag=True)
@click.option('--show-id', is_flag=True, help='Print SSO instance/identity store id being used')
@click.option('--separator', default=': ')
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
    sso_admin_client = session.client('sso-admin')
    identity_store_client = session.client('identitystore')

    ids = Ids(sso_admin_client, instance_arn, identity_store_id)
    ids.suppress_print = not show_id

    try:
        if type == 'instance':
            ids.suppress_print = True
            print(ids.instance_arn)
        elif type == 'identity-store':
            ids.suppress_print = True
            print(ids.identity_store_id)
        elif type == 'groups':
            if not value:
                raise click.UsageError("Group name is required")
            lines = []
            for name in value:
                try:
                    group_id = lookup_group_by_name(identity_store_client, ids, name)
                except LookupError as e:
                    if error_if_not_found:
                        print(format_lines(lines, separator))
                        print("Group {} not found".format(name), file=sys.stderr)
                        sys.exit(1)
                    group_id = 'NOT_FOUND'
                lines.append((name, group_id))
            print(format_lines(lines, separator))
        elif type == 'users':
            if not value:
                raise click.UsageError("User name is required")
            lines = []
            for name in value:
                try:
                    user_id = lookup_user_by_name(identity_store_client, ids, name)
                except LookupError as e:
                    if error_if_not_found:
                        print(format_lines(lines, separator))
                        print("User {} not found".format(name), file=sys.stderr)
                        sys.exit(1)
                    user_id = 'NOT_FOUND'
                lines.append((name, user_id))
            print(format_lines(lines, separator))
        elif type == 'permission-sets':
            if not value:
                raise click.UsageError("Permission set name is required")
            lookup = PermissionSetArnLookup(sso_admin_client, ids)
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

def lookup_group_by_name(identity_store_client, ids, name):
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

def lookup_user_by_name(identity_store_client, ids, name):
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
    def __init__(self, sso_admin_client, ids):
        self.client = sso_admin_client
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
