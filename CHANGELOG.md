# Changelog

* [`aws-sso-util`](#aws-sso-util)
* [`aws-sso-lib`](#aws-sso-lib)

## `aws-sso-util`

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

### lib v1.8
* Add `expiry_window` to `login()`
* Add `user_auth_handler` to `login()` per [#25](https://github.com/benkehoe/aws-sso-util/pull/25)

### lib v1.7

* Write AWS SSO token expiration in correct ISO format
* Added configurable token expiry window to login()
* Bug fix and better logging for instance-finding
