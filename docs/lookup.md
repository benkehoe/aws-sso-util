# `aws-sso-util lookup` and `aws-sso-util assignments`
The AWS SSO APIs leave a lot to be desired when it comes to searching and listing items.
These two utilities help deal with that.

# `aws-sso-util lookup`
The AWS SSO APIs and CloudFormation resources require the use of identifiers that are not displayed in the console, and that the APIs do not make easy to look up by name.
`aws-sso-util lookup` is provided to make this a little easier.

| Item                    | Syntax                                             |
| ----------------------- | -------------------------------------------------- |
| AWS SSO instance        | `aws-sso-util lookup instance`                          |
| AWS SSO identity store  | `aws-sso-util lookup identity-store`                    |
| Groups                  | `aws-sso-util lookup groups GROUP_NAME [GROUP_NAME...]` |
| Users                   | `aws-sso-util lookup users USER_NAME [USER_NAME...]`    |
| Permission sets         | `aws-sso-util lookup permission-sets NAME [NAME...]`    |

For instance and identity store, it just prints out the id.
For the others, it displays the instance/identity store id being used, and then a list of the names with their identifiers.
You can control the field separator with `--sep` (e.g., to output a CSV).

By default, any names not found will have `NOT_FOUND` as their identifier, but with `--error-if-not-found`/`-e` it will exit with an error at the first name not found.

For group/user/permission set lookups, the instance/identity store will be automatically retrieved if you do not provide `--instance-arn` (for permission sets) or `--instance-store-id` (for groups and users).
By default, the ids will not be printed when they are looked up; you can display them `--show-id`.

# `aws-sso-util assignments`
There is no simple API for retrieving all assignments or even a decent subset.
The current best you can do is [list all the users with a particular PermissionSet on a particular account](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListAccountAssignments.html).

`aws-sso-util` takes care of this, by [looping over all the accounts in your organization](https://docs.aws.amazon.com/organizations/latest/APIReference/API_ListAccounts.html), then [over all the permission sets in each account](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListPermissionSetsProvisionedToAccount.html) and then [over all principals with that permission set in that account](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListAccountAssignments.html).

For group/user/permission set lookups, the instance/identity store will be automatically retrieved if you do not provide `--instance-arn` (for permission sets) or `--instance-store-id` (for groups and users).
By default, the ids will not be printed when they are looked up; you can display them `--show-id`.

The output is a CSV-formatted list of the assignments with the following columns:
* Principal type (`GROUP` or `USER`)
* Principal id
* Principal name, if it can be found, or `UNKNOWN` otherwise
* PermissionSet id (the part of the ARN after the first slash, to get the ARN prepend the id with `arn:aws:sso:::permissionSet/`)
* PermissionSet name
* Target type (`AWS_ACCOUNT`)
* Target id (account number)
* Target name (account name)

You can filter the list by providing the following options.
For a given parameter, providing multiple values is an OR operation; combining multiple parameters is AND.

`--group`/`-g` and `--user`/`-u` can be the full id, or a regex pattern to match against the name.

`--permission-set` can be the ARN, or the full id (everything after the first slash in the ARN) or the short id (after the last slash), or a regex to match against the permission set name.

`--account`/`-a` can be a string that matches either the beginning or the end of the AWS account number, or a regex to match against the account name.
