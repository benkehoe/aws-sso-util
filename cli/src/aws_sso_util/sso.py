# Copyright 2023 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import typing

import aws_sso_lib as lib

from aws_sso_lib.config import Session

def _get_sso_session(config_session: Session):
    if config_session.is_inline_session():
        session_name = None
    else:
        session_name = config_session.session_name
    sso_session = lib.SSOSession(
        start_url=config_session.start_url,
        region=config_session.region,
        registration_scopes=config_session.registration_scopes,
        session_name=session_name
    )
    return sso_session

def login(config_session: Session, *,
        force_refresh: bool=False,
        expiry_window=None,
        disable_browser: bool=None,
        message: str=None,
        outfile: typing.Union[typing.TextIO, bool]=None,
        user_auth_handler=None,
        sso_cache=None):
    sso_session = _get_sso_session(config_session)
    return lib.login(
        sso_session=sso_session,
        force_refresh=force_refresh,
        expiry_window=expiry_window,
        disable_browser=disable_browser,
        message=message,
        outfile=outfile,
        user_auth_handler=user_auth_handler,
        sso_cache=sso_cache,
    )

def list_available_roles(
        config_session: Session,
        account_id: typing.Union[str, int, typing.Iterable[typing.Union[str, int]]]=None,
        *,
        login: bool=False,
        sso_cache=None) -> typing.Iterator[typing.Tuple[str, str, str]]:
    sso_session = _get_sso_session(config_session)
    return lib.list_available_roles(
        sso_session=sso_session,
        account_id=account_id,
        login=login,
        sso_cache=sso_cache
    )