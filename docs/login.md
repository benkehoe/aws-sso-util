# `aws-sso-util login` and `aws-sso-util logout`

A problem with [`aws sso login`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/sso/login.html) is that it's required to operate on a profile, that is, you have to tell it to log in to AWS SSO *plus some account and role.*
But the whole point of AWS SSO is that you log in once for *many* accounts and roles.
You could have a particular account and role set up in your default profile, but I prefer not to have a default profile so that I'm always explicitly selecting a profile and never accidentally end up in the default by mistake.
`aws-sso-util login` solves this problem by letting you log in to *AWS SSO.*

## AWS SSO instances
To login, an AWS SSO instance must be specified.
This consists of a start URL and the region the AWS SSO instance is in (which is separate from whatever region you might be accessing).
However, `aws-sso-util configure` tries to be smart about finding this value.

If you've got only one AWS SSO instance in your `~/.aws/config`, you can just do `aws-sso-util login` and it will just work.
You should consider setting the environment variables `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION` in your environment (e.g., your `.bashrc` or `.profile`), which will make it explicit.

If you've got multiple SSO instances configured, you've got to tell `aws-sso-util login` which one to choose, or use `--all` or set `AWS_SSO_LOGIN_ALL=true` to log in to them all.

`aws-sso-util login` uses the following algorithm to determine these values:
1. Except for `aws-sso-util configure profile`, if you provide a profile name with `--profile`, this profile will be checked for the fields `sso_start_url` and `sso_region`. It fails if they are not found.
2. The start URL and regions are looked for in the following CLI parameters and environment variables, stopping if either are found:
    1. The arguments from `aws-sso-util login [[sso_start_url] sso_region]`
    2. `AWS_LOGIN_SSO_DEFAULT_SSO_START_URL` and `AWS_LOGIN_DEFAULT_SSO_REGION`
    3. `AWS_DEFAULT_SSO_START_URL` and `AWS_DEFAULT_SSO_REGION`
3. If both the start URL and region are found, and the start URL is a full URL beginning wth `http`, these values are used.
4. If not, all the profiles containing AWS SSO config are loaded. All AWS SSO instances found in the config are then filtered:
    * If a start URL was found in step 2 and it begins with `http`, it will ignore all other instances.
    * If a start URL was found in step 2 and it does not begin with `http`, it is treated as a regex pattern that instance start URLs must match.
    * If a region was found in step 2, instances must match this region.
5. The resulting filtered list of instances must contain exactly one entry, unless `--all` is set or `AWS_SSO_LOGIN_ALL=true`.

In general: if you've got multiple AWS SSO instances you're using, you should set the environment variables listed above with your most-used instance, and then use a substring with `--sso-start-url`/`-u` to select among them.

For example, if you're using `https://foo.awsapps.com/start` (region `us-east-2`) and `https://bar.awsapps.com/start` (`ap-northeast-1`), and the first is your more used one, you'd set:
```
AWS_DEFAULT_SSO_START_URL=https://foo.awsapps.com/start
AWS_DEFAULT_SSO_REGION=us-east-2
```
and you'd login for that with `aws-sso-util login`
and for the other with `aws-sso-util login bar`

If you're finding that it's not correctly selecting the right instance, you can see the details with `--verbose`.

## Other options

Use `--force` to ignore any cached tokens.

On headless systems, the attempt to pop up the browser will silently fail and the always-printed fallback message with the URL and code can be used.
If you are on a system with a browser but you do not want the automatic pop up, use `--headless` or set the environment variable `AWS_SSO_DISABLE_BROWSER` to `1` or `true`.
