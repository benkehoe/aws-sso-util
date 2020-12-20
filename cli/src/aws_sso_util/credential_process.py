# Copyright 2020 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This code is based on the code for the AWS CLI v2"s `aws sso login` functionality
# https://github.com/aws/aws-cli/tree/v2/awscli/customizations/sso

import argparse
import os
import sys
import json
import logging
import datetime

from botocore.session import Session
from botocore.exceptions import ClientError

import click

from aws_sso_lib.sso import get_credentials
from aws_sso_lib.exceptions import InvalidSSOConfigError, AuthDispatchError, AuthenticationNeededError, UnauthorizedSSOTokenError

LOG_FILE = os.path.expanduser(
    os.path.join("~", ".aws", "sso", "aws-sso-credential-process-log.txt")
)

LOGGER = logging.getLogger(__name__)

CONFIG_VARS = [
    ("start url", "sso_start_url"),
    ("SSO region", "sso_region"),
    ("account", "sso_account_id"),
    ("role", "sso_role_name")
]

def get_config(arg_config, profile_config):
    sso_config = {}
    missing_vars = []
    for friendly_name, config_var_name in CONFIG_VARS:
        if arg_config.get(config_var_name):
            sso_config[config_var_name] = arg_config[config_var_name]
        elif config_var_name not in profile_config:
            missing_vars.append((friendly_name, config_var_name))
            sso_config[config_var_name] = None
        else:
            sso_config[config_var_name] = profile_config[config_var_name]

    required_vars = ["sso_start_url", "sso_region", "sso_account_id", "sso_role_name"]

    missing_requred_vars = [v[0] for v in missing_vars if v[1] in required_vars]
    if missing_requred_vars:
        raise InvalidSSOConfigError(
            "Missing " + ", ".join(missing_requred_vars)
        )
    return sso_config


@click.command("credential-process")
@click.option("--profile", help="Extract settings from the given profile")
@click.option("--sso-start-url", "--start-url", "start_url")
@click.option("--sso-region", "--region", "region")
@click.option("--account-id")
@click.option("--role-name")

@click.option("--force-refresh", is_flag=True, help="Do not reuse cached AWS SSO token")
@click.option( "--verbose", "-v", "--debug", count=True, help="Write to the debugging log file")
def credential_process(
        profile,
        start_url,
        region,
        account_id,
        role_name,
        force_refresh,
        verbose):
    """Helper for AWS SDKs that don't yet support AWS SSO.

    This is not a command you use directly.
    In a ~/.aws/config profile set up for AWS SSO, you can add the line

    credential_process = aws-sso-util credential-process --profile NAME

    with the profile name set to the profile the line is in.

    This line is automatically added by aws-sso-util configure commands.
    """

    if verbose or os.environ.get("AWS_SSO_CREDENTIAL_PROCESS_DEBUG", "").lower() in ["1", "true"]:
        logging.basicConfig(level=logging.DEBUG, filename=LOG_FILE, filemode="w")
    else:
        logging.disable(logging.CRITICAL)

    LOGGER.info("Starting credential process at {}".format(datetime.datetime.now().isoformat()))

    if role_name is None and os.environ.get("AWS_SSO_ROLE_NAME"):
        LOGGER.debug("Using role from env: {}".format(os.environ["AWS_SSO_ROLE_NAME"]))
        role_name = os.environ["AWS_SSO_ROLE_NAME"]

    if account_id is None and os.environ.get("AWS_SSO_ACCOUNT_ID"):
        LOGGER.debug("Using acccount from env: {}".format(os.environ["AWS_SSO_ACCOUNT_ID"]))
        account_id = os.environ["AWS_SSO_ACCOUNT_ID"]

    # if role_name and role_name.startswith("arn"):
    #     parts = role_name.split(":")
    #     account_id = parts[4]
    #     role_name = parts[5].split("/", 1)[1]

    if start_url is None and os.environ.get("AWS_SSO_START_URL"):
        start_url = os.environ["AWS_SSO_START_URL"]

    if region is None and os.environ.get("AWS_SSO_REGION"):
        region = os.environ["AWS_SSO_REGION"]

    session_kwargs = {}

    if profile:
        session_kwargs["profile"] = profile

    arg_config = {
        "sso_start_url": start_url,
        "sso_region": region,
        "sso_role_name": role_name,
        "sso_account_id": account_id,
    }

    LOGGER.info("CONFIG FROM ARGS: {}".format(json.dumps(arg_config)))

    try:
        session = Session(**session_kwargs)

        if profile:
            profile_config = session.get_scoped_config()
            LOGGER.info("CONFIG FROM PROFILE: {}".format(json.dumps(profile_config)))
        else:
            profile_config = {}

        config = get_config(arg_config, profile_config)

        LOGGER.info("CONFIG: {}".format(json.dumps(config)))

        if (config.get("sso_interactive_auth") or "").lower() == "true":
            raise InvalidSSOConfigError("Interactive auth has been removed. See https://github.com/benkehoe/aws-sso-credential-process/issues/4")

        if not config["sso_account_id"]:
            raise InvalidSSOConfigError("Missing account id")

        if not config["sso_role_name"]:
            raise InvalidSSOConfigError("Missing role")

        credentials = get_credentials(
            session=session,
            start_url=config["sso_start_url"],
            sso_region=config["sso_region"],
            account_id=config["sso_account_id"],
            role_name=config["sso_role_name"],
            force_refresh=force_refresh,
        )

        output = {
            "Version": 1,
            "AccessKeyId": credentials["access_key"],
            "SecretAccessKey": credentials["secret_key"],
            "SessionToken": credentials["token"],
            # as provided the expiration isn"t valid ISO8601 and that causes parsing errors for some SDKs
            "Expiration": credentials["expiry_time"].replace("UTC", "Z"),
        }
        LOGGER.debug("CREDENTIALS: " + json.dumps(output))

        print(json.dumps(output, separators=(",", ":")))
    except (AuthenticationNeededError, UnauthorizedSSOTokenError) as e:
        if profile:
            aws_sso_util_cmd = f"aws-sso-util login --profile {profile}"
            aws_sso_cmd = f"aws sso login --profile {profile}"
        else:
            aws_sso_util_cmd = f"aws-sso-util login {config['sso_start_url']} {config['sso_region']}"
            aws_sso_cmd = f"aws sso login"
        print(f"Login required. Use `{aws_sso_util_cmd}` or `{aws_sso_cmd}` and try again.", file=sys.stderr)
        sys.exit(1)
    except InvalidSSOConfigError as e:
        LOGGER.error(e)
        print(e, file=sys.stderr)
        sys.exit(2)
    except AuthDispatchError as e:
        LOGGER.error(e)
        print(e, file=sys.stderr)
        sys.exit(3)
    except ClientError as e:
        LOGGER.error(e, exc_info=True)
        #TODO: print a different message for AccessDeniedException during CreateToken? -> user canceled login
        # boto_error_matches(e, "CreateToken", "AccessDeniedException")
        print("ERROR:", e, file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        LOGGER.error(e, exc_info=True)
        print("ERROR:", e, file=sys.stderr)
        sys.exit(5)

if __name__ == "__main__":
    credential_process(prog_name="python -m aws_sso_util.credential_process")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
