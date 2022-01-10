# Changelog

* [`aws-sso-util`](#aws-sso-util)
* [`aws-sso-lib`](#aws-sso-lib)

## `aws-sso-util`

### CLI v4.26
* Add `aws-sso-util run-as` command (#44). Read the docs [here](docs/run-as.md).
* Add `aws-sso-util console` commands (#47). Read the docs [here](docs/console.md).
* Better debugging of token issues in `aws-sso-util check` (#45).
    * Note that the token is checked by default, which is a slight backwards-incompatible change if you were relying on a success return code to check specifically if the instance was configured correctly; for this situation, use `--skip-token-check`.
* Ignore `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` environment variables for commands that don't use them (#41).
* Standardize account option as `--account-id` across commands (with backwards compatibility).
* Include component names in `aws-sso-util configure populate` help (#33).
* Fix `aws-sso-util login --all` when environment variables are set.

### CLI v4.25
* Fix macro not recognizing all intrinsic functions
* Fix profile names in `aws-sso-util configure populate` to remove square brackets per [#31](https://github.com/benkehoe/aws-sso-util/issues/31)

### CLI v4.24

* Add [`aws-sso-util check`](docs/check.md) command
* `aws-sso-util configure populate`: Added `num_regions` for process formatter
* Increased `aws_sso_lib` logging with `--verbose`
* Fixed instance-finding exceptions
* Renamed some env var variable names

### CLI v4.23

* Fix default session duration extraction
* Fix processing templates with no assignment groups
* Fix name fetching error with `!Ref` principal or target

## `aws-sso-lib`

### lib v1.9
* `get_boto3_session()` now ignores `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` environment variables.
* Add `find_all_instances()` function to `config` package.
* Update `botocore` dependency for `JSONFileCache.__delitem__` support (#46).
* Fix `logout()` return values to match docs.

### lib v1.8
* Add `expiry_window` to `login()`
* Add `user_auth_handler` to `login()` per [#25](https://github.com/benkehoe/aws-sso-util/pull/25)

### lib v1.7

* Write AWS SSO token expiration in correct ISO format
* Added configurable token expiry window to login()
* Bug fix and better logging for instance-finding
