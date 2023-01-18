# `aws-sso-util check`

`aws-sso-util check` helps in debugging issues with `aws-sso-util` and Identity Center.
It can help you validate where the Identity Center instance configuration is (or isn't) getting picked up.
It can help you validate whether or not you have access to a specific account and/or role.

## Quiet mode

For use in shell scripts, the `--quiet`/`-q` flag can be specified, which will suppress all output, allowing for shell script conditionals to check the return code.

## Identity Center instance configuration check

To use `aws-sso-util` commands (not including `aws-sso-util admin` commands), an Identity Center instance must be specified.
`aws-sso-util check` always determines if a valid instance is configured.

### Overview

The Identity Center instance consists of a start URL and the region the Identity Center instance is in (which is separate from whatever region you might be accessing).
However, `aws-sso-util` tries to be smart about finding this value.

If you're working with a single Identity Center instance, and you've already got a profile configured for it, it should just work.
You should consider setting the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION` in your environment (e.g., your `.bashrc` or `.profile`), which will make it explicit.

`aws-sso-util check` uses the following algorithm to determine these values:
1. The start URL and regions are looked for in the following CLI parameters and environment variables, stopping if either are found:
    1. `--sso-start-url`/`-u` and `--sso-region`
    2. If `--command` is specified and is not set to `default`:
        * If `--command` is `configure`: `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_DEFAULT_SSO_REGION`
        * If `--command` is `login`: `AWS_LOGIN_SSO_DEFAULT_SSO_START_URL` and `AWS_LOGIN_DEFAULT_SSO_REGION`
    3. `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`
2. If both the start URL and region are found, and the start URL is a full URL beginning wth `http`, these values are used.
3. If not, all the profiles containing Identity Center config are loaded. All Identity Center instances found in the config are then filtered:
    * If a start URL was found in step 1 and it begins with `http`, it will ignore all other instances.
    * If a start URL was found in step 1 and it does not begin with `http`, it is treated as a regex pattern that instance start URLs must match.
    * If a region was found in step 1, instances must match this region.
4. The resulting filtered list of instances must contain exactly one entry.

### Instance check
If `aws-sso-util check` cannot find a unique Identity Center instance, it will return an error and a description of what it did find.

* If no Identity Center instances were found at all, it will print that and exit with return code 101.
* If at least one Identity Center instance was found, but the specifier filtered all of them, it will print the specifier and the entire set of instances, and exit with return code 102.
* If no unique Identity Center intance was found, either because no specifier was found or because the specifier matched more than one of them, it will print all matched instances, the specifier, and the entire set of instances, and exit with return code 103.

If `aws-sso-util check` finds a unique instance, and neither `--account-id` nor `--role-name` are given, it will print the details of the instance, the specifier, and the entire set of instances, and exit with return code 0 (success).
To print out these details when also checking access to an account and/or role, use the `--instance-details` flag.

If you provide the flag `-vvv` (which turns the logging level of `aws_sso_lib` to `DEBUG`), the details of the Identity Center instance collection and filtering process will be printed.

## Identity Center token check

`aws-sso-util check` attempts to load the user's Identity Center token.
If `--force-refresh` is provided, it goes through the login process.
Otherwise, it attempts to load the cached token.
Either way, on successful retrieval of the token, the expiration is printed; on failure, it will exit with code 201.
To skip this step when not checking access to an account or role (which requires the token anyway), use the `--skip-token-check` flag.

`aws-sso-util check` attempts to identify common problems with cached tokens, including permissions errors.

## Identity Center access check

`aws-sso-util` can check if the user has access to a particular account and/or role using the `--account-id` and `--role-name` options.

If only `--account-id` is given, `aws-sso-util check` will find if any roles are accessible in that account, and print them out.
If no roles are accessible in that account, it will print an error and exit with return code 202.

If only `--role-name` is given, `aws-sso-util check` will find if there are any accounts where that role is accessible, and print them out.
If the role is not accessible in any account, it will print an error and exit with return code 203.

If both `--account-id` and `--role-name` are given, `aws-sso-util check` will find if the role is accessible in that account, and print out a success message.
If no roles are accessible in the account, it will print an error and exit with return code 202.
If there are roles accessible in the account, but the given role is not accessible in the account, it will exit with return code 204.

If the access is found, it will exit with return code 0 (success).

## Checking a config profile

To check access for a specific profile in `~/.aws/config` (or a custom config file specified with the `AWS_CONFIG_FILE` environment variable), use the `--check-profile` option.
The profile must have the `sso_start_url`, `sso_region`, `sso_account_id`, and `sso_role_name` fields.
You cannot use `--sso-start-url`/`-u`, `--sso-region`, `--account-id`/`-a`, and `--role-name`/`-r` when using `--check-profile`.
