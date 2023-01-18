# `aws-sso-util credential-process`
**Get Identity Center working with all the SDKs that don't understand it yet**

Currently, [Identity Center](https://aws.amazon.com/single-sign-on/) support is implemented in the [AWS CLI v2](https://aws.amazon.com/blogs/developer/aws-cli-v2-is-now-generally-available/), but the capability to usage the credentials retrieved from Identity Center by the CLI v2 has not been implemented in the various AWS SDKs. However, they all support the [credential process](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html) system. This tool bridges the gap by implementing a credential process provider that understands the Identity Center credential retrieval and caching system. Once AWS implements the necessary support in the SDK for your favorite language, this tool will no longer be necessary.

If you try this and your tools still don't work with the credentials, you can get the credentials themselves using [aws-export-credentials](https://github.com/benkehoe/aws-export-credentials), which can also inject them as environment variables for your program.

## SDK support for Identity Center

Read this section to determine if the SDK in your language of choice has implemented support for Identity Center.

* [boto3 (the Python SDK)](boto3.amazonaws.com/v1/documentation/api/latest/index.html) has added support for loading credentials cached by [`aws sso login`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/sso/login.html) as of [version 1.14.0](https://github.com/boto/boto3/blob/develop/CHANGELOG.rst#1140). However, it does not support initiating authentication. That is, if the credentials are expired, you have to use `aws sso login` to login again, and this of course means that you (and your users) need the AWS CLI v2 installed for your Python scripts to use Identity Center credentials. `aws-sso-util credential-process` does not have a dependency on AWS CLI v2 and supports initiating authentication.

## Quickstart

1. Set up your `.aws/config` file for Identity Center as normal (see step 6 for how to make this easier):

```
[profile my-sso-profile]

region = us-east-2
output = yaml

sso_start_url = https://something.awsapps.com/start
sso_region = us-east-2
sso_account_id = 123456789012
sso_role_name = MyLeastPrivilegeRole
```

2. Then, just add a [`credential_process` entry](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html) to the profile, using the `--profile` flag with the same profile name (see step 6 for how to make this easier):

```
[profile my-sso-profile]

credential_process = aws-sso-util credential-process --profile my-sso-profile

region = us-east-2
output = yaml

sso_start_url = https://something.awsapps.com/start
sso_region = us-east-2
sso_account_id = 123456789012
sso_role_name = MyLeastPrivilegeRole

```

3. You're done! Test it out:
```bash
aws sso login --profile my-sso-profile
AWS_PROFILE=my-sso-profile AWS_SDK_LOAD_CONFIG=1 node -e "new (require('aws-sdk')).STS().getCallerIdentity(console.log)"
```

NOTE: if you test it out with your favorite script or application and get something like `NoCredentialProviders: no valid providers in chain.`, you may need to set the environment variable `AWS_SDK_LOAD_CONFIG=1`. The Go SDK, and applications built with the Go SDK (like Terraform) [don't automatically use your `.aws/config` file](https://docs.aws.amazon.com/sdk-for-go/v1/developer-guide/configuring-sdk.html).


4. Streamline the process. If you've got one main Identity Center configuration, set up your `.bashrc` (or similar) like this:
```
export AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL=https://something.awsapps.com/start
export AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION=us-east-2
```

Use `aws-sso-util configure profile` to set up your Identity Center profiles (see the full docs [here](configure.md)).
This will set up your profile as shown above interactively, including prompting you to select from available accounts and roles.
It will look something like this:
```
$ aws-sso-util configure profile my-sso-profile
SSO start URL [https://something.awsapps.com/start]:
SSO Region [us-east-2]:
Attempting to automatically open the SSO authorization page in your default browser.
If the browser does not open or you wish to use a different device to authorize this request, open the following URL:

https://device.sso.us-east-2.amazonaws.com/

Then enter the code:

ABCD-WXYZ
There are N AWS accounts available to you.
Using the account ID 123456789012
The only role available to you is: MyLeastPrivilegeRole
Using the role name "MyLeastPrivilegeRole"
CLI default client Region [None]: us-east-2
CLI default output format [None]: yaml

To use this profile, specify the profile name using --profile, as shown:

aws s3 ls --profile my-sso-profile
```

## Configuration

The `--profile` parameter on `aws-sso-util credential-process` doesn't work like the same parameter on the AWS CLI, and cannot be set from the environment; it's intended only to help make the `credential_process` entry in a profile more concise.

### Debugging
Setting the `--debug` flag or the env var `AWS_SSO_CREDENTIAL_PROCESS_DEBUG=true` will cause debug output to be sent to `.aws/sso/aws-sso-util credential-process-log.txt`. Note that this file will contain your credentials, though these credentials are both short-lived and also cached within the same directory.

### Identity Center Start URL

* `.aws/config`: `sso_start_url`
* env var: `AWS_SSO_START_URL`
* parameter: `--sso-start-url`

### Identity Center Region

* `.aws/config`: `sso_region`
* env var: `AWS_SSO_REGION`
* parameter: `--sso-region`

### Account

* `.aws/config`: `sso_account_id`
* env var: `AWS_SSO_ACCOUNT_ID`
* parameter: `--account-id`

### Role

* `.aws/config`: `sso_role_name`
* env var: `AWS_SSO_ROLE_NAME`
* parameter: `--role-name`
