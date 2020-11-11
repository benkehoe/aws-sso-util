# aws-sso-util configure

`aws-sso-util configure` has two subcommands, `aws-sso-util configure profile` for configuring a single profile, and `aws-sso-util configure populate` to add _all_ your permissions as profiles, in whatever region(s) you want (with highly configurable profile names).

You probably want to set the environment variables `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION`, which will inform these commands of your start url and SSO region (that is, the region that you've configured AWS SSO in), so that you don't have to pass them in as parameters every time.

`aws-sso-util configure profile` takes a profile name and prompts you with the accounts and roles you have access to, to configure that profile.

`aws-sso-util configure populate` takes one or more regions, and generates a profile for each account+role+region combination.
The profile names are completely customizable.

# aws-sso-util configure profile

`aws-sso-util configure profile` allows you to configure a single profile for use with AWS SSO interactively, including prompting you to select from available accounts and roles.
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

This tool wraps the AWS CLI v2's `aws configure sso` command, to provide auto-population of the start URL and SSO region based on the environment variables listed above, and automatically inserts the `credential_process` entry to enable support for SDK (see [the docs for `aws-sso-util credential-process` for more details](credential-process.md)).

# aws-sso-util configure populate

`aws-sso-util configure populate` allows you to configure profiles for all the access you have through AWS SSO.
You specify one or more regions, and a profile is created for every account, role, and region you have access to through AWS SSO (note that if access to a region is prohibited by an IAM policy, this does not suppress creation of the profile).

You can provide regions through the `--region`/`-r` flag (multiple regions like `-r REGION1 -r REGION2`), or by setting the `AWS_CONFIGURE_DEFAULT_REGION` environment variable (this is ignored if any regions are specified on the command line).

You can view the profiles without writing them using the `--dry-run` flag.

## Config entries

You can provide additional entries to include in each profile with the `--config-default`/`-d` parameter.
You can provide multiple entries, each of the form `--config-default key=value`, e.g. `-d output=yaml`

These defaults will not overwrite any existing values you have put in your config file.
To change this, use the `--existing-config-action` parameter.
There are three options:
* `keep` (the default): for each profile, keep all entries that are specifically set by `aws-sso-util configure populate`, but add provided default entries that don't conflict
* `overwrite`: for each profile, provided default entries will overwrite existing entries
* `discard`: for each profile, all existing entries will be discarded

## Profile names
The generated profile names are highly configurable.

By default, the profile name is `{account_name}_{role_name}` for the first region given, and `{account_name}_{region_name}_{short_region}` for additional regions.
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
The values are joined with `_` by default, which can be changed with `--separator`.

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

### Profile name

Finally, if you want total control over the generated profile names, you can provide a shell command with `--profile-name-process` and it will be executed with the following positional arguments:
* Account name
* Account id
* Role name
* Region name
* Short region name (see above)
* Region index (zero-based index of what position the region is in the provided list of regions)

This must output a profile name to stdout and return an exit code of 0.
