# aws-sso-util CloudFormation support

`aws-sso-util` helps patch over the lack of support in Identity Center, and therefore in Identity Center's CloudFormation resources, for managing assignments as groups.

Identity Center's CloudFormation support currently only includes [`AWS::SSO::Assignment`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sso-assignment.html), which means for every combination of principal (group or user), permission set, and target (AWS account), you need a separate CloudFormation resource.
Additionally, Identity Center does not support OUs as targets, so you need to specify every account separately.

Obviously, this gets verbose, and even an organization of moderate size is likely to have tens of thousands of assignments.
`aws-sso-util` provides two mechanisms to make this concise, a [CloudFormation Macro](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-macros.html) for cloud-side processing, or client-side generation using `aws-sso-util admin cfn`.

[I look forward to discarding](https://faasandfurious.com/122) this part of the tool once there are two prerequisites:
1. OUs as targets for assignments
2. An `AWS::SSO::AssignmentGroup` resource that allows specifications of multiple principals, permission sets, and targets, and performs the combinatorics directly.

You can, however, use the client-side version to generate a CSV of the assignments that the template will generate, which can use useful for auditing the actual assignments (which you can get from `aws-sso-util assignments`, see the docs for that [here](lookup.md)).

## Output
With either method, the result is a template that either includes the assignments directly, or, if there are too many assignments to contain in a single stack, [nested stacks](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-nested-stacks.html) that contain the assignments (references are automatically wired through into the child stacks).

However, this is not done automatically.
The goal is to prevent any given assignment from being moved around between the parent and nested stack, or between nested stacks.
If an assignment is moved between stacks, there is the potential that one stack could attempt to create it before the other stack has deleted, creating a conflict that prevents the whole update from completing.

By default, no nested stacks will be created, and you'll be limited to creating as many assignments will fit in a single template.
If your configuration generates more assignments than that, the generator (either client-side or the Macro) will raise an error.

To allow for more assignments, you need to specify a number of child stacks.
You can either specify the number of child stacks explicitly, or provide the maximum number of assignment resources you want to support (which will calculate the number of child stacks automatically).
See below for how to configure this.

When specifying an OU for assignment the generated assignments will not include accounts with a status of `SUSPENDED` or `PENDING_CLOSURE`, these accounts can be explicitly listed.

Note that no assignments for the Organizations management account will be generated unless it is explicitly listed as an account target.
If an OU that contains the management account is given as a target, the generated assignments for that OU will not include the management account.

The assignment resources can contain the following metadata, in the `Metadata` section of the resource under the `SSO` key:
* If you are using the macro: The resource name of the `AssignmentGroup` resource, as well as the value of the `Name` property of the resource, if it exists and is a string.
* If you specified an OU as a target
    * The metadata for every assignment for an account from that OU will have the OU in the metadata in the `SourceOU` field.
    * The account name will be present under the `TargetName` field.
* If you enable name lookups, the principal and permission set names will be looked up and put in the `PrincipalName` and `PermissionSetName` fields, as will the account name (in `TargetName`) if it wasn't generated from an OU.
See below for how to enable this.

# CloudFormation Macro
`aws-sso-util` defines a resource format for an AssignmentGroup that is a combination of multiple principals, permission sets, and targets, and provides a CloudFormation Macro you can deploy that lets you use this resource in your templates.

## Deploy macro

This should be able to be a [SAR app](https://aws.amazon.com/serverless/serverlessrepo/), but until then, here is the manual process:

```bash
git clone https://github.com/benkehoe/aws-sso-util
cd aws-sso-util/macro
sam build --use-container
sam deploy --guided
```

The macro template has the following parameters (note that for the values that can be set in the `Metadata` section of the template, as noted below, the template values take precedence for that template's generation):
* `NumChildStacks` and `MaxAssignmentsAllocation`: set one of these (not both) to fix a default number of child stacks (can be overridden by setting metadata in the template, see below).
* `LookupNames`: if set to `true`, lookup the names for identifiers on assignments and include them in the resource metadata
* `DefaultSessionDuration`: an [ISO8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations) like `PT8H` to set on `AWS::SSO::PermissionSet` resources that don't already have it set.
* `ChildTemplatesInYaml`: if set to `true`, store nested stack templates in YAML format, otherwise default to JSON.
* `MaxConcurrentAssignments`: to keep assignment creation from being throttled, this is set to 20 as a default. You can change it with this parameter.
* `MaxResourcesPerTemplate`: just what it sounds like, defaults to the CloudFormation limit.
* `LogLevel`: set the logging level for the Macro
* `ArtifactS3KeyPrefix`: control the prefix for the artifacts put in the S3 bucket
* `S3PutObjectArgs`: set this to a JSON object to have more control over the child stack template objects that are put in S3.

## Use macro

The template must include `AWS-SSO-Util-2020-11-08` in its [`Transform` section](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/transform-section-structure.html)  ([see example template](../examples/template/example-template.yaml)).

`AWS::SSO::PermissionSet` resources get the following features:
* Leave the `InstanceArn` property off and it will get looked up using [`sso-admin:ListInstances`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html).
* Specify the `InlinePolicy` as JSON/YAML, and it will get converted to string-containing-json. Note this only works if the policy does not contain references.
* Specify a default session duration in the template metadata or the Macro template parameters, and it will get put on the permission sets if they don't have a value set already.

The syntax for the `SSOUtil::SSO::AssignmentGroup` resource is:

```yaml
MyAssignmentGroup:
  Type: SSOUtil::SSO::AssignmentGroup
  Properties:
    Name: MyAssignmentGroup # As documentation
    InstanceArn: arn:aws:sso:::instance/ssoins-d9e7477013d8e62a
    Principal:
    - Type: USER
      Id: c843295c-d41f-4f23-9832-1521dbaf36f7
    - Type: GROUP
      Id:
      - 6c1645fc-37b5-40ba-8c3d-5216b9055505
      - 67d02fc7-ef1e-463f-b572-ba9b2fe710ba

    PermissionSet:
    - arn:aws:sso:::permissionSet/ssoins-69e2ecd0b249f0cd/ps-45b2cb9e8a6aee12
    - ssoins-69e2ecd0b249f0cd/ps-04a493b762a3fef9
    - ps-b5b9375180ceaaac
    - !GetAtt SomePermissionSetResource.PermissionSetArn

    Target:
    - Type: AWS_OU
      Id: ou-7w1i-suzvrczk
    - Type: AWS_OU
      Recursive: True
      Id: ou-qlmf-1j9r4iq9
    - Type: AWS_ACCOUNT
      Id:
      - 123456789012
      - 174652129131
```
Similar to how IAM policies work, entries for `Principal`, `PermissionSet`, `Target`, and `Id` within `Principal` and `Target` entries, can be either values or lists of values.

The `InstanceArn` field can be omitted, in which case the macro retrieves it from [`sso-admin:ListInstances`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html).
The instance can be provided as a full ARN or just the id.

PermissionSets can be provided as ARNs, the id including the instance, or just the id (in which case the instance is taken from the `Instance` field or looked up).

OUs can optionally be recursive with the `Recursive` property set to true, in which case all accounts in all child OUs are included.
If the accounts in an OU change, and you need the macro to regenerate the assignments based on the change, the resource properties won't have changed, so you can optionally add a string-valued property to the resource called `UpdateNonce` to force CloudFormation to re-run the macro.
Note this will cause all `SSOUtil::SSO::AssignmentGroup` resources in the template to be re-processed, as the macro does not interpret or store this value.

The template can control some of its generation by including the following keys in the `Metadata` section of the template under the `SSO` section:
* `NumChildStacks` and `MaxAssignmentsAllocation`: set one of these (not both) to fix a default number of child stacks.
* `DefaultSessionDuration`: an [ISO8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations) like `PT8H` to set on `AWS::SSO::PermissionSet` resources that don't already have it set.
* `MaxConcurrentAssignments`: to keep assignment creation from being throttled, this is set to 20 as a default. You can change it with this parameter.
* `MaxResourcesPerTemplate`: just what it sounds like, defaults to the CloudFormation limit.

# Client-side generation

I am against client-side generation of CloudFormation templates, but if you don't want to trust this 3rd party macro, you can generate the CloudFormation templates directly.

`aws-sso-util admin cfn` takes one or more input files, and for each input file, generates a CloudFormation template and potentially one or more child templates.
These templates can then be packaged and uploaded using [`aws cloudformation package`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/cloudformation/package.html), for example.

The input files can either be templates using the Macro (using the `--macro` flag), or somewhat simpler configuration files using a different syntax.
These configuration files can define permission sets inline, have references that turn into template parameters, and you can provide a base template that the resulting resources are layered on top of.

Additionally, you can generate a CSV of the assignments that the template will generate, which can use useful for auditing the actual assignments (which you can get from `aws-sso-util assignments`, see the docs for that [here](lookup.md)).
Use the `--assignments-csv` parameter to provide an output file name; the output has the same format as `aws-sso-util assignments`.
Add the `--assignments-csv-only` flag to suppress creation of the templates and only output the CSV.

## Options for both template and config files

The Identity Center instance can be provided using `--sso-instance`/`--ins`, either as the ARN or the id.
It is an error to provide a value that conflicts with an instance given in a template or config file.
If no instance is provided and it is not specified in the template or config file, the instance will be retrieved from [`sso-admin:ListInstances`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html).

The output template file by default is named the same as the input file, in a directory named `templates` in the directory of the input file (that is, `./example.yaml` will result in a template named `./templates/example.yaml`).
Nested stack templates will be placed in a subdirectory named for the input file, e.g., `./templates/example/example01.yaml`.
You can change the output directory with `--output-dir`.
You can change the output file names to include a suffix (before `.yaml`) with `--template-file-suffix`, e.g. providing `-template` to get `example-template.yaml`.

You can control generation parameters, which override any values set in the config file or template, using the following:
* `--lookup-names`: when set, lookup the names for identifiers on assignments and include them in the resource metadata
* `--num-child-stacks` and `--max-assignments-allocation`: set one of these (not both) to fix a default number of child stacks.
* `--default-session-duratoin`: an [ISO8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations) like `PT8H` to set on `AWS::SSO::PermissionSet` resources that don't already have it set.
* `--max-concurrent-assignments`: to keep assignment creation from being throttled, this is set to 20 as a default. You can change it with this parameter.
* `--max-resources-per-template`: just what it sounds like, defaults to the CloudFormation limit.

`--verbose`/`-v` prints more information, up to `-vvv`.

## Templates

Use the `--macro` flag, and see above for syntax.

## Config files

The syntax for config files is as follows:
```yaml
Instance: ssoins-d9e7477013d8e62a

Groups:
- 6c1645fc-37b5-40ba-8c3d-5216b9055505
- 67d02fc7-ef1e-463f-b572-ba9b2fe710ba

Users:
- c843295c-d41f-4f23-9832-1521dbaf36f7
- !Ref UserParameter

PermissionSets:
- arn:aws:sso:::permissionSet/ssoins-69e2ecd0b249f0cd/ps-45b2cb9e8a6aee12
- ssoins-69e2ecd0b249f0cd/ps-04a493b762a3fef9
- ps-b5b9375180ceaaac
- !Ref SomePSResource
- Name: ReadOnly
  ManagedPolicies:
  - "ViewOnlyAccess"

OUs:
- ou-7w1i-suzvrczk
RecursiveOUs:
- ou-qlmf-1j9r4iq9

Accounts:
- 123456789012
- 174652129131
- !Ref AccountParameter
```

All fields (except `Instance`) can either be a single value or a list of values.

The config file can control some of its generation (if these are not set on the command line) by including the following fields:
* `NumChildStacks` and `MaxAssignmentsAllocation`: set one of these (not both) to fix a default number of child stacks.
* `DefaultSessionDuration`: an [ISO8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations) like `PT8H` to set on `AWS::SSO::PermissionSet` resources that don't already have it set.
* `MaxConcurrentAssignments`: to keep assignment creation from being throttled, this is set to 20 as a default. You can change it with this parameter.
* `MaxResourcesPerTemplate`: just what it sounds like, defaults to the CloudFormation limit.

The `Instance` field can be omitted, in which case the macro retrieves it from [`sso-admin:ListInstances`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html).
The instance can be provided as a full ARN or just the id.

PermissionSets can be provided as ARNs, the id including the instance, or just the id (in which case the instance is taken from the `Instance` field or looked up).

The OUs specified in the `OUs` section are not recursive and only include accounts that are direct children of the OU.
To include all child accounts for an OU, put it in the `RecursiveOUs` section.

For any value, you can provide raw CloudFormation that will resolve a value in the template (e.g, a `!Ref` reference, `Fn::If`, etc.).
References become template parameters if they are not found in the base template (see below)
For PermissionSets, you can provide an inline definition of an `AWS::SSO::PermissionSet` resource and it will get included in the (parent) template.

A base template can be provided with `--base-template-file`.
The generated resources are added to this base template, and so you can use references to resources or parameters in the base template as values in your config file.
Note the base template is not used for the nested stacks, which only contain assignments; references from the assignments to resources in the base template are passed through the nested stack parameters.
