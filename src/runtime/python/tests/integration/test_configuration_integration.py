"""Integration tests for configuration management."""

import json
import os
from unittest.mock import patch

import pytest
import yaml

from mcp_mesh import (
    DatabaseConfig,
    DatabaseType,
    InvalidConfigurationError,
    LogLevel,
    MissingConfigurationError,
    RegistryConfig,
    RegistryMode,
    SecurityConfig,
    SecurityMode,
    ServerConfig,
    ServiceDiscoveryConfig,
)
from mcp_mesh.runtime.shared.configuration import (
    CompositeConfigProvider,
    ConfigurationManager,
    FileConfigProvider,
    config_manager,
)


class TestFileConfigProvider:
    """Test FileConfigProvider functionality."""

    def test_load_yaml_config(self, tmp_path):
        """Test loading configuration from YAML file."""
        config_data = {
            "mode": "standalone",
            "environment": "test",
            "debug": True,
            "server": {
                "host": "0.0.0.0",
                "port": 9000,
                "workers": 4,
                "enable_ssl": True,
                "ssl_cert_path": "/path/to/cert.pem",
                "ssl_key_path": "/path/to/key.pem",
            },
            "database": {
                "database_type": "sqlite",
                "database_path": "test.db",
                "connection_timeout": 60,
            },
            "security": {
                "mode": "api_key",
                "api_keys": ["test-key-1", "test-key-2"],
            },
            "monitoring": {
                "log_level": "DEBUG",
                "enable_metrics": True,
                "metrics_port": 9091,
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        provider = FileConfigProvider(config_file)
        config = provider.load_config()

        assert config.mode == RegistryMode.STANDALONE
        assert config.environment == "test"
        assert config.debug is True
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 9000
        assert config.server.workers == 4
        assert config.server.enable_ssl is True
        assert config.database.database_type == DatabaseType.SQLITE
        assert config.database.database_path == "test.db"
        assert config.security.mode == SecurityMode.API_KEY
        assert config.security.api_keys == ["test-key-1", "test-key-2"]
        assert config.monitoring.log_level == LogLevel.DEBUG
        assert config.monitoring.enable_metrics is True

    def test_load_json_config(self, tmp_path):
        """Test loading configuration from JSON file."""
        config_data = {
            "mode": "clustered",
            "server": {
                "host": "localhost",
                "port": 8080,
            },
            "database": {
                "database_type": "postgresql",
                "connection_string": "postgresql://user:pass@localhost/db",
            },
        }

        config_file = tmp_path / "config.json"
        with open(config_file, "w") as f:
            json.dump(config_data, f)

        provider = FileConfigProvider(config_file)
        config = provider.load_config()

        assert config.mode == RegistryMode.CLUSTERED
        assert config.server.host == "localhost"
        assert config.server.port == 8080
        assert config.database.database_type == DatabaseType.POSTGRESQL
        assert (
            config.database.connection_string == "postgresql://user:pass@localhost/db"
        )

    def test_save_yaml_config(self, tmp_path):
        """Test saving configuration to YAML file."""
        config = RegistryConfig(
            mode=RegistryMode.FEDERATED,
            environment="production",
            debug=False,
            server=ServerConfig(
                host="0.0.0.0",
                port=8443,
                enable_ssl=True,
            ),
            security=SecurityConfig(
                mode=SecurityMode.JWT,
                jwt_secret="secret-key",
            ),
        )

        config_file = tmp_path / "output.yaml"
        provider = FileConfigProvider(config_file, create_if_missing=True)

        provider.save_config(config)

        # Verify the saved content
        with open(config_file) as f:
            saved_data = yaml.safe_load(f)

        assert saved_data["mode"] == "federated"
        assert saved_data["environment"] == "production"
        assert saved_data["debug"] is False
        assert saved_data["server"]["host"] == "0.0.0.0"
        assert saved_data["server"]["port"] == 8443
        assert saved_data["server"]["enable_ssl"] is True
        assert saved_data["security"]["mode"] == "jwt"
        assert saved_data["security"]["jwt_secret"] == "secret-key"

    def test_validate_config(self, tmp_path):
        """Test configuration validation."""
        config_file = tmp_path / "config.yaml"
        config_file.touch()
        provider = FileConfigProvider(config_file)

        # Valid configuration
        valid_config = RegistryConfig(
            server=ServerConfig(port=8000),
            database=DatabaseConfig(connection_timeout=30),
        )
        assert provider.validate_config(valid_config) is True

        # Invalid port
        invalid_config = RegistryConfig(
            server=ServerConfig(port=70000),  # Invalid port
        )
        assert provider.validate_config(invalid_config) is False

        # Invalid timeout
        invalid_config2 = RegistryConfig(
            database=DatabaseConfig(connection_timeout=-1),  # Invalid timeout
        )
        assert provider.validate_config(invalid_config2) is False

    def test_missing_file_error(self):
        """Test error handling for missing configuration file."""
        with pytest.raises(MissingConfigurationError):
            FileConfigProvider("/nonexistent/config.yaml")

    def test_invalid_yaml_error(self, tmp_path):
        """Test error handling for invalid YAML."""
        config_file = tmp_path / "invalid.yaml"
        with open(config_file, "w") as f:
            f.write("invalid: yaml: content: [")

        provider = FileConfigProvider(config_file)
        with pytest.raises(InvalidConfigurationError):
            provider.load_config()

    def test_unsupported_format_error(self, tmp_path):
        """Test error handling for unsupported file format."""
        config_file = tmp_path / "config.txt"
        config_file.write_text("test content")

        provider = FileConfigProvider(config_file)
        with pytest.raises(InvalidConfigurationError):
            provider.load_config()


class TestCompositeConfigProvider:
    """Test CompositeConfigProvider functionality."""

    def test_composite_config_loading(self, tmp_path):
        """Test loading configuration from multiple providers."""
        # Create base config file
        base_config = {
            "server": {"host": "localhost", "port": 8000},
            "database": {"database_path": "base.db"},
        }
        base_file = tmp_path / "base.yaml"
        with open(base_file, "w") as f:
            yaml.safe_dump(base_config, f)

        # Create override config file
        override_config = {
            "server": {"port": 9000, "workers": 4},
            "security": {"mode": "api_key"},
        }
        override_file = tmp_path / "override.yaml"
        with open(override_file, "w") as f:
            yaml.safe_dump(override_config, f)

        # Create composite provider
        providers = [
            FileConfigProvider(base_file),
            FileConfigProvider(override_file),
        ]
        composite = CompositeConfigProvider(providers)

        config = composite.load_config()

        # Verify merged configuration
        assert config.server.host == "localhost"  # From base
        assert config.server.port == 9000  # Overridden
        assert config.server.workers == 4  # From override
        assert config.database.database_path == "base.db"  # From base
        assert config.security.mode == SecurityMode.API_KEY  # From override

    def test_empty_providers_error(self):
        """Test error handling for empty providers list."""
        composite = CompositeConfigProvider([])
        with pytest.raises(MissingConfigurationError):
            composite.load_config()


class TestConfigurationManager:
    """Test ConfigurationManager functionality."""

    def test_load_from_file(self, tmp_path):
        """Test loading configuration from file through manager."""
        config_data = {
            "mode": "standalone",
            "server": {"host": "127.0.0.1", "port": 8888},
        }
        config_file = tmp_path / "manager_config.yaml"
        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        manager = ConfigurationManager()
        config = manager.load_from_file(config_file)

        assert config.mode == RegistryMode.STANDALONE
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 8888

        # Test get_config returns the same instance
        assert manager.get_config() is config

    def test_load_from_environment(self):
        """Test loading configuration from environment variables."""
        env_vars = {
            "MCP_MESH_HOST": "10.0.0.1",
            "MCP_MESH_PORT": "7000",
            "MCP_MESH_WORKERS": "8",
            "MCP_MESH_ENABLE_SSL": "true",
            "MCP_MESH_DB_PATH": "env_test.db",
            "MCP_MESH_SECURITY_MODE": "jwt",
            "MCP_MESH_JWT_SECRET": "env-secret",
            "MCP_MESH_ENVIRONMENT": "testing",
            "MCP_MESH_DEBUG": "true",
        }

        with patch.dict(os.environ, env_vars):
            manager = ConfigurationManager()
            config = manager.load_from_environment()

            assert config.server.host == "10.0.0.1"
            assert config.server.port == 7000
            assert config.server.workers == 8
            assert config.server.enable_ssl is True
            assert config.database.database_path == "env_test.db"
            assert config.security.mode == SecurityMode.JWT
            assert config.security.jwt_secret == "env-secret"
            assert config.environment == "testing"
            assert config.debug is True

    def test_default_config(self):
        """Test getting default configuration when none loaded."""
        manager = ConfigurationManager()
        config = manager.get_config()

        # Should return default configuration
        assert isinstance(config, RegistryConfig)
        assert config.mode == RegistryMode.STANDALONE
        assert config.server.host == "localhost"
        assert config.server.port == 8000
        assert config.environment == "development"
        assert config.debug is False

    def test_update_config(self):
        """Test updating configuration values."""
        manager = ConfigurationManager()
        manager.update_config(environment="production", debug=False)

        config = manager.get_config()
        assert config.environment == "production"
        assert config.debug is False

    def test_validate_config(self, tmp_path):
        """Test configuration validation through manager."""
        # Create valid config
        config_data = {
            "server": {"host": "localhost", "port": 8000},
            "database": {"connection_timeout": 30},
        }
        config_file = tmp_path / "valid_config.yaml"
        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        manager = ConfigurationManager()
        manager.load_from_file(config_file)

        assert manager.validate_config() is True


class TestGlobalConfigManager:
    """Test global configuration manager instance."""

    def test_global_config_manager(self):
        """Test that global config manager works correctly."""
        # Reset the global manager
        config_manager._config = None
        config_manager._provider = None

        # Test default behavior
        config = config_manager.get_config()
        assert isinstance(config, RegistryConfig)
        assert config.mode == RegistryMode.STANDALONE

    def test_global_config_persistence(self):
        """Test that global config manager maintains state."""
        # Reset the global manager
        config_manager._config = None
        config_manager._provider = None

        # Update configuration
        config_manager.update_config(environment="test")

        # Get config again - should maintain the update
        config = config_manager.get_config()
        assert config.environment == "test"


class TestIntegrationWithExistingSystem:
    """Test integration with existing MCP Mesh components."""

    def test_database_config_compatibility(self):
        """Test that new config system is compatible with existing database config."""
        config = RegistryConfig(
            database=DatabaseConfig(
                database_path="test_integration.db",
                connection_timeout=45,
                busy_timeout=6000,
                journal_mode="WAL",
                synchronous="NORMAL",
                cache_size=15000,
                enable_foreign_keys=True,
            )
        )

        # Verify all expected fields are present and accessible
        db_config = config.database
        assert db_config.database_path == "test_integration.db"
        assert db_config.connection_timeout == 45
        assert db_config.busy_timeout == 6000
        assert db_config.journal_mode == "WAL"
        assert db_config.synchronous == "NORMAL"
        assert db_config.cache_size == 15000
        assert db_config.enable_foreign_keys is True

    def test_server_config_integration(self):
        """Test server configuration integration."""
        config = RegistryConfig(
            server=ServerConfig(
                host="0.0.0.0",
                port=8080,
                workers=2,
                max_connections=200,
                timeout=60,
                enable_ssl=True,
                ssl_cert_path="/path/to/cert.pem",
                ssl_key_path="/path/to/key.pem",
                enable_cors=True,
                cors_origins=["http://localhost:3000"],
                rate_limit_enabled=True,
                rate_limit_requests=50,
                rate_limit_window=30,
            )
        )

        server_config = config.server
        assert server_config.host == "0.0.0.0"
        assert server_config.port == 8080
        assert server_config.workers == 2
        assert server_config.enable_ssl is True
        assert server_config.rate_limit_enabled is True

    def test_security_config_features(self):
        """Test security configuration features."""
        config = RegistryConfig(
            security=SecurityConfig(
                mode=SecurityMode.JWT,
                api_keys=["key1", "key2"],
                jwt_secret="super-secret-key",
                jwt_expiration=7200,
                tls_ca_cert="/path/to/ca.pem",
                require_client_cert=True,
                allowed_hosts=["*.example.com"],
                enable_audit_log=True,
                audit_log_path="/var/log/mcp-mesh-audit.log",
            )
        )

        security_config = config.security
        assert security_config.mode == SecurityMode.JWT
        assert security_config.jwt_secret == "super-secret-key"
        assert security_config.require_client_cert is True
        assert security_config.enable_audit_log is True

    def test_service_discovery_config(self):
        """Test service discovery configuration."""
        config = RegistryConfig(
            discovery=ServiceDiscoveryConfig(
                enable_caching=True,
                cache_ttl=600,
                registry_timeout=45,
                max_retries=5,
                retry_delay=2.0,
                health_check_enabled=True,
                health_check_interval=30,
                health_check_timeout=15,
                agent_registration_ttl=7200,
                auto_refresh_enabled=True,
                refresh_interval=120,
            )
        )

        discovery_config = config.discovery
        assert discovery_config.enable_caching is True
        assert discovery_config.cache_ttl == 600
        assert discovery_config.max_retries == 5
        assert discovery_config.health_check_enabled is True


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary configuration file for testing."""
    config_data = {
        "mode": "standalone",
        "environment": "test",
        "server": {
            "host": "localhost",
            "port": 8000,
        },
        "database": {
            "database_path": "test.db",
        },
    }

    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.safe_dump(config_data, f)

    return config_file


class TestEndToEndConfiguration:
    """End-to-end configuration testing scenarios."""

    def test_full_configuration_workflow(self, temp_config_file):
        """Test complete configuration workflow from file to usage."""
        # Load configuration
        manager = ConfigurationManager()
        config = manager.load_from_file(temp_config_file)

        # Verify loaded configuration
        assert config.mode == RegistryMode.STANDALONE
        assert config.environment == "test"
        assert config.server.host == "localhost"
        assert config.server.port == 8000

        # Update configuration
        manager.update_config(debug=True)
        updated_config = manager.get_config()
        assert updated_config.debug is True

        # Validate configuration
        assert manager.validate_config() is True

        # Save configuration (create new file since original might be read-only)
        new_file = temp_config_file.parent / "updated_config.yaml"
        new_manager = ConfigurationManager()
        new_manager._config = updated_config
        new_manager._provider = FileConfigProvider(new_file, create_if_missing=True)
        new_manager.save_config()

        # Verify saved configuration
        reloaded_manager = ConfigurationManager()
        reloaded_config = reloaded_manager.load_from_file(new_file)
        assert reloaded_config.debug is True
        assert reloaded_config.environment == "test"

    def test_hierarchical_configuration_loading(self, tmp_path):
        """Test loading configuration with hierarchy: defaults -> file -> env -> cli."""
        # Create base configuration file
        base_config = {
            "server": {"host": "localhost", "port": 8000, "workers": 1},
            "database": {"database_path": "base.db"},
            "debug": False,
        }
        base_file = tmp_path / "base.yaml"
        with open(base_file, "w") as f:
            yaml.safe_dump(base_config, f)

        # Create environment override
        env_vars = {
            "MCP_MESH_PORT": "9000",
            "MCP_MESH_WORKERS": "4",
            "MCP_MESH_DEBUG": "true",
        }

        with patch.dict(os.environ, env_vars):
            # Create providers in priority order
            from mcp_mesh import EnvironmentConfigProvider

            providers = [
                FileConfigProvider(base_file),
                EnvironmentConfigProvider(),
            ]

            composite = CompositeConfigProvider(providers)
            config = composite.load_config()

            # Verify hierarchical override
            assert config.server.host == "localhost"  # From file
            assert config.server.port == 9000  # From environment
            assert config.server.workers == 4  # From environment
            assert config.database.database_path == "base.db"  # From file
            assert config.debug is True  # From environment
