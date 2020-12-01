# `aws-sso-lib`

`aws-sso-lib` allows you to programmatically interact with AWS SSO.

The primary functions that will be of interest are available at the package level:
* `get_boto3_session`: Get a boto3 session for a specific account and role.
* `login`: ensure the user is logged in to AWS SSO, with dispatch to the browser.
* `list_available_accounts` and `list_available_roles`: discover the access the user has.
* `list_assignments`: for admin purposes, iterate over all assignments in AWS SSO, which is currently hard to do through the API.

`aws-sso-util` is a command-line utility built on `aws-sso-lib` for interacting with AWS SSO; see the details of that project [here](https://github.com/benkehoe/aws-sso-util).

## Install

```
pip install --user aws-sso-lib
python -c "import aws_sso_lib; aws_sso_lib.login('https://my-start-url.awsapps.com/start', 'us-east-2')"
```

## `get_boto3_session`

Often when writing a script, you know the exact account and role you want the script to use.
You could configure a profile in your `~/.aws/config` for this (perhaps using `aws-sso-util configure profile`), but especially if multiple people may be using the script, it's more convenient to have the configuration baked into the script itself.
`get_boto3_session()` is the function to do that with.

```python
get_boto3_session(start_url, sso_region, account_id, role_name, region, login=False)
```

* `start_url`: [REQUIRED] The start URL for the AWS SSO instance.
* `sso_region`: [REQUIRED] The AWS region for the AWS SSO instance.
* `account_id`: [REQUIRED] The AWS account ID to use.
* `role_name`: [REQUIRED] The AWS SSO role (aka PermissionSet) name to use.
* `region`: [REQUIRED] The AWS region for the boto3 session.
* `login`: Set to `True` to interactively log in the user if their AWS SSO credentials have expired.
* Returns a [boto3 Session object](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/core/session.html) configured for the account and role.

For more control over the login process, use the `login` function separately.

## `login`

While the functions that require the user to be logged in let you specify `login=True` to interactively log in the user if they are not already logged in, you can have more control over the process, or retrieve the access token, using `login()`.

If the user is not logged in or `force_refresh` is `True`, it will attempt to log in.
If the user is logged in and `force_refresh` is `False`, no action is taken.

Normally, it will attempt to automatically open the user's browser to log in, as well as printing the URL and code to stderr as a fallback. However, if `disable_browser` is `True`, or if `disable_browser` is `None` (the default) and the environment variable `AWS_SSO_DISABLE_BROWSER` is set to `1` or `true`, only the message with the URL and code will be printed.

A custom message can be printed by setting `message` to a template string using `{url}` and `{code}` as placeholders.
The message can be suppressed by setting `message` to `False`.

```python
login(start_url, sso_region, force_refresh=False, disable_browser=None, message=None, outfile=None)
```

* `start_url`: [REQUIRED] The start URL for the AWS SSO instance.
* `sso_region`: [REQUIRED] The AWS region for the AWS SSO instance.
* `force_refresh`: Set to `True` to always go through the authentication process.
* `disable_browser`: Set to `True` to skip the browser popup and only print a message with the URL and code.
* `message`: A message template to print with the fallback URL and code, or `False` to suppress the message.
* `outfile`: The file-like object to print the message to (stderr by default)
* Returns the token dict as returned by [sso-oidc:CreateToken](https://docs.aws.amazon.com/singlesignon/latest/OIDCAPIReference/API_CreateToken.html), which contains the actual authorization token, as well as the expiration.

## `list_available_accounts` and `list_available_roles`

AWS SSO provides programmatic access to the permissions that a user has.
You can access this through `list_available_accounts()` and `list_available_roles()`.

With both, you can set `login=True` to interactively log in the user if they are not already logged in.

Note that these functions return iterators; they don't return a list, because the number of roles may be very large and you shouldn't have to wait for the entire list to be created to start processing.
You can always get a list by, for example, `list(list_available_roles(...))`.

```python
list_available_accounts(start_url, sso_region, login=False)
```

* `start_url`: The start URL for the AWS SSO instance.
* `sso_region`: The AWS region for the AWS SSO instance.
* `login`: Set to `True` to interactively log in the user if their AWS SSO credentials have expired.
* Returns an iterator that yields account id and account name.

```
list_available_roles(start_url, sso_region, account_id=None, login=False)
```

* `start_url`: [REQUIRED] The start URL for the AWS SSO instance.
* `sso_region`: [REQUIRED] The AWS region for the AWS SSO instance.
* `account_id`: Optional account id or list of account ids to check.
  * If not set, all accounts available to the user are used.
* `login`: Set to `True` to interactively log in the user if their AWS SSO credentials have expired.
* Returns an iterator that yields account id, account name, and role name.

## `list_assignments`

The AWS SSO API only allows you to [list assignments for a specific account _and_ permission set](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListAccountAssignments.html).
To find all your assignments, you need to iterate over all accounts, and then interate over all permission sets.
`list_assignments()` does this work for you.

Unlike the other functions list above, this uses admin APIs, which require AWS credentials, rather than taking as input a start URL and region.

`list_assignments` returns an iterator over `Assignment` named tuples, which have the following fields:

* `instance_arn`
* `principal_type`
* `principal_id`
* `principal_name`
* `permission_set_arn`
* `permission_set_name`
* `target_type`
* `target_id`
* `target_name`

The name fields may be `None`, if the names are not known or looked up.
By default, principal and permission set names are not retrieved, nor are account names for accounts that have been provided as explicit targets.

If you don't specify `instance_arn` and/or `identity_store_id`, these will be looked up using the [ListInstances API](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html), which today returns at most one instance (with associated identity store).

An assignment is the combination of a principal (a user or a group), a permission set, and a target (an AWS account).
For each of these values, you can provide either an explicit specification, or a filter function.

You can provide an OU as a target, which will use all accounts in that OU, and optionally all accounts recursively in child OUs as well.

```python
list_assignments(
    session,
    instance_arn=None,
    identity_store_id=None,
    principal=None,
    principal_filter=None,
    permission_set=None,
    permission_set_filter=None,
    target=None,
    target_filter=None,
    get_principal_names=False,
    get_permission_set_names=False,
    get_target_names=False,
    ou_recursive=False)
```

* `session`: [REQUIRED] boto3 session to use
* `instance_arn`: The SSO instance to use, or it will be looked up using ListInstances
* `identity_store_id`: The identity store to use if principal names are being retrieved or it will be looked up using ListInstances
* `principal`: A principal specification or list of principal specifications.
  * A principal specification is a principal id or a 2-tuple of principal type and id.
* `principal_filter`: A callable taking principal type, principal id, and principal name (which may be `None`), and returning `True` if the principal should be included.
* `permission_set`: A permission set arn or id, or a list of the same.
* `permission_set_filter`: A callable taking permission set arn and name (name may be `None`), returning True if the permission set should be included.
* `target`: A target specification or list of target specifications.
  * A target specification is an account or OU id, or a 2-tuple of target type, which is either AWS_ACCOUNT or AWS_OU, and target id.
* `target_filter`: A callable taking target type, target id, and target name (which may be `None`), and returning `True` if the target should be included.
* `get_principal_names`: Set to `True` to retrieve names for principals in assignments.
* ` get_permission_set_names`: Set to `True` to retrieve names for permission sets in assignments.
* `get_target_names`: Set to `True` to retrieve names for targets in assignments, when they are explicitly provided as targets. For OUs as targets or if no targets are specified, the account names will be retrieved automatically during the enumeration process.
* `ou_recursive`: Set to `True` if an OU is provided as a target to get all accounts including those in child OUs.
* Returns an iterator over `Assignment` tuples
