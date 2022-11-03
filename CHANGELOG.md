# Changelog

`aws-sso-util` and `aws-sso-lib` use [monotonic versioning](blog.appliedcompscilab.com/monotonic_versioning_manifesto/).

* [`aws-sso-util`](#aws-sso-util)
* [`aws-sso-lib`](#aws-sso-lib)

## `aws-sso-util`

### CLI v4.30
* `aws-sso-util login` adds `receivedAt` time to token cache entry.
* Improved `aws-sso-util check` feedback.
    * Displays `receivedAt` time for token if present.
    * Validates apparently-valid cached token by attempting to list one page of available accounts.
* Add `--check-profile` option to `aws-sso-util check` for pulling configuration from a profile.

### CLI v4.29
* Remove support for Python 3.6 (removed in `boto3`).
* Fix `aws-sso-credential-process` for `botocore` change.

### CLI v4.28
* Log normal output to stdout ([#54](https://github.com/benkehoe/aws-sso-util/issues/54)).
* Fix short region names for GovCloud in `aws-sso-util configure populate` and `aws-sso-util configure profile` ([#55](https://github.com/benkehoe/aws-sso-util/issues/55)).
* Update `aws-sso-util login` to use `--force-refresh` for consistency with other commands (`--force` still works).
* `aws-sso-util check` now provides more information about the token cache.

### CLI v4.27
* Added `--account-name-case` and `--role-name-case` to `aws-sso-util configure populate` ([#48](https://github.com/benkehoe/aws-sso-util/pull/48)).
* `aws-sso-util check` logs version and timestamp information.
* Fixed bug in `aws-sso-util configure profile` with Python 3.6

### CLI v4.26
* Add `aws-sso-util run-as` command ([#44](https://github.com/benkehoe/aws-sso-util/pull/44)). Read the docs [here](docs/run-as.md).
* Add `aws-sso-util console` commands ([#47](https://github.com/benkehoe/aws-sso-util/pull/47)). Read the docs [here](docs/console.md).
* Better debugging of token issues in `aws-sso-util check` ([#45](https://github.com/benkehoe/aws-sso-util/pull/45)).
    * Note that the token is checked by default, which is a slight backwards-incompatible change if you were relying on a success return code to check specifically if the instance was configured correctly; for this situation, use `--skip-token-check`.
* Ignore `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` environment variables for commands that don't use them ([#41](https://github.com/benkehoe/aws-sso-util/issues/41)).
* Standardize account option as `--account-id` across commands (with backwards compatibility).
* Include component names in `aws-sso-util configure populate` help ([#33](https://github.com/benkehoe/aws-sso-util/issues/33)).
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

### lib v1.13
* `login()` adds `receivedAt` timestamp to token dict.

### lib v1.12
* Remove support for Python 3.6 (removed in `boto3`).
* Fix `get_credentials()` for `botocore` change.

### lib v1.11
* Improvements to `SSOTokenFetcher` to support better `aws-sso-util check` functionality.
* Fixed type annotations.

### lib v1.10
* `lookup_accounts_for_ou()` now caches calls to `organizations.DescribeOrganization`.

### lib v1.9
* `get_boto3_session()` now ignores `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` environment variables.
* Add `find_all_instances()` function to `config` package.
* Update `botocore` dependency for `JSONFileCache.__delitem__` support ([#46](https://github.com/benkehoe/aws-sso-util/issues/46)).
* Fix `logout()` return values to match docs.

### lib v1.8
* Add `expiry_window` to `login()`
* Add `user_auth_handler` to `login()` per [#25](https://github.com/benkehoe/aws-sso-util/pull/25)

### lib v1.7

* Write AWS SSO token expiration in correct ISO format
* Added configurable token expiry window to login()
* Bug fix and better logging for instance-finding
