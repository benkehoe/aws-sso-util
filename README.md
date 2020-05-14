# aws-sso-credential-process
**Get AWS SSO working with all the SDKs that don't understand it yet**

Currently, [AWS SSO](https://aws.amazon.com/single-sign-on/) support is implemented in the [AWS CLI v2](https://aws.amazon.com/blogs/developer/aws-cli-v2-is-now-generally-available/), but the capability to usage the credentials retrieved from AWS SSO by the CLI v2 has not been implemented in the various AWS SDKs. However, they all support the [credential process](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html) system. This tool bridges the gap by implementing a credential process provider that understands the SSO credential retrieval and caching system. Once AWS implements the necessary support in the SDK for your favorite language, this tool will no longer be necessary.

If you try this and your tools still don't work with the credentials, you can get the credentials themselves using [aws-export-credentials](https://github.com/benkehoe/aws-export-credentials), which can also inject them as environment variables for your program.

## Quickstart

1. I recommend you install [`pipx`](https://pipxproject.github.io/pipx/), which installs the tool in an isolated virtualenv while linking the script you need.

Mac:
```bash
brew install pipx
pipx ensurepath
```

Other:
```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

2. Install the tool.
```bash
pipx install aws-sso-credential-process
```

3. Set up your `.aws/config` file for AWS SSO as normal (you can use `aws configure sso --profile my-sso-profile` to do this as well):

```
[profile my-sso-profile]

region = us-east-2
output = yaml

sso_start_url = https://something.awsapps.com/start
sso_region = us-east-2
sso_account_id = 123456789012
sso_role_name = MyLeastPrivilegeRole
```

4. Then, just add a [`credential_process` entry](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html) to the profile, using the `--profile` flag with the same profile name:

```
[profile my-sso-profile]

credential_process = aws-sso-credential-process --profile my-sso-profile

region = us-east-2
output = yaml

sso_start_url = https://something.awsapps.com/start
sso_region = us-east-2
sso_account_id = 123456789012
sso_role_name = MyLeastPrivilegeRole

```

5. You're done! Test it out:
```bash
aws sso login --profile my-sso-profile
python -c "import boto3; print(boto3.Session(profile_name='my-sso-profile').client('sts').get_caller_identity())"
```

## Configuration

The order of configuration matches the AWS CLI and SDKs: values from CLI parameters take precedence, followed by env vars, followed by settings in `.aws/config`.

The `--profile` parameter doesn't work like the same parameter on the AWS CLI, and cannot be set from the environment; it's intended only to help make the `credential_process` entry in a profile more concise.

The `aws-configure-sso-profile` tool wraps `aws configure sso` to help you set up profiles in `.aws/config`; you can set the environment variables `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION` to set defaults for those values so you're not typing them all the time. The tool will set up the `credential_process` entry as well. Note that `--profile` is required (unlike `aws configure sso`).

### Interactive authentication

The most important thing to determine is whether or not you want to allow interactive authentication, which is off by default (so that the behavior is the same as the AWS CLI v2).

When interactive authentication is off, you need to use the CLI v2's `aws sso login` to login through AWS SSO. If you haven't logged in or your session has expired, the process will fail and interrupt whatever you're doing.

With interactive authentication turned on, the functionality of `aws sso login` will be triggered automatically; a browser will pop up to prompt you to log in (or, if you're already logged in, it will prompt you to approve the login). This is useful when you're running scripts interactively, but bad for automated processes that are incapable of logging in.

**To enable interactive authentication, the best way is to set `AWS_SSO_INTERACTIVE_AUTH=true` in your environment.** This lets you control whether interactive auth is enabled for a given profile depending on the situation you're using it for. Otherwise, you can set `sso_interactive_auth=true` in your profile in `.aws/config`, or use the `--interactive` flag for the process. Note that you can use the `--noninteractive` flag to disable interactive auth even if the environment variable is set.

Note that if you've got your profile set up as shown above, the AWS CLI v2 won't get interactive authentication, because it will natively use the profile configuration, skipping this tool as a credential process. If you really want interactive auth with the CLI, you can put the AWS SSO configuration information as parameters to the tool in the credential process directive, instead of directly in the profile, and then the CLI will use credential process as well.

### Debugging
Setting the `--debug` flag or the env var `AWS_SSO_CREDENTIAL_PROCESS_DEBUG=true` will cause debug output to be sent to `.aws/sso/aws-sso-credential-process-log.txt`. Note that this file will contain your credentials, though these credentials are both short-lived and also cached within the same directory.

### Account

* `.aws/config`: `sso_account_id`
* env var: `AWS_SSO_ACCOUNT_ID`
* parameter: `--account-id`

### Role

* `.aws/config`: `sso_role_name`
* env var: `AWS_SSO_ROLE_NAME`
* parameter: `--role-name`

### SSO Start URL

* `.aws/config`: `sso_start_url`
* env var: `AWS_SSO_START_URL`
* parameter: `--start-url`

### SSO Region

* `.aws/config`: `sso_region`
* env var: `AWS_SSO_REGION`
* parameter: `--region`
