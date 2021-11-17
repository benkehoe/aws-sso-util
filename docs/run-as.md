# `aws-sso-util run-as`
Sometimes, you want to invoke a particular command with a particular account and role, without needing a profile configured for it—or without knowing the profile name corresponding to the account and role.
`aws-sso-util run-as` serves this purpose.

An example is sending a command for a colleague to run from their machine.
Another example is a shell script that knows what account and role it should be using—a python script would use [`aws_sso_lib.get_boto3_session()`](../lib/README.md#get_boto3_session) for this purpose.
If the script can be used with any credentials, it should assume the environment it runs in is configured appropriately (e.g., the user may have set the `AWS_PROFILE` environment variable).

`aws-sso-util run-as` is **not** intended to serve as a mechanism to "set" the account and role for a shell environment.
In general, in the AWS SSO world, you shouldn't be trying to manually set credentials in an environment, nor thinking about "logging in" to a particular account and role.
You log in to *AWS SSO* once, and then *use* accounts and roles with that session.
You should orient yourself around configuration profiles—use [`aws-sso-util configure populate`](configure.md) to set up profiles for every account and role you have access to, and then use either the `--profile` argument to tell a command to use a specific profile, or set the `AWS_PROFILE` environment variable to have all commands your shell use a particular profile unless they are told otherwise ([here's a shell function to help manage that env var](https://gist.github.com/benkehoe/0d2985e56059437e489314d021be3fbe)).

`aws-sso-util run-as` is **not** intended to serve as a mechanism for exporting credentials for tools that do not support AWS SSO configuration.
`aws-sso-util configure` already mitigates this by [adding a credential process added to profiles](https://github.com/benkehoe/aws-sso-util/blob/master/README.md#adding-aws-sso-support-to-aws-sdks), which enables AWS SSO support for SDKs that support credential processes.
Some tools, notably those based on the AWS JavaScript v2 SDK, don't support the credential process.
For those, the standalone tool [`aws-export-credentials`](https://github.com/benkehoe/aws-export-credentials) is recommended instead.

# Usage
```bash
aws-sso-util --sso-start-url https://example.awsapps.com/start --sso-region us-east-2 \
    --account 123456789012 --role-name Developer --region us-west-2 \
    aws sts get-caller-identity --output yaml
```
will output something like
```
Account: '123456789012'
Arn: arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_Developer_112334bd274cc856/me@example.com
UserId: AROA1XAALGJDBETAD7DKW:me@example.com
```

## Multiple commands

If you're running multiple commands with the same configuration, instead of using `aws-sso-util run-as` on each one individually (or trying to get them all to run in, say, a subshell), you can use a temporary AWS config file.
The AWS CLI and SDKs use a *default* location of `~/.aws/config` for the configuration file, but this can be set with the `AWS_CONFIG_FILE` environment variable.
`aws-sso-util configure profile` also respects the `AWS_CONFIG_FILE` environment variable, providing a way to write configuration to an arbitrary file.
The following pattern uses a config file in `/tmp`, which it cleans up at the end.


```bash
# make sure no profile is set first
export -n AWS_PROFILE= AWS_DEFAULT_PROFILE=

export AWS_CONFIG_FILE=$(mktemp --suffix .aws-config)
aws-sso-util configure profile default --sso-start-url https://example.awsapps.com/start --sso-region us-east-2 \
    --account 123456789012 --role-name Developer --region us-west-2

aws sts get-caller-identity
aws s3 cp s3://some-bucket/some-key ./my-file

rm -f $AWS_CONFIG_FILE
export -n AWS_CONFIG_FILE=
```

Note that `aws-sso-util configure profile` is configuring the `default` profile in the example above, so the subsequent commands don't need to use the `--profile` argument.
If you need to use multiple configurations in the same script, you can make multiple calls to `aws-sso-util configure profile` using different profile names to put those configurations in the same temporary configuration file, which you then use in subsequent commands by using the `--profile` argument (if it's available) or the `AWS_PROFILE` environment variable.

There's nothing special about `aws-sso-util configure profile` in this example; you could write the raw configuration directly, for example using a [heredoc](https://tldp.org/LDP/abs/html/here-docs.html).
This works for both AWS SSO and [other configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html#cli-configure-files-settings); however, you should never embed credentials directly in a script.

# Arguments

## AWS SSO instance

To explicitly set the AWS SSO instance, use `--sso-start-url` and `--sso-region`.
If you're using `aws-sso-util run-as`, you're probably in a situation where you shouldn't assume anything about the configuration of the system it's running on.

However, because it uses the same instance resolution procedure as other commands, if both values are not provided explicitly, there is a search for the AWS SSO instance.
Here are the details of of how the instance is determined:
1. The start URL and regions are looked for in the following CLI parameters and environment variables, stopping if either are found:
    1. `--sso-start-url` and `--sso-region`
    2. `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`
2. If both the start URL and region are found, and the start URL is a full URL beginning wth `http`, these values are used.
3. If not, all the profiles containing AWS SSO config are loaded. All AWS SSO instances found in the config are then filtered:
    * If a start URL was found in step 1 and it begins with `http`, it will ignore all other instances.
    * If a start URL was found in step 1 and it does not begin with `http`, it is treated as a regex pattern that instance start URLs must match.
    * If a region was found in step 1, instances must match this region.
4. The resulting filtered list of instances must contain exactly one entry.

## Required

* `--account`: The AWS account.
* `--role-name`: The SSO role (also the Permission Set name) to assume in account.

## Optional

* `--region`: The AWS region. **NOTE:** this may be required by the operation being performed.
* `--force-refresh`: Force a new log-in.
