"""Shared pytest fixtures for aws-sso-util testing."""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Generator
from unittest.mock import Mock, patch

import pytest
import yaml


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_aws_config_dir(temp_dir: Path) -> Path:
    """Create a mock AWS config directory structure."""
    config_dir = temp_dir / ".aws"
    config_dir.mkdir()
    
    # Create mock config file
    config_file = config_dir / "config"
    config_file.write_text("""[default]
region = us-east-1

[profile test-profile]
sso_start_url = https://test.awsapps.com/start
sso_region = us-east-1
sso_account_id = 123456789012
sso_role_name = TestRole
region = us-west-2
""")
    
    # Create mock credentials file
    credentials_file = config_dir / "credentials"
    credentials_file.write_text("")
    
    return config_dir


@pytest.fixture
def mock_sso_cache_dir(temp_dir: Path) -> Path:
    """Create a mock SSO cache directory."""
    cache_dir = temp_dir / ".aws" / "sso" / "cache"
    cache_dir.mkdir(parents=True)
    
    # Create a mock cache file
    cache_data = {
        "startUrl": "https://test.awsapps.com/start",
        "region": "us-east-1",
        "accessToken": "mock-access-token",
        "expiresAt": "2024-12-31T23:59:59Z"
    }
    
    cache_file = cache_dir / "mock-cache.json"
    cache_file.write_text(json.dumps(cache_data))
    
    return cache_dir


@pytest.fixture
def mock_sso_config() -> Dict[str, Any]:
    """Provide a mock SSO configuration."""
    return {
        "start_url": "https://test.awsapps.com/start",
        "region": "us-east-1",
        "accounts": [
            {
                "account_id": "123456789012",
                "account_name": "Test Account",
                "roles": ["TestRole", "AdminRole"]
            },
            {
                "account_id": "210987654321",
                "account_name": "Production Account",
                "roles": ["ReadOnlyRole"]
            }
        ]
    }


@pytest.fixture
def mock_boto3_client():
    """Mock boto3 client for AWS SSO operations."""
    with patch('boto3.client') as mock_client:
        client = Mock()
        mock_client.return_value = client
        
        # Mock common SSO operations
        client.list_accounts.return_value = {
            'accountList': [
                {
                    'accountId': '123456789012',
                    'accountName': 'Test Account',
                    'emailAddress': 'test@example.com'
                }
            ]
        }
        
        client.list_account_roles.return_value = {
            'roleList': [
                {
                    'roleName': 'TestRole',
                    'accountId': '123456789012'
                }
            ]
        }
        
        client.get_role_credentials.return_value = {
            'roleCredentials': {
                'accessKeyId': 'MOCK_ACCESS_KEY',
                'secretAccessKey': 'MOCK_SECRET_KEY',
                'sessionToken': 'MOCK_SESSION_TOKEN',
                'expiration': 1234567890
            }
        }
        
        yield client


@pytest.fixture
def mock_environment(monkeypatch):
    """Set up mock environment variables."""
    env_vars = {
        'AWS_CONFIG_FILE': '/tmp/mock/config',
        'AWS_SHARED_CREDENTIALS_FILE': '/tmp/mock/credentials',
        'AWS_SSO_CACHE_DIR': '/tmp/mock/sso/cache'
    }
    
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    
    return env_vars


@pytest.fixture
def sample_yaml_config(temp_dir: Path) -> Path:
    """Create a sample YAML configuration file."""
    config_data = {
        'SSOConfig': {
            'StartUrl': 'https://test.awsapps.com/start',
            'Region': 'us-east-1',
            'Accounts': [
                {
                    'AccountId': '123456789012',
                    'AccountName': 'Test Account',
                    'Roles': ['TestRole', 'AdminRole']
                }
            ]
        }
    }
    
    config_file = temp_dir / "sso-config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f)
    
    return config_file


@pytest.fixture
def mock_click_context():
    """Provide a mock Click context for CLI testing."""
    from click.testing import CliRunner
    runner = CliRunner()
    return runner


@pytest.fixture(autouse=True)
def reset_singleton_instances():
    """Reset any singleton instances between tests."""
    # This fixture runs automatically before each test
    # Add any singleton reset logic here if needed
    yield
    # Cleanup after test if needed


@pytest.fixture
def capture_logs():
    """Capture log output during tests."""
    import logging
    from io import StringIO
    
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    # Get the root logger
    logger = logging.getLogger()
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    
    yield log_capture
    
    # Cleanup
    logger.removeHandler(handler)
    logger.setLevel(original_level)