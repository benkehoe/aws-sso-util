# aws-sso-util CloudFormation support

`aws-sso-util` helps patch over the lack of support in AWS SSO, and therefore in AWS SSO's CloudFormation resources, for managing assignments as groups.

AWS SSO's CloudFormation support currently only includes [`AWS::SSO::Assignment`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sso-assignment.html), which means for every combination of principal (group or user), permission set, and target (AWS account), you need a separate CloudFormation resource.
Additionally, AWS SSO does not support OUs as targets, so you need to specify every account separately.

Obviously, this gets verbose, and even an organization of moderate size is likely to have tens of thousands of assignments.
`aws-sso-util` provides two mechanisms to make this concise, a [CloudFormation Macro](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-macros.html) for cloud-side processing, or client-side generation using `aws-sso-util cfn`.

[I look forward to discarding](https://faasandfurious.com/122) this part of the tool once there are two prerequisites:
1. OUs as targets for assignments
2. An `AWS::SSO::AssignmentGroup` resource that allows specifications of multiple principals, permission sets, and targets, and performs the combinatorics directly.

## Output
With either method, the result is a template that either includes the assignments directly, or, if there are too many assignments to contain in a single stack, [nested stacks](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-nested-stacks.html) that contain the assignments.
References on assignment resources are automatically wired through to the nested stacks.

# CloudFormation Macro
`aws-sso-util` defines a resource format for an AssignmentGroup that is a combination of multiple principals, permission sets, and targets, and provides a CloudFormation Macro you can deploy that lets you use this resource in your templates.

## Deploy macro

TODO

## Use macro

The template must include `AWS-SSO-Util-2020-11-08` in its [`Transform` section](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/transform-section-structure.html).

The syntax for the `AWSSSOUtil::SSO::AssignmentGroup` resource is:

```yaml
MyAssignmentGroup:
  Type: AWSSOUtil::SSO::AssignmentGroup
  Properties:
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
    - !Ref SomePermissionSetResource

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
Note this will cause all `AWSSOUtil::SSO::AssignmentGroup` resources in the template to be re-processed, as the macro does not interpret or store this value.

# Client-side generation

I am against client-side generation of CloudFormation templates, but if you don't want to trust this 3rd party macro, you can generate the CloudFormation templates directly.

`aws-sso-util cfn` takes one or more input files, and for each input file, generates a CloudFormation template and potentially one or more child templates.
These templates can then be packaged and uploaded using [`aws cloudformation package`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/cloudformation/package.html), for example.

The input files can either be templates using the Macro (using the `--macro` flag), or somewhat simpler configuration files using a different syntax.
These configuration files can define permission sets inline, have references that turn into template parameters, and you can provide a base template that the resulting resources are layered on top of.

## Options for both template and config files

The AWS SSO instance can be provided using `--sso-instance`/`--ins`, either as the ARN or the id.
It is an error to provide a value that conflicts with an instance given in a template or config file.
If no instance is provided and it is not specified in the template or config file, the instance will be retrieved from [`sso-admin:ListInstances`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html).

The output template file by default is named the same as the input file, in a directory named `templates` in the directory of the input file (that is, `./example.yaml` will result in a template named `./templates/example.yaml`).
Nested stack templates will be placed in a subdirectory named for the input file, e.g., `./templates/example/example01.yaml`.
You can change the output directory with `--output-dir`.
You can change the output file names to include a suffix (before `.yaml`) with `--template-file-suffix`, e.g. providing `-template` to get `example-template.yaml`.

`--max-resources-per-template` defines how many assignments will be put in a given template, forcing the assignments into nested stacks and determining the number of nested stacks.

`--max-concurrent-assignments` produces dependencies between the assignments to slow the creation of assignments to prevent throttling.
The default is 20.

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

OUs: ou-7w1i-suzvrczk
RecursiveOUs:
- ou-qlmf-1j9r4iq9

Accounts:
- 123456789012
- 174652129131
- !Ref AccountParameter
```

All fields (except `Instance`) can either be a single value or a list of values.

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
