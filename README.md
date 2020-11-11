# aws-sso-util
## Making life with AWS SSO a little easier

[AWS SSO](https://aws.amazon.com/single-sign-on/) has some rough edges, and `aws-sso-util` is here to smooth them out, hopefully temporarily until AWS makes it better.

`aws-sso-util` contains utilities for the following:
* Configuring `.aws/config`
* AWS SDK support
* Looking up identifiers
* CloudFormation
* Python library for AWS SSO authentication

## Quickstart

0. Make sure you've got the AWS CLI v2 (which has AWS SSO support).

1. I recommend you install [`pipx`](https://pipxproject.github.io/pipx/), which installs the tool in an isolated virtualenv while linking the script you need.

Mac:
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

4. Autocomplete
```bash
```

## Configuring `.aws/config`

Read the full docs for `aws-sso-util configure` [here](docs/configure.md).

`aws-sso-util configure` has two subcommands, `aws-sso-util configure profile` for configuring a single profile, and `aws-sso-util configure populate` to add _all_ your permissions as profiles, in whatever region(s) you want (with highly configurable profile names).

You probably want to set the environment variables `AWS_CONFIGURE_SSO_DEFAULT_SSO_START_URL` and `AWS_CONFIGURE_SSO_DEFAULT_SSO_REGION`, which will inform these commands of your start url and SSO region (that is, the region that you've configured AWS SSO in), so that you don't have to pass them in as parameters every time.

`aws-sso-util configure profile` takes a profile name and prompts you with the accounts and roles you have access to, to configure that profile.

`aws-sso-util configure populate` takes one or more regions, and generates a profile for each account+role+region combination.
The profile names are completely customizable.

## Adding AWS SSO support to AWS SDKs

Read the full docs for `aws-sso-util credential-process` [here](docs/credential-process.md).

Not all AWS SDKs have support for AWS SSO (which will change eventually).
However, they all have support for `credential_process`, which allows an external process to provide credentials.
`aws-sso-util credential-process` uses this to allow these SDKs to get credentials from AWS SSO.
It's added automatically (by default) by the `aws-sso-util configure` commands.

## Looking up identifiers

Read the full docs for `aws-sso-util lookup` and `aws-sso-util assignments` [here](docs/lookup.md).

When you're creating assignments through the API or CloudFormation, you're required to use identifiers like the instance ARN, the principal ID, etc.
These identifiers aren't readily available through the console, and the principal IDs are not the IDs you're familiar with.
`aws-sso-util lookup` allows you to get these identifers, even en masse.

There is no simple API for retrieving all assignments or even a decent subset.
The current best you can do is [list all the users with a particular PermissionSet on a particular account](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListAccountAssignments.html).
`aws-sso-util assigments` takes the effort out of looping over the necessary APIs.

## CloudFormation support

You'll want to read the full docs [here](docs/cloudformation.md).

AWS SSO's CloudFormation support currently only includes [`AWS::SSO::Assignment`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sso-assignment.html), which means for every combination of principal (group or user), permission set, and target (AWS account), you need a separate CloudFormation resource.
Additionally, AWS SSO does not support OUs as targets, so you need to specify every account separately.

Obviously, this gets verbose, and even an organization of moderate size is likely to have tens of thousands of assignments.
`aws-sso-util cfn` provides two mechanisms to make this concise.

I look forward to discarding this part of the tool once there are two prerequisites:
1. OUs as targets for assignments
2. An `AWS::SSO::AssignmentGroup` resource that allows specifications of multiple principals, permission sets, and targets, and performs the combinatorics directly.

### CloudFormation Macro
`aws-sso-util` defines a resource format for an AssignmentGroup that is a combination of multiple principals, permission sets, and targets, and provides a CloudFormation Macro you can deploy that lets you use this resource in your templates.

### Client-side generation

I am against client-side generation of CloudFormation templates, but if you don't want to trust this 3rd party macro, you can generate the CloudFormation templates directly.

`aws-sso-util cfn` takes one or more input files, and for each input file, generates a CloudFormation template and potentially one or more child templates.
These templates can then be packaged and uploaded using [`sam`](), for example.

The input files can either be templates using the Macro (using the `--macro` flag), or somewhat simpler configuration files using a different syntax.
These configuration files can define permission sets inline, have references that turn into template parameters, and you can provide a base template that the resulting resources are layered on top of.
