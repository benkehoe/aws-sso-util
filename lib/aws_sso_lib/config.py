# Copyright 2020 Ben Kehoe
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

import os
import logging
import re
import json
from collections import defaultdict
from dataclasses import dataclass, field as dataclass_field
from typing import Optional, Union, Iterable

import botocore
from botocore.exceptions import ProfileNotFound
from .vendored_awscli.utils import parse_sso_registration_scopes

LOGGER = logging.getLogger(__name__)

def _getenv(names: list[str]):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value, name
    return None, None

SPECIFIER_VARS = ["AWS_SSO_SESSION"]

@dataclass(frozen=True)
class Source:
    type: str
    name: str
    parent: Optional["Source"] = None

    def __str__(self):
        s = f"{self.type} {self.name}"
        if self.parent:
            s += f" via {self.parent}"
        return s

@dataclass(frozen=True)
class Session:
    session_name: str
    source: Optional[Source]

    start_url: str
    region: str
    registration_scopes: Optional[list[str]] = None

    def __post_init__(self):
        if not (self.session_name and self.start_url and self.region):
            raise ValueError("Session must have a name, start URL, and region")

    def is_inline_session(self):
        return self.session_name.startswith("http")
    
    def to_str(self, region: bool=False, registration_scopes: bool=False) -> str:
        if self.is_inline_session():
            s = f"anonymous[{self.start_url}"
        else:
            s = f"{self.session_name}[{self.start_url}"
        if region:
            s += f";{self.region}"
        if registration_scopes and self.registration_scopes:
            s += f";{','.join(self.registration_scopes)}"
        s += "]"
        return s
    
    def __str__(self) -> str:
        return self.to_str()
    
    @classmethod
    def to_strs(self, sessions: Iterable["Session"], region: bool=False, registration_scopes: bool=False) -> str:
        return ", ".join(s.to_str(region=region, registration_scopes=registration_scopes) for s in sessions)


class InlineSessionError(Exception):
    pass

@dataclass(frozen=True)
class Specifier:
    value: str
    source: Source

    session: Optional[Session] = dataclass_field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "session", self._to_session())

    def _to_session(self) -> Optional[Session]:
        if not self.value.strip().startswith("{"):
            return None
        try:
            session_data = json.loads(self.value)
        except json.JSONDecodeError as e:
            raise InlineSessionError(f"Inline session from {self.source} is not valid JSON")
        if not isinstance(session_data, dict):
            return None

        missing = []
        if "sso_start_url" not in session_data:
            missing.append("sso_start_url")
        if "sso_region" not in session_data:
            missing.append("sso_region")
        
        if missing:
            raise InlineSessionError(f"Inline session from {self.source} in specifier is missing fields: {' '.join(missing)}")
        
        session_kwargs = {
            "session_name": session_data["sso_start_url"], #TODO: allow this to given in the session_data?
            "source": Source(
                type="inline specifier",
                name=self.source.name,
                parent=self.source
            ),
            "start_url": session_data["sso_start_url"],
            "region": session_data["sso_region"]
        }

        if "sso_registration_scopes" in session_data:
            raw_registration_scopes = session_data["sso_registration_scopes"]
            try:
                session_kwargs["registration_scopes"] = parse_sso_registration_scopes(raw_registration_scopes)
            except Exception as e:
                raise InlineSessionError(f"Inline session has malformed registration scopes {raw_registration_scopes}")
        
        return Session(**session_kwargs)
    
    def matches(self, session: Session) -> bool:
        if self.session:
            raise TypeError("This specifier is in an inline session, it can't be used for matching")
        if self.value.startswith("http"):
            return self.value == session.start_url
        return re.search(self.value, session.session_name)
    
    def to_str(self):
        s = repr(self.value)
        if self.source:
            s += f" from {self.source}"
        return s

def get_specifier() -> Specifier:
    value, name = _getenv(SPECIFIER_VARS)
    if not value:
        return None
    return Specifier(
        value=value,
        source=Source(
            type="env var",
            name=name
        )
    )

class MismatchedSessionError(Exception):
    pass

@dataclass(frozen=True)
class MismatchedSession:
    mismatched_session: Session
    base_session: Session
    message: str

def _validate_sessions_are_same(s1: Session, s2: Session) -> Optional[MismatchedSession]:
    bad_fields = []
    if s1.session_name != s2.session_name:
        raise ValueError("Session names do not match")
    if s1.start_url != s2.start_url:
        bad_fields.append("start_url")
    if s1.region != s2.region:
        bad_fields.append("region")
    if s1.registration_scopes != s2.registration_scopes:
        bad_fields.append("registration_scopes")
    if not bad_fields:
        return None
    
    message = f"Session {s1.session_name}"
    if s1.source:
        message += f" ({s1.source})"
    messsage += f" and {s2.session_name}"
    if s2.source:
        message += f" ({s2.source})"
    message += f" have mismatched values for {', '.join(bad_fields)}"

    return MismatchedSession(
        mismatched_session=s2,
        base_session=s1,
        message=message
    )

@dataclass(frozen=True)
class FindAllSessionsResult:
    unique_sessions: list[Session]
    all_sessions: list[Session]
    malformed_session_errors: list[Exception]
    mismatched_sessions: dict[str, list[MismatchedSession]]

    def filter(self, specifier: Specifier) -> list[Session]:
        result = []
        for session in self.unique_sessions:
            if specifier.matches(session):
                result.append(session)
        return result
    
    def raise_for_mismatch(self, sessions: Union[list[str], list[Session]]):
        messages = []
        for session in sessions:
            if isinstance(session, Session):
                session_name = session.session_name
            else:
                session_name = session
            if session_name in self.mismatched_sessions:
                messages.append(self.mismatched_sessions[session_name].message)
        if messages:
            raise MismatchedSessionError("; ".join(messages))

def find_all_sessions(botocore_session_full_config=None) -> FindAllSessionsResult:
    if botocore_session_full_config is None:
        botocore_session = botocore.session.Session(session_vars={
            "profile": (None, None, None, None),
            "region": (None, None, None, None),
        })
        botocore_session_full_config = botocore_session.full_config
    
    unique_sessions = {}
    all_sessions = []
    malformed_session_errors = []
    mismatched_sessions = defaultdict(default_factory=list)

    def _add(s: Session):
        if s.session_name not in unique_sessions:
            unique_sessions[s.session_name] = s
        else:
            mismatched_session = _validate_sessions_are_same(unique_sessions[s.session_name], s)
            if mismatched_session:
                mismatched_sessions[s.session_name].append(mismatched_session)
        all_sessions.append(s)

    try:
        specifier = get_specifier()
        if specifier and specifier.session:
            _add(specifier.session)
    except InlineSessionError as e:
        LOGGER.debug(f"Found invalid inline session in specifier: {e}")
        malformed_session_errors.append(e)

    for profile_name in botocore_session_full_config.get("profiles", {}).keys():
        try:
            session = get_session_from_config_profile(
                profile_name=profile_name,
                skip_loading_referenced_sessions=True,
                botocore_session_full_config=botocore_session_full_config
            )
            if not session:
                continue
            _add(session)
        except ConfigProfileError as e:
            LOGGER.debug(f"Config profile {profile_name} has a malformed inline session: {e}")
            malformed_session_errors.append(e)
    
    for session_name in botocore_session_full_config.get("sso_sessions", {}).keys():
        try:
            session = get_session_from_config_session(
                session_name=session_name,
                botocore_session_full_config=botocore_session_full_config
            )
            _add(session)
        except ConfigSessionError as e:
            LOGGER.debug(f"Config session {session_name} is malformed: {e}")
            malformed_session_errors.append(e)
    
    return FindAllSessionsResult(
        unique_sessions=[s for s in unique_sessions.values()],
        all_sessions=all_sessions,
        malformed_session_errors=malformed_session_errors,
        mismatched_sessions=mismatched_sessions
    )

def find_sessions(specifier: Specifier) -> list[Session]:
    sessions = find_all_sessions()
    return sessions.filter(specifier)

class SessionRetrievalError(Exception):
    pass

class ConfigProfileError(SessionRetrievalError):
    pass

def get_session_from_config_profile(
        profile_name: str,
        source: Source=None,
        skip_loading_referenced_sessions: bool=False,
        botocore_session_full_config=None) -> Optional[Session]:
    if botocore_session_full_config is None:
        botocore_session = botocore.session.Session(session_vars={
            "profile": (None, None, None, None),
            "region": (None, None, None, None),
        })
        botocore_session_full_config = botocore_session.full_config
    
    if profile_name not in botocore_session_full_config.get("profiles", {}):
        raise ConfigProfileError(f"Did not find config profile {profile_name}")

    profile_config = botocore_session_full_config.get("profiles", {})[profile_name]
    
    if "sso_session" in profile_config:
        session_name = profile_config["sso_session"]
        if skip_loading_referenced_sessions:
            LOGGER.debug(f"Skipping config profile {profile_name}, which uses config session {session_name}")
            return None
        LOGGER.debug(f"Config profile {profile_name} uses config session {session_name}")
        new_source = Source(
            type="config profile",
            name=profile_name,
            parent=source
        )
        try:
            session = get_session_from_config_session(
                session_name=session_name,
                source=new_source,
                botocore_session_full_config=botocore_session_full_config
            )
        except ConfigSessionError as e:
            raise ConfigProfileError(f"Config profile {profile_name} uses an invalid config session: {str(e)}")
        LOGGER.debug(f"Config profile {profile_name} has session {session}")
        return session

    start_url = profile_config.get("sso_start_url")
    region = profile_config.get("sso_region")

    if not start_url and not region:
        return None

    if not start_url:
        raise ConfigProfileError(f"Config profile {profile_name} is missing fields: sso_start_url")
    
    if not region:
        raise ConfigProfileError(f"Config profile {profile_name} is missing fields: sso_region")

    session = Session(
        session_name=start_url,
        source=Source(
            type="config profile",
            name=profile_name,
            parent=source
        ),
        start_url=start_url,
        region=region
    )
    LOGGER.debug(f"Config profile {profile_name} has inline session {session}")
    return session

class ConfigSessionError(SessionRetrievalError):
    pass

def get_session_from_config_session(
        session_name: str,
        source: Source=None,
        botocore_session_full_config: dict=None) -> Session:
    if botocore_session_full_config is None:
        botocore_session = botocore.session.Session(session_vars={
            "profile": (None, None, None, None),
            "region": (None, None, None, None),
        })
        botocore_session_full_config = botocore_session.full_config
    
    if session_name not in botocore_session_full_config.get("sso_sessions", {}):
        raise ConfigSessionError(f"Did not find config session {session_name}")

    session_config = botocore_session_full_config.get("sso_sessions", {})[session_name]

    start_url = session_config.get("sso_start_url")
    region = session_config.get("sso_region")
    
    missing = []
    if not start_url:
        missing.append("sso_start_url")
    if not region:
        missing.append("sso_region")

    if missing:
        raise ConfigSessionError(f"Config session {session_name} is missing fields: {' '.join(missing)}")
    
    registration_scopes = None
    if "sso_registration_scopes" in session_config:
        raw_registration_scopes = session_config["sso_registration_scopes"]
        try:
            registration_scopes = parse_sso_registration_scopes(raw_registration_scopes)
        except Exception as e:
            raise (f"Config session {session_name} has malformed registration scopes {raw_registration_scopes}")
    
    session = Session(
        session_name=session_name,
        source=Source(
            type="config session",
            name=session_name,
            parent=source
        ),
        start_url=start_url,
        region=region,
        registration_scopes=registration_scopes
    )
    LOGGER.debug(f"Config session {session_name} has session {session}")
    return session
