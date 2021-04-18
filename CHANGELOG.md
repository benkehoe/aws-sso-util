# Changelog

* [`aws-sso-util`](#aws-sso-util)
* [`aws-sso-lib`](#aws-sso-lib)

## `aws-sso-util`

### v4.24

* Add [`aws-sso-util check`](docs/check.md) command
* `aws-sso-util configure populate`: Added `num_regions` for process formatter
* Increased `aws_sso_lib` logging with `--verbose`
* Fixed instance-finding exceptions
* Renamed some env var variable names

### v4.23

* Fix default session duration extraction
* Fix processing templates with no assignment groups
* Fix name fetching error with `!Ref` principal or target

## `aws-sso-lib`

### v1.7

* Write AWS SSO token expiration in correct ISO format
* Added configurable token expiry window to login()
* Bug fix and better logging for instance-finding
