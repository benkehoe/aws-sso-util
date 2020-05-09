from botocore.exceptions import BotoCoreError

class SSOError(BotoCoreError):
    fmt = "An unspecified error happened when resolving SSO credentials"


class PendingAuthorizationExpiredError(SSOError):
    fmt = (
        "The pending authorization to retrieve an SSO token has expired. The "
        "device authorization flow to retrieve an SSO token must be restarted."
    )


class SSOTokenLoadError(SSOError):
    fmt = "Error loading SSO Token: {error_msg}"


class UnauthorizedSSOTokenError(SSOError):
    fmt = (
        "The SSO session associated with this profile has expired or is "
        "otherwise invalid. To refresh this SSO session run aws2 sso login "
        "with the corresponding profile."
    )
