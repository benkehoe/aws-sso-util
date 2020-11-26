# `aws-sso-util configure` and `aws-sso-util roles`

You can view the roles you have available to you with `aws-sso-util roles`, which you can use to configure your profiles, but `aws-sso-util` also provides functionality to directly configure profiles for you.

`aws-sso-util configure` has two subcommands, `aws-sso-util configure profile` for configuring a single profile, and `aws-sso-util configure populate` to add _all_ your permissions as profiles, in whatever region(s) you want (with highly configurable profile names).

You probably want to set the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`, which will inform these commands of your start url and SSO region (that is, the region that you've configured AWS SSO in), so that you don't have to pass them in as parameters every time.

`aws-sso-util configure profile` takes a profile name and prompts you with the accounts and roles you have access to, to configure that profile.

`aws-sso-util configure populate` takes one or more regions, and generates a profile for each account+role+region combination.
The profile names are completely customizable.

# `aws-sso-util roles`

`aws-sso-util roles` prints out a table of the accounts and roles you have access to.
This table contains the following columns: account ID, account name, role name.

An AWS SSO instance must be specified when using `aws-sso-util roles`.
If you've only got one AWS SSO instance, and you've already got a profile configured for it, it should just work.
You should consider setting the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION` in your environment (e.g., your `.bashrc` or `.profile`), which will make it explicit.
Otherwise, see below for the full resolution algorithm.

`aws-sso-util roles` has the following options:
* `--account`/`-a`: either an explicit 12-digit account ID (which will speed up the process) or a patterns to match, either the account ID prefix or suffix, or a regex to match against the account name.
  * This option can be provided multiple times.
  * If explicit account IDs are provided, the account name will always be `UNKNOWN`.
* `--role-name`/`-r`: a regex to match against the role name
* `--separator`/`--sep`: the field separator.
  * If `--separator` is provided and not `--sort-by` (see below), the rows will be printed as they are received, rather than all at once at the end. This can be useful if you have access to a large number of accounts and roles.
* `--header`/`--no-header`: print a header row (default) or suppress it.
* `--sort-by`: sort the output (and order the columns) according to the specification. The input must be two comma-separated values:
  * `id` is the account ID.
  * `name` is the account name.
  * `role` is the role name.
  * The default used if `--separator` is not provided is `name,role`, that is, sort first by account name, then by role name.
* `--force-refresh`: log in again

# Common options

## AWS SSO instance
For both commands, an AWS SSO instance must be specified.
This consists of a start URL and the region the AWS SSO instance is in (which is separate from whatever region you might be accessing).
However, `aws-sso-util configure` tries to be smart about finding this value.

If you've only got one AWS SSO instance, and you've already got a profile configured for it, it should just work.
You should consider setting the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION` in your environment (e.g., your `.bashrc` or `.profile`), which will make it explicit.

`aws-sso-util configure` uses the following algorithm to determine these values:
1. The start URL and regions are looked for in the following CLI parameters and environment variables, stopping if either are found:
  1. `--sso-start-url`/`-u` and `--sso-region`
  2. `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_DEFAULT_SSO_REGION`
  3. `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`
2. If both the start URL and region are found, and the start URL is a full URL beginning wth `http`, these values are used.
3. If not, all the profiles containing AWS SSO config are loaded. All AWS SSO instances found in the config are then filtered:
  * If a start URL was found in step 2 and it begins with `http`, it will ignore all other instances.
  * If a start URL was found in step 2 and it does not begin with `http`, it is treated as a regex pattern that instance start URLs must match.
  * If a region was found in step 2, instances must match this region.
4. The resulting filtered list of instances must contain exactly one entry.

In general: if you've got multiple AWS SSO instances you're using, you should set the environment variables listed above with your most-used instance, and then use a substring with `--sso-start-url`/`-u` to select among them.

For example, if you're using `https://foo.awsapps.com/start` (region `us-east-2`) and `https://bar.awsapps.com/start` (`ap-northeast-1`), and the first is your more used one, you'd set:
```
AWS_DEFAULT_SSO_START_URL=https://foo.awsapps.com/start
AWS_DEFAULT_SSO_REGION=us-east-2
```
and you'd configure profiles for that with `aws-sso-util configure profile my-foo-profile`
and for the other with `aws-sso-util configure profile my-bar-profile --sso-start-url https://bar.awsapps.com/start --sso-region ap-northeast-1` the first time, and then `aws-sso-util configure profile my-other-bar-profile --sso-start-url bar` afterwards, as the region would get found from the `my-bar-profile` profile.

If you're finding that it's not correctly selecting the right instance, you can see the details with `--verbose`.

## Config fields
You can provide additional entries to include in profiles with the `--config-default`/`-c` parameter.
You can provide multiple entries, each of the form `--config-default key=value`, e.g. `-c output=yaml`

These defaults will not overwrite any existing values you have put in your config file.
To change this, use the `--existing-config-action` parameter.
There are three options:
* `keep` (the default): for each profile, don't add provided default entries when they conflict with a default
* `overwrite`: for each profile, provided default entries will overwrite existing entries
* `discard`: for each profile, all existing entries will be discarded

By default, a `credential_process` entry is created in profiles, see [the docs for `aws-sso-util credential-process`](credential-process.md) for details.
To disable this, set `--no-credential-process` or the environment variable `AWS_CONFIGURE_SSO_DISABLE_CREDENTIAL_PROCESS=true`.

# aws-sso-util configure profile

`aws-sso-util configure profile` allows you to configure a single profile for use with AWS SSO.
You can set all the options for a profile, or let it prompt you interactively to select from available accounts and roles.

A complete profile has the following required information, and you can set them with the listed parameters/environment variables:
* AWS SSO start URL
  * See above for how to set this
  * `--sso-start-url`
  * `AWS_CONFIGURE_DEFAULT_SSO_START_URL`
  * `AWS_DEFAULT_SSO_START_URL`
* AWS SSO region
  * `--sso-region`
  * `AWS_CONFIGURE_DEFAULT_SSO_REGION`
  * `AWS_DEFAULT_SSO_REGION`
* Account
  * `--account-id`/`-a`
* Role name
  * `--role-name`/`-r`
* Region
  * `--region`
  * `AWS_CONFIGURE_DEFAULT_REGION` environment variable
  * `AWS_DEFAULT_REGION`

You can additionally set the `output` field with `--output`/`-o`, and as mentioned above, you can provide additional fields with `--config-default`/`-c`.

If not all of the required fields are provided, the interactive prompts appear, unless the `--non-interactive` flag is set.
The interactive prompts come from the AWS CLI v2's `aws configure sso` command.
If you do not have the AWS CLI v2, you'll receive a message about installing it.
Get ahead of the game with [these installation instructions](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html).

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

# aws-sso-util configure populate

`aws-sso-util configure populate` allows you to configure profiles for all the access you have through AWS SSO.
You specify one or more regions, and a profile is created for every account, role, and region you have access to through AWS SSO (note that if access to a region is prohibited by an IAM policy, this does not suppress creation of the profile).

You can provide regions through the `--region`/`-r` flag (multiple regions like `-r REGION1 -r REGION2`), or by setting the `AWS_CONFIGURE_DEFAULT_REGION` environment variable (this is ignored if any regions are specified on the command line).

You can view the profiles without writing them using the `--dry-run` flag.

## Profile names
The generated profile names are highly configurable.

By default, the profile name is `{account_name}.{role_name}` for the first region given, and `{account_name}.{role_name}.{short_region}` for additional regions.
The "short region" is a five-character abbreviation of the region: the country code followed by either the first two letters of the location or the abbreviation for locations like "northwest" ("nw") followed by the number.
For example, this results in "usea1" for "us-east-1", "apne1" for "ap-northeast-1", and "cace1" for "ca-central-1".

### Components and separator
The default profile name is generated based a list of components.
The components are:
* `account_name`
* `account_id`
* `account_number` (an alias for `account_id`)
* `role_name`
* `region`
* `short_region` (as defined above)
* `default_style_region` (use the region style from `--region-style`, which is `short_region` by default)

You can provide a comma separated list of components to the `--components` parameter.
Any value that doesn't match the list above is included as a literal.
The values are joined with `.` by default, which can be changed with `--separator`.

Whether a region component (any of the three in the list) is included in the profile name is controlled by the `--include-region` parameter.
`--include-region default` (the default, obviously) only includes the region component if it is not the first region listed, on the basis that it is your most-used region and therefore you shouldn't have to explicitly specify it.
`--include-region always` will always include the region component.

The default region component is `default_style_region`, which uses the value of `--region-style`, which is `short` by default.
If you only want to change the profile names to use the long region, you can set `--region-style long` instead of having to set `--components` yourself.

### Trim account and role names

There are often boilerplate parts of account and role names.
To trim this out of your profile names, you can provide [Python regular expressions](https://docs.python.org/3/library/re.html#regular-expression-syntax) to `--trim-account-name` and `--trim-role-name`; matched substrings will be removed.
You can provide these parameters multiple times.

A useful piece of syntax for this is lookahead/lookbehind assertions.
* `(?<=Admin)Role` would turn `"AdminRole"` into `"Admin"` but leave `"UserRole"` and `"MyRole"` as is.
* `(?<!My)Role` would turn `"AdminRole"` into `"Admin"` and `"UserRole"` into `"User"` but leave `"MyRole"` as is.
* `RoleFor(?=Admin)` and `RoleFor(?!My)` work similarly for suffixes.

### Profile name process

Finally, if you want total control over the generated profile names, you can provide a shell command with `--profile-name-process` and it will be executed with the following positional arguments:
* Account name
* Account id
* Role name
* Region name
* Short region name (see above)
* Region index (zero-based index of what position the region is in the provided list of regions)

This must output a profile name to stdout and return an exit code of 0.

The default formatting is roughly equivalent to the following code:
```python
import sys
sep = "."
(
    account_name, account_id,
    role_name,
    region_name, short_region_name
) = sys.argv[1:6]
region_index = int(sys.argv[6])
region_str = "" if region_index == 0 else sep + short_region_name
print(account_name + sep + role_name + region_str)
```
If this was stored as `profile_formatter.py`, it could be used as `--profile-name-process "python profile_formatter.py"`
