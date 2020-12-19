# AWS SSO primer

AWS SSO is a service for integrating authentication and authorization in a common way across your AWS footprint.
It can also  function as a single sign-on provider, but we will set that aside here.

You can use AWS SSO either with an external identity provider (IdP) like Okta, Ping, OneLogin, and ActiveDirectory (replacing SAML federation with STS), or with an AWS SSO-managed identity store (replacing IAM users).

Note that only the AWS CLI v2 supports signing in to AWS SSO; [installation docs are here](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html).

## Concepts

There is an AWS SSO **instance**; currently, only one instance is allowed, but this seems likely to change in the future (the API is [*ListInstances*](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ListInstances.html)).
An AWS SSO instance is associated with an identity store, and has two identifiers: an *instance ARN*, which is used by administrators, and a **start URL**, which is the entry point for signing in, and the identifier used by users.
An instance exists in a particular AWS region, and this region must be known by users as it is needed as part of the sign-in process.

Adminstrators create [**permission sets**](https://docs.aws.amazon.com/singlesignon/latest/userguide/permissionsetsconcept.html); each permission set is a collection of IAM policies (currently, AWS managed policies and a single inline policy).

Administrators create [**assignments**](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_CreateAccountAssignment.html); each assignment is the combination of a *principal* (a user or group from the IdP), a permission set, and a *target* (an AWS account).
A assignment means that principal is entitled use those permissions within that account. An assignment is [*provisioned*](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_ProvisionPermissionSet.html) into an AWS SSO-managed IAM role in that account.

Users interact with "role names", using familiar terminology, but these are in fact permission set names.
The provisioned IAM roles use mangled names that are not shown to users.

## Signing in

When a user signs in, they first authenticate with AWS SSO, which, if it is configured to use an external IdP, involves a redirection to the IdP.
This authentication results in an OIDC access token that represents the user's session.
Note that this is *not* AWS credentials, because the user may have access to many accounts and roles (provisioned permission sets), but they only need to sign in once.

The sign-in always happens through the browser, so it can leverage your existing session with your external IdP.
If you use [`aws sso login`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/sso/login.html), [`aws-sso-util login`](https://github.com/benkehoe/aws-sso-util/blob/master/docs/login.md), or [`aws_sso_lib.login()`](https://github.com/benkehoe/aws-sso-util/blob/master/lib/README.md#login), these will all re-used a cached token if they find one, or pop up a browser if they do not have a valid cached token, which will then prompt you to sign in only if your session with your IdP has expired.
The browser sign-in flow will, however, always prompt you to approve releasing the token to the CLI or script that triggered the sign-in process.

When using the AWS CLI and `aws-sso-util`/`aws-sso-lib`, this token is cached in `~/.aws/sso/cache`.

## AWS credentials

Subsequently, this OIDC access token can be used to determine the user's access, and to get AWS credentials for a specific account and role (i.e., an IAM role provisioned for a permission set).

The ability to enumerate which accounts and roles the user has access to, using the access token, is leveraged by [`aws configure sso`](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/configure/sso.html), [`aws-sso-util configure`](https://github.com/benkehoe/aws-sso-util/blob/master/docs/configure.md), and [`aws-sso-util roles`](https://github.com/benkehoe/aws-sso-util/blob/master/docs/configure.md#aws-sso-util-roles).

For a given account and role, the token can be used to get AWS credentials.
A profile configured for AWS SSO in `~/.aws/config` has an account and role specified, and the AWS CLI and SDKs* automatically load the cached access token and use it to retrieve AWS credentials for that account and role (including refreshing the AWS credentials if they expire but the access token is still valid).
This mechanism is also used for programmatic access using [`aws_sso_lib.get_boto3_session()`](https://github.com/benkehoe/aws-sso-util/blob/master/lib/README.md#get_boto3_session).

## Administration

Administering AWS SSO is done through the [`sso-admin`](https://docs.aws.amazon.com/singlesignon/latest/APIReference/welcome.html) and [`identitystore`](https://docs.aws.amazon.com/singlesignon/latest/IdentityStoreAPIReference/welcome.html) APIs, which are accessed using AWS credentials.

Note that a) these APIs cannot be used directly with the OIDC access token resulting from signing in, and b) the AWS credentials used to access them do not need to come from a role linked to AWS SSO (otherwise, how would you set it up?).
