# `aws-sso-util check`

`aws-sso-util check` helps in debugging issues with `aws-sso-util` and AWS SSO.
It can help you validate where the AWS SSO instance configuration is (or isn't) getting picked up.
It can help you validate whether or not you have access to a specific account and/or role.

## Quiet mode

For use in shell scripts, the `--quiet`/`-q` flag can be specified, which will suppress all output, allowing for shell script conditionals to check the return code.

## AWS SSO instance configuration

### Overview

To use `aws-sso-util` commands (not including `aws-sso-util admin` commands), an AWS SSO instance must be specified.

This consists of a start URL and the region the AWS SSO instance is in (which is separate from whatever region you might be accessing).
However, `aws-sso-util configure` tries to be smart about finding this value.

If you've only got one AWS SSO instance, and you've already got a profile configured for it, it should just work.
You should consider setting the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION` in your environment (e.g., your `.bashrc` or `.profile`), which will make it explicit.

`aws-sso-util configure` uses the following algorithm to determine these values:
1. The start URL and regions are looked for in the following CLI parameters and environment variables, stopping if either are found:
  1. `--sso-start-url`/`-u` and `--sso-region`
  2. If `--command` is specified and is not set to `default`:
    * If `--command` is `configure`: `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_DEFAULT_SSO_REGION`
    * If `--command` is `login`: `AWS_LOGIN_SSO_DEFAULT_SSO_START_URL` and `AWS_LOGIN_DEFAULT_SSO_REGION`
  3. `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`
2. If both the start URL and region are found, and the start URL is a full URL beginning wth `http`, these values are used.
3. If not, all the profiles containing AWS SSO config are loaded. All AWS SSO instances found in the config are then filtered:
  * If a start URL was found in step 2 and it begins with `http`, it will ignore all other instances.
  * If a start URL was found in step 2 and it does not begin with `http`, it is treated as a regex pattern that instance start URLs must match.
  * If a region was found in step 2, instances must match this region.
4. The resulting filtered list of instances must contain exactly one entry.

### Debugging
If `aws-sso-util check` cannot find a unique AWS SSO instance, it will return an error and a description of what it did find.

* If no AWS SSO instances were found at all, it will print that and exit with return code 101.
* If at least one AWS SSO instance was found, but the specifier filtered all of them, it will print the specifier and the entire set of instances, and exit with return code 102.
* If no unique AWS SSO intance was found, either because no specifier was found or because the specifier matched more than one of them, it will print all matched instances, the specifier, and the entire set of instances, and exit with return code 103.

If `aws-sso-util check` finds a unique instance, and neither `--account` nor `--role-name` are given, it will print the details of the instance, the specifier, and the entire set of instances, and exit with return code 0 (success).

If you provide the flag `-vvv` (which turns the logging level of `aws_sso_lib` to `DEBUG`), the details of the AWS SSO instance collection and filtering process will be printed.

## AWS SSO access

`aws-sso-util` can check if the user has access to a particular account and/or role.

If the above AWS SSO instance check passed, the instance is printed.

If a valid token cannot be found and the user cannot be logged in, it will print an error and exit with return code 201.
Otherwise, the expiration of the token is printed.

If only `--account` is given, `aws-sso-util check` will find if any roles are accessible in that account, and print them out.
If no roles are accessible in that account, it will print an error and exit with return code 202.

If only `--role-name` is given, `aws-sso-util check` will find if there are any accounts where that role is accessible, and print them out.
If the role is not accessible in any account, it will print an error and exit with return code 203.

If both `--account` and `--role-name` are given, `aws-sso-util check` will find if the role is accessible in that account, and print out a success message.
If no roles are accessible in the account, it will print an error and exit with return code 202.
If there are roles accessible in the account, but the given role is not accessible in the account, it will exit with return code 204.

If the access is found, it will exit with return code 0 (success).
