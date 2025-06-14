"""Validation tests to verify the testing infrastructure is set up correctly."""

import sys
from pathlib import Path

import pytest


class TestSetupValidation:
    """Validate that the testing infrastructure is properly configured."""
    
    @pytest.mark.unit
    def test_pytest_installed(self):
        """Verify pytest is installed and importable."""
        import pytest
        assert pytest.__version__
    
    @pytest.mark.unit
    def test_pytest_cov_installed(self):
        """Verify pytest-cov is installed."""
        import pytest_cov
        assert pytest_cov.__version__
    
    @pytest.mark.unit
    def test_pytest_mock_installed(self):
        """Verify pytest-mock is installed."""
        import pytest_mock
        # pytest-mock doesn't expose __version__, just verify import works
        assert pytest_mock
    
    @pytest.mark.unit
    def test_project_structure(self):
        """Verify the project structure is correct."""
        project_root = Path(__file__).parent.parent
        
        # Check main directories exist
        assert project_root.exists()
        assert (project_root / "src").exists()
        assert (project_root / "src" / "aws_sso_util").exists()
        assert (project_root / "tests").exists()
        assert (project_root / "tests" / "unit").exists()
        assert (project_root / "tests" / "integration").exists()
    
    @pytest.mark.unit
    def test_conftest_fixtures(self, temp_dir, mock_sso_config):
        """Verify conftest fixtures are available."""
        # Test temp_dir fixture
        assert temp_dir.exists()
        assert temp_dir.is_dir()
        
        # Test mock_sso_config fixture
        assert isinstance(mock_sso_config, dict)
        assert "start_url" in mock_sso_config
        assert "region" in mock_sso_config
        assert "accounts" in mock_sso_config
    
    @pytest.mark.unit
    def test_aws_config_fixture(self, mock_aws_config_dir):
        """Verify AWS config fixture creates proper structure."""
        assert mock_aws_config_dir.exists()
        assert (mock_aws_config_dir / "config").exists()
        assert (mock_aws_config_dir / "credentials").exists()
        
        # Verify config content
        config_content = (mock_aws_config_dir / "config").read_text()
        assert "[default]" in config_content
        assert "[profile test-profile]" in config_content
    
    @pytest.mark.unit
    def test_yaml_config_fixture(self, sample_yaml_config):
        """Verify YAML config fixture works correctly."""
        assert sample_yaml_config.exists()
        assert sample_yaml_config.suffix == ".yaml"
        
        import yaml
        with open(sample_yaml_config) as f:
            config = yaml.safe_load(f)
        
        assert "SSOConfig" in config
        assert "StartUrl" in config["SSOConfig"]
    
    @pytest.mark.unit
    def test_mock_boto3_fixture(self, mock_boto3_client):
        """Verify boto3 mock fixture is working."""
        # Test list_accounts
        response = mock_boto3_client.list_accounts()
        assert "accountList" in response
        assert len(response["accountList"]) > 0
        
        # Test get_role_credentials
        creds_response = mock_boto3_client.get_role_credentials()
        assert "roleCredentials" in creds_response
        assert "accessKeyId" in creds_response["roleCredentials"]
    
    @pytest.mark.unit
    def test_click_runner_fixture(self, mock_click_context):
        """Verify Click runner fixture is available."""
        from click.testing import CliRunner
        assert isinstance(mock_click_context, CliRunner)
    
    @pytest.mark.unit
    def test_log_capture_fixture(self, capture_logs):
        """Verify log capture fixture works."""
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info("Test log message")
        
        log_output = capture_logs.getvalue()
        assert "Test log message" in log_output
    
    @pytest.mark.unit 
    def test_markers_defined(self, request):
        """Verify custom markers are properly defined."""
        markers = ["unit", "integration", "slow"]
        config_markers = request.config.getini("markers")
        
        for marker in markers:
            assert any(marker in str(m) for m in config_markers)


@pytest.mark.integration
class TestIntegrationSetup:
    """Basic integration test to verify the setup."""
    
    def test_integration_marker(self):
        """Verify integration marker works."""
        assert True
    
    @pytest.mark.slow
    def test_slow_marker(self):
        """Verify slow marker works."""
        import time
        # Just a quick sleep to demonstrate
        time.sleep(0.1)
        assert True