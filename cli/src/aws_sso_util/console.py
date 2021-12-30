import logging
import sys
import json
import webbrowser
import urllib.parse
import os
import base64
from typing import Optional, List, Dict

import requests

import click

from aws_sso_lib.sso import get_boto3_session, login

from .utils import configure_logging, get_instance, GetInstanceError

LOGGER = logging.getLogger(__name__)

def get_logout_url(region: Optional[str]=None):
    redirect = urllib.parse.quote_plus("https://aws.amazon.com/premiumsupport/knowledge-center/sign-out-account/?from_aws_sso_util_logout")
    if not region or region == "us-east-1":
        return f"https://signin.aws.amazon.com/oauth?Action=logout&redirect_uri={redirect}"

    if region == "us-gov-east-1":
        return "https://us-gov-east-1.signin.amazonaws-us-gov.com/oauth?Action=logout"

    if region == "us-gov-west-1":
        return "https://signin.amazonaws-us-gov.com/oauth?Action=logout"

    return f"https://{region}.signin.aws.amazon.com/oauth?Action=logout&redirect_uri={redirect}"

def get_federation_endpoint(region: Optional[str]=None):
    if not region or region == "us-east-1":
        return "https://signin.aws.amazon.com/federation"

    if region == "us-gov-east-1":
        return "https://us-gov-east-1.signin.amazonaws-us-gov.com/federation"

    if region == "us-gov-west-1":
        return "https://signin.amazonaws-us-gov.com/federation"

    return f"https://{region}.signin.aws.amazon.com/federation"

def get_destination_base_url(region: Optional[str]=None):
    if region and region.startswith("us-gov-"):
        #TODO: regional?
        return "https://console.amazonaws-us-gov.com"
    if region:
        return f"https://{region}.console.aws.amazon.com/"
    else:
        return "https://console.aws.amazon.com/"

def get_destination(path: Optional[str]=None, region: Optional[str]=None, override_region_in_destination: bool=False):
    base = get_destination_base_url(region=region)

    if path:
        stripped_path_parts = urllib.parse.urlsplit(path)[2:]
        path = urllib.parse.urlunsplit(('', '') + stripped_path_parts)
        url = urllib.parse.urljoin(base, path)
    else:
        # url = urllib.parse.urljoin(base, "/console/home")
        url = base

    if not region:
        return url

    parts = list(urllib.parse.urlsplit(url))
    query_params = urllib.parse.parse_qsl(parts[3])
    if override_region_in_destination:
        query_params = [(k, v) for k, v in query_params if k != "region"]
        query_params.append(("region", region))
    elif not any(k == "region" for k, _ in query_params):
        query_params.append(("region", region))
    query_str = urllib.parse.urlencode(query_params)
    parts[3] = query_str

    url = urllib.parse.urlunsplit(parts)

    return url

@click.command("launch")
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account-id", "-a", metavar="ACCOUNT_ID", help="The AWS account", required=True)
@click.option("--role-name", "-r", metavar="ROLE_NAME", help="The SSO role to assume in account", required=True)
@click.option("--region", metavar="REGION", help="The AWS region", envvar="AWS_CONSOLE_DEFAULT_REGION")
@click.option("--destination", "destination_path", metavar="PATH", help="Console URL path to go to", envvar="AWS_CONSOLE_DEFAULT_DESTINATION")
@click.option("--override-region-in-destination/--keep-region-in-destination", default=False)
@click.option("--open/--no-open", "-o", "open_url", default=None, help="Open the login URL in a browser (the default)")
@click.option("--print/--no-print", "-p", "print_url", default=None, help="Print the login URL")
@click.option("--duration", metavar="MINUTES", type=click.IntRange(15, 720), help="The session duration in minutes")
@click.option("--logout-first/--no-logout-first", "-l", default=None, help="Open a logout page first")
@click.option("--force-refresh", is_flag=True, help="Re-login to AWS SSO")
@click.option("--verbose", "-v", count=True)
def launch(
        sso_start_url,
        sso_region,
        account_id,
        role_name,
        region,
        destination_path,
        override_region_in_destination,
        open_url,
        print_url,
        duration,
        logout_first,
        force_refresh,
        verbose
        ):
    """Sign in to the AWS console as a particular account and role."""

    configure_logging(LOGGER, verbose)

    if open_url is None:
        open_url = not (print_url is True)

    logout_first_from_env = False
    if logout_first is None:
        logout_first = os.environ.get("AWS_CONSOLE_LOGOUT_FIRST", "").lower() in ["true", "1"]
        logout_first_from_env = True

    if logout_first and not open_url:
        if logout_first_from_env:
            logout_first_value = os.environ["AWS_CONSOLE_LOGOUT_FIRST"]
            raise click.UsageError(f"AWS_CONSOLE_LOGOUT_FIRST={logout_first_value} requires --open")
        else:
            raise click.UsageError("--logout-first requires --open")

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
        )
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    federation_endpoint = get_federation_endpoint(region=region)
    issuer = os.environ.get("AWS_CONSOLE_DEFAULT_ISSUER")
    destination = get_destination(path=destination_path, region=region, override_region_in_destination=override_region_in_destination)

    return _launch_console(
        sso_start_url=instance.start_url,
        sso_region=instance.region,
        account_id=account_id,
        role_name=role_name,
        federation_endpoint=federation_endpoint,
        issuer=issuer,
        destination=destination,
        region=region,
        open_url=open_url,
        print_url=print_url,
        duration=duration,
        logout_first=logout_first,
        force_refresh=force_refresh,
        )

TOKEN_KEY_MAPPING = [
    ("version", "v"),
    ("sso_start_url", "ssourl"),
    ("sso_region", "ssoreg"),
    ("account_id", "acc"),
    ("role_name", "rol"),
    ("region", "reg"),
    ("federation_endpoint", "url"),
    ("issuer", "iss"),
    ("destination", "dst"),
    ("duration", "dur"),
]

def to_token_key(key):
    for k, token_k in TOKEN_KEY_MAPPING:
        if k == key:
            return token_k
    # do not allow unknown keys in an outgoing token
    raise KeyError(key)

def from_token_key(token_key):
    for k, token_k in TOKEN_KEY_MAPPING:
        if token_k == token_key:
            return k
    # allow unknown keys in an incoming token
    return token_key

@click.command("get-config-token")
@click.option("--sso-start-url", "-u", metavar="URL", help="Your AWS SSO start URL")
@click.option("--sso-region", metavar="REGION", help="The AWS region your AWS SSO instance is deployed in")
@click.option("--account-id", "-a", metavar="ACCOUNT_ID", help="The AWS account")
@click.option("--role-name", "-r", metavar="ROLE_NAME", help="The SSO role to assume in account")
@click.option("--region", metavar="REGION", help="The AWS region")
@click.option("--destination", "destination_path", metavar="PATH", help="Console URL path to go to")
@click.option("--override-region-in-destination/--keep-region-in-destination", default=False)
@click.option("--duration", metavar="MINUTES", type=click.IntRange(15, 720), help="The session duration in minutes")
@click.option("--issuer", metavar="ISSUER", hidden=True)
@click.option("--verbose", "-v", count=True)
def get_config_token(
        sso_start_url,
        sso_region,
        account_id,
        role_name,
        region,
        destination_path,
        override_region_in_destination,
        duration,
        issuer,
        verbose
        ):
    """Package console launch config as a token to use with `aws-sso-util console launch-from-config`.

    Note that config tokens do not contain credentials."""

    configure_logging(LOGGER, verbose)

    try:
        instance = get_instance(
            sso_start_url,
            sso_region,
        )
    except GetInstanceError as e:
        LOGGER.fatal(str(e))
        sys.exit(1)

    federation_endpoint = get_federation_endpoint(region=region)
    destination = get_destination(path=destination_path, region=region, override_region_in_destination=override_region_in_destination)

    token_data = {
        "version": "1",
        "sso_start_url": instance.start_url,
        "sso_region": instance.region,
        "federation_endpoint": federation_endpoint,
        "destination": destination,
    }
    if account_id:
        token_data["account_id"] = account_id
    if role_name:
        token_data["role_name"] = role_name
    if region:
        token_data["region"] = region
    if duration:
        token_data["duration"] = duration

    # unless specifically provided, issuer should be set when login actually happens
    if issuer:
        token_data["issuer"] = issuer

    # convert to compact form
    token_payload = dict((to_token_key(key), value) for key, value in token_data.items())

    LOGGER.debug("Token payload: " + json.dumps(token_payload))

    serialized_json_bytes = json.dumps(token_payload, ensure_ascii=True, separators=(',', ':')).encode("utf-8")
    base64_encoded_bytes = base64.urlsafe_b64encode(serialized_json_bytes)
    token = str(base64_encoded_bytes, "ascii")
    LOGGER.info(token)

@click.command("launch-from-config")
@click.option("--config-token", "-t", metavar="TOKEN", help="The config token", required=True)
@click.option("--account-id", "-a", metavar="ACCOUNT_ID", help="The AWS account")
@click.option("--role-name", "-r", metavar="ROLE_NAME", help="The SSO role to assume in account")
@click.option("--open/--no-open", "-o", "open_url", default=None, help="Open the login URL in a browser (the default)")
@click.option("--print/--no-print", "-p", "print_url", default=None, help="Print the login URL")
@click.option("--logout-first/--no-logout-first", "-l", default=None, help="Open a logout page first")
@click.option("--force-refresh", is_flag=True, help="Re-login to AWS SSO")
@click.option("--verbose", "-v", count=True)
def launch_from_config(
        config_token,
        account_id,
        role_name,
        open_url,
        print_url,
        logout_first,
        force_refresh,
        verbose
        ):
    """Sign in to the AWS console using the given config token."""

    configure_logging(LOGGER, verbose)

    if open_url is None:
        open_url = not (print_url is True)

    logout_first_from_env = False
    if logout_first is None:
        logout_first = os.environ.get("AWS_CONSOLE_LOGOUT_FIRST", "").lower() in ["true", "1"]
        logout_first_from_env = True

    if logout_first and not open_url:
        if logout_first_from_env:
            logout_first_value = os.environ["AWS_CONSOLE_LOGOUT_FIRST"]
            raise click.UsageError(f"AWS_CONSOLE_LOGOUT_FIRST={logout_first_value} requires --open")
        else:
            raise click.UsageError("--logout-first requires --open")

    param_keys = {
        "sso_start_url",
        "sso_region",
        "account_id",
        "role_name",
        "federation_endpoint",
        "issuer",
        "destination",
        "region",
        "duration",
    }

    all_keys = set(k for k, v in TOKEN_KEY_MAPPING)

    # parse the token
    try:
        token_payload = json.loads(base64.urlsafe_b64decode(config_token))
        if not isinstance(token_payload, dict):
            raise ValueError("Invalid format")
        LOGGER.debug("Token payload: " + json.dumps(token_payload))
        # convert from compact form
        token_data = dict((from_token_key(key), value) for key, value in token_payload.items())
    except Exception as e:
        LOGGER.error(f"The config token is invalid: {e}")
        sys.exit(1)

    # check the token version
    token_version = token_data.get("version")
    if token_version != "1":
        LOGGER.error(f"Unknown config token version: {token_version}")

    # check we have an account, override if it's given
    if not token_data.get("account_id") and not account_id:
        raise click.UsageError("Token does not specify account, please use --account-id")
    if account_id:
        token_data["account_id"] = account_id

    # check we have a role, override if it's given
    if not token_data.get("role_name") and not role_name:
        raise click.UsageError("Token does not specify account, please use --role-name")
    if role_name:
        token_data["role_name"] = role_name

    # check for keys we don't understand
    token_data_keys = set(token_data.keys())
    unknown_keys = token_data_keys - all_keys
    if unknown_keys:
        LOGGER.warning(f"The config token contains unknown keys: {', '.join(unknown_keys)}")

    # filter down to args for _launch_console
    params = dict((k, v) for k, v in token_data.items() if k in param_keys)

    return _launch_console(
        open_url=open_url,
        print_url=print_url,
        logout_first=logout_first,
        force_refresh=force_refresh,
        **params
    )

def _launch_console(
        *,
        sso_start_url: str,
        sso_region: str,
        account_id: str,
        role_name: str,
        federation_endpoint: str,
        destination: str,
        region: Optional[str]=None,
        open_url: Optional[bool]=None,
        print_url: Optional[bool]=None,
        duration: Optional[int]=None,
        logout_first: Optional[bool]=None,
        issuer: Optional[str]=None,
        force_refresh: Optional[bool]=None,
        ):
    if not issuer:
        issuer = sso_start_url

    login(sso_start_url, sso_region, force_refresh=force_refresh)

    session = get_boto3_session(
        sso_start_url,
        sso_region,
        account_id,
        role_name,
        region=region,
    )

    read_only_credentials = session.get_credentials().get_frozen_credentials()

    session_data = {
        "sessionId": read_only_credentials.access_key,
        "sessionKey": read_only_credentials.secret_key,
        "sessionToken": read_only_credentials.token
    }

    get_signin_token_payload = {
        "Action": "getSigninToken",
        "Session": json.dumps(session_data)
    }
    if duration is not None:
        get_signin_token_payload["SessionDuration"] = duration * 60

    response = requests.post(federation_endpoint, data=get_signin_token_payload)

    if response.status_code != 200:
        LOGGER.error("Could not get signin token")
        LOGGER.debug(response.status_code + "\n" + response.text)
        sys.exit(2)

    token = response.json()["SigninToken"]

    get_login_url_params = {
        "Action": "login",
        "Issuer": issuer,
        "Destination": destination,
        "SigninToken": token
    }

    request = requests.Request(method="GET", url=federation_endpoint,
        params=get_login_url_params)

    prepared_request = request.prepare()

    login_url = prepared_request.url

    if print_url:
        LOGGER.info(login_url)

    if open_url:
        if logout_first:
            logout_url = get_logout_url(region=region)
            webbrowser.open(logout_url, autoraise=False) #&redirect_uri=https://aws.amazon.com

        webbrowser.open(login_url)


if __name__ == "__main__":
    launch(prog_name="python -m aws_sso_util.console")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
