"""Shared pytest fixtures for aws-sso-lib testing."""

import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Generator
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_aws_config(temp_dir: Path) -> Dict[str, Any]:
    """Create a mock AWS configuration."""
    config = {
        "profiles": {
            "default": {
                "region": "us-east-1"
            },
            "test-sso": {
                "sso_start_url": "https://test.awsapps.com/start",
                "sso_region": "us-east-1",
                "sso_account_id": "123456789012",
                "sso_role_name": "TestRole",
                "region": "us-west-2"
            }
        }
    }
    return config


@pytest.fixture
def mock_sso_cache(temp_dir: Path) -> Path:
    """Create a mock SSO cache directory with sample data."""
    cache_dir = temp_dir / ".aws" / "sso" / "cache"
    cache_dir.mkdir(parents=True)
    
    # Create a mock cache file
    cache_data = {
        "startUrl": "https://test.awsapps.com/start",
        "region": "us-east-1",
        "accessToken": "mock-access-token",
        "expiresAt": "2024-12-31T23:59:59Z"
    }
    
    cache_file = cache_dir / "test-cache.json"
    cache_file.write_text(json.dumps(cache_data))
    
    return cache_dir


@pytest.fixture
def mock_boto3_session():
    """Mock boto3 session for AWS operations."""
    with patch('boto3.Session') as mock_session_class:
        session = Mock()
        mock_session_class.return_value = session
        
        # Mock SSO client
        sso_client = Mock()
        session.client.return_value = sso_client
        
        # Mock common SSO operations
        sso_client.list_accounts.return_value = {
            'accountList': [
                {
                    'accountId': '123456789012',
                    'accountName': 'Test Account',
                    'emailAddress': 'test@example.com'
                }
            ]
        }
        
        sso_client.list_account_roles.return_value = {
            'roleList': [
                {
                    'roleName': 'TestRole',
                    'accountId': '123456789012'
                }
            ]
        }
        
        yield session


@pytest.fixture
def sample_sso_token() -> Dict[str, Any]:
    """Provide a sample SSO token."""
    return {
        "accessToken": "sample-access-token",
        "expiresAt": "2024-12-31T23:59:59Z",
        "startUrl": "https://test.awsapps.com/start",
        "region": "us-east-1"
    }


@pytest.fixture
def mock_webbrowser():
    """Mock webbrowser module to prevent opening actual browser."""
    with patch('webbrowser.open') as mock_open:
        mock_open.return_value = True
        yield mock_open


@pytest.fixture
def mock_time():
    """Mock time-related functions for consistent testing."""
    with patch('time.time') as mock_time:
        mock_time.return_value = 1640995200  # 2022-01-01 00:00:00
        yield mock_time


@pytest.fixture
def capture_stdout():
    """Capture stdout for testing CLI output."""
    from io import StringIO
    import sys
    
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()
    
    yield captured_output
    
    sys.stdout = old_stdout