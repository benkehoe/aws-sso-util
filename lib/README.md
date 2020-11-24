# `aws-sso-lib`

`aws-sso-lib` allows you to programmatically interact with AWS SSO.

The primary functions that will be of interest are available at the package level:
* `get_boto3_session`: Get a boto3 session for a specific account and role.
* `login`: ensure the user is logged in to AWS SSO, with dispatch to the browser.
* `list_available_accounts` and `list_available_roles`: discover the access the user has.
* `list_assignments`: for admin purposes, iterate over all assignments in AWS SSO, which is currently hard to do through the API.

## Install

```
pip install --user aws-sso-lib
python -c "import aws_sso_lib; aws_sso_lib.login('https://my-start-url.awsapps.com/start', 'us-east-2')"
```

## `get_boto3_session`

