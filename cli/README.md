# aws-sso-util
## Making life with AWS SSO a little easier

[AWS SSO](https://aws.amazon.com/single-sign-on/) has some rough edges, and `aws-sso-util` is here to smooth them out, hopefully temporarily until AWS makes it better.

`aws-sso-util` contains utilities for the following:
* Configuring `.aws/config`
* Logging in/out
* AWS SDK support
* Looking up identifiers
* CloudFormation

The underlying Python library for AWS SSO authentication is [`aws-sso-lib`](https://pypi.org/project/aws-sso-lib/), which has useful functions like interactive login, creating a boto3 session for specific a account and role, and the programmatic versions of the `lookup` functions in `aws-sso-util`.

`aws-sso-util` supersedes `aws-sso-credential-process`, which is still available in its original form [here](https://github.com/benkehoe/aws-sso-credential-process).
Read the updated docs for `aws-sso-util credential-process` [here](docs/credential-process.md).

## Quickstart

1. I recommend you install [`pipx`](https://pipxproject.github.io/pipx/), which installs the tool in an isolated virtualenv while linking the script you need.

Mac [and Linux](https://docs.brew.sh/Homebrew-on-Linux):
```bash
brew install pipx
pipx ensurepath
```

Other:
```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

2. Install
```bash
pipx install aws-sso-util
```

3. Learn
```bash
aws-sso-util --help
```

## Documentation

See the full docs at [https://github.com/benkehoe/aws-sso-util](https://github.com/benkehoe/aws-sso-util)
