"""
End-to-End Workflow Tests

Comprehensive tests for complete workflows involving file operations,
MCP protocol communication, mesh integration, and error recovery scenarios.
"""

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from mcp_mesh_runtime.shared.exceptions import (
    TransientError,
)
from mcp_mesh_runtime.shared.types import RetryConfig, RetryStrategy
from mcp_mesh_runtime.tools.file_operations import FileOperations


class WorkflowTestEnvironment:
    """Test environment for end-to-end workflow testing."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(tempfile.mkdtemp())
        self.file_ops: FileOperations | None = None
        self.mock_registry = AsyncMock()
        self.operation_log: list[dict[str, Any]] = []

        # Setup mock registry with services
        self.mock_registry.get_dependency.side_effect = self._mock_get_dependency
        self.mock_registry.register_agent = AsyncMock()
        self.mock_registry.send_heartbeat = AsyncMock()
        self.mock_registry.close = AsyncMock()

        # Track service calls
        self.service_calls: dict[str, list[dict[str, Any]]] = {
            "auth_service": [],
            "audit_logger": [],
            "backup_service": [],
        }

    async def _mock_get_dependency(self, dependency_name: str) -> str | None:
        """Mock dependency resolution with call tracking."""
        service_mapping = {
            "auth_service": "mock-auth-service-v1.0.0",
            "audit_logger": "mock-audit-logger-v1.0.0",
            "backup_service": "mock-backup-service-v1.0.0",
        }

        if dependency_name in service_mapping:
            self.service_calls[dependency_name].append(
                {"timestamp": datetime.now(), "action": "dependency_resolved"}
            )
            return service_mapping[dependency_name]

        return None

    async def setup(self) -> None:
        """Setup test environment."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=self.mock_registry,
        ):
            self.file_ops = FileOperations(
                base_directory=str(self.base_dir),
                max_file_size=10 * 1024 * 1024,  # 10MB
            )

    async def cleanup(self) -> None:
        """Cleanup test environment."""
        if self.file_ops:
            await self.file_ops.cleanup()

        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)

    def log_operation(self, operation: str, **kwargs) -> None:
        """Log operation for analysis."""
        self.operation_log.append(
            {"timestamp": datetime.now(), "operation": operation, **kwargs}
        )

    def create_test_files(self, files: dict[str, str]) -> dict[str, Path]:
        """Create test files in the environment."""
        created_files = {}

        for filename, content in files.items():
            file_path = self.base_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            created_files[filename] = file_path

        return created_files

    def get_service_call_count(self, service: str) -> int:
        """Get number of calls to a service."""
        return len(self.service_calls.get(service, []))


@pytest.fixture
async def workflow_env():
    """Create workflow test environment."""
    env = WorkflowTestEnvironment()
    await env.setup()
    yield env
    await env.cleanup()


class TestDocumentManagementWorkflow:
    """Test complete document management workflows."""

    async def test_document_creation_and_editing_workflow(self, workflow_env):
        """Test complete document creation, editing, and management workflow."""
        env = workflow_env

        # Phase 1: Document Creation
        env.log_operation("phase_1_start", phase="document_creation")

        doc_path = str(env.base_dir / "project_docs" / "README.md")
        initial_content = """# Project Documentation

## Overview
This is the initial version of our project documentation.

## Getting Started
1. Clone the repository
2. Install dependencies
3. Run the application

## Contributing
Please follow our coding standards.
"""

        # Create initial document
        result = await env.file_ops.write_file(doc_path, initial_content)
        assert result is True
        env.log_operation("document_created", path=doc_path, size=len(initial_content))

        # Verify document was created
        created_content = await env.file_ops.read_file(doc_path)
        assert created_content == initial_content

        # Phase 2: Document Discovery and Analysis
        env.log_operation("phase_2_start", phase="document_discovery")

        # List directory to discover documents
        docs_dir = str(env.base_dir / "project_docs")
        entries = await env.file_ops.list_directory(docs_dir, include_details=True)

        assert len(entries) == 1
        readme_entry = entries[0]
        assert readme_entry["name"] == "README.md"
        assert readme_entry["type"] == "file"
        assert readme_entry["size"] > 0

        env.log_operation("document_discovered", entry=readme_entry)

        # Phase 3: Collaborative Editing
        env.log_operation("phase_3_start", phase="collaborative_editing")

        # Simulate multiple edits (like multiple contributors)
        updates = [
            {
                "section": "Installation",
                "content": """
## Installation
```bash
npm install
# or
pip install -r requirements.txt
```
""",
            },
            {
                "section": "API Reference",
                "content": """
## API Reference
### File Operations
- `read_file(path)` - Read file contents
- `write_file(path, content)` - Write file contents
- `list_directory(path)` - List directory contents
""",
            },
            {
                "section": "Examples",
                "content": """
## Examples
See the `examples/` directory for usage examples.
""",
            },
        ]

        current_content = created_content
        for update in updates:
            # Add new section
            current_content += update["content"]

            # Write with backup
            result = await env.file_ops.write_file(
                doc_path, current_content, create_backup=True
            )
            assert result is True

            env.log_operation(
                "document_updated",
                section=update["section"],
                new_size=len(current_content),
            )

            # Verify backup was created
            backup_files = list(
                Path(doc_path).parent.glob(f"{Path(doc_path).name}.backup.*")
            )
            assert len(backup_files) > 0

        # Phase 4: Document Validation
        env.log_operation("phase_4_start", phase="document_validation")

        # Read final document
        final_content = await env.file_ops.read_file(doc_path)

        # Verify all sections are present
        expected_sections = [
            "# Project Documentation",
            "## Installation",
            "## API Reference",
            "## Examples",
        ]
        for section in expected_sections:
            assert section in final_content

        # Verify document structure
        lines = final_content.split("\n")
        header_lines = [line for line in lines if line.startswith("#")]
        assert len(header_lines) >= 6  # Main header + section headers

        env.log_operation(
            "document_validated",
            final_size=len(final_content),
            sections=len(header_lines),
        )

        # Phase 5: Document Publishing
        env.log_operation("phase_5_start", phase="document_publishing")

        # Create published version (copy to different location)
        published_path = str(env.base_dir / "published" / "README.md")
        result = await env.file_ops.write_file(published_path, final_content)
        assert result is True

        # Verify published version
        published_content = await env.file_ops.read_file(published_path)
        assert published_content == final_content

        env.log_operation("document_published", published_path=published_path)

        # Verify service integrations were used
        assert env.get_service_call_count("audit_logger") > 0
        assert env.get_service_call_count("backup_service") > 0

    async def test_configuration_management_workflow(self, workflow_env):
        """Test configuration file management workflow."""
        env = workflow_env

        # Phase 1: Initial Configuration Setup
        configs = {
            "app.json": {
                "name": "MyApplication",
                "version": "1.0.0",
                "environment": "development",
                "features": {
                    "authentication": True,
                    "logging": True,
                    "monitoring": False,
                },
            },
            "database.json": {
                "host": "localhost",
                "port": 5432,
                "database": "myapp_dev",
                "ssl": False,
                "pool_size": 10,
            },
            "services.json": {
                "auth_service": {
                    "url": "http://auth.internal:8080",
                    "timeout": 30,
                    "retries": 3,
                },
                "logging_service": {
                    "url": "http://logs.internal:9090",
                    "level": "INFO",
                },
            },
        }

        config_dir = env.base_dir / "config"
        config_dir.mkdir()

        # Create all configuration files
        for filename, config_data in configs.items():
            config_path = str(config_dir / filename)
            config_json = json.dumps(config_data, indent=2)

            result = await env.file_ops.write_file(config_path, config_json)
            assert result is True

            env.log_operation(
                "config_created", filename=filename, size=len(config_json)
            )

        # Phase 2: Configuration Validation
        # Read and validate each configuration
        for filename, expected_config in configs.items():
            config_path = str(config_dir / filename)
            config_content = await env.file_ops.read_file(config_path)

            parsed_config = json.loads(config_content)
            assert parsed_config == expected_config

            env.log_operation("config_validated", filename=filename)

        # Phase 3: Environment-Specific Updates
        # Update app config for production
        app_config_path = str(config_dir / "app.json")
        app_content = await env.file_ops.read_file(app_config_path)
        app_config = json.loads(app_content)

        # Production updates
        app_config["environment"] = "production"
        app_config["features"]["monitoring"] = True
        app_config["version"] = "1.1.0"

        updated_json = json.dumps(app_config, indent=2)
        result = await env.file_ops.write_file(
            app_config_path, updated_json, create_backup=True
        )
        assert result is True

        env.log_operation(
            "config_updated", filename="app.json", environment="production"
        )

        # Phase 4: Configuration Deployment
        # Copy configurations to deployment directory
        deploy_dir = env.base_dir / "deploy" / "config"
        deploy_dir.mkdir(parents=True)

        config_entries = await env.file_ops.list_directory(str(config_dir))

        for entry in config_entries:
            if entry.endswith(".json"):
                source_path = str(config_dir / entry)
                deploy_path = str(deploy_dir / entry)

                # Read and copy
                content = await env.file_ops.read_file(source_path)
                result = await env.file_ops.write_file(deploy_path, content)
                assert result is True

                env.log_operation(
                    "config_deployed", filename=entry, deploy_path=deploy_path
                )

        # Verify deployment
        deployed_entries = await env.file_ops.list_directory(
            str(deploy_dir), include_details=True
        )
        assert len(deployed_entries) == len(configs)

        # Verify deployed app config has production settings
        deployed_app_path = str(deploy_dir / "app.json")
        deployed_app_content = await env.file_ops.read_file(deployed_app_path)
        deployed_app_config = json.loads(deployed_app_content)

        assert deployed_app_config["environment"] == "production"
        assert deployed_app_config["features"]["monitoring"] is True
        assert deployed_app_config["version"] == "1.1.0"


class TestDataProcessingWorkflow:
    """Test data processing and analysis workflows."""

    async def test_csv_data_processing_workflow(self, workflow_env):
        """Test CSV data processing workflow."""
        env = workflow_env

        # Phase 1: Data Ingestion
        raw_data = """id,name,email,department,salary,hire_date
1,John Doe,john@company.com,Engineering,75000,2023-01-15
2,Jane Smith,jane@company.com,Marketing,65000,2023-02-20
3,Bob Johnson,bob@company.com,Engineering,80000,2022-11-10
4,Alice Brown,alice@company.com,HR,55000,2023-03-05
5,Charlie Wilson,charlie@company.com,Engineering,85000,2022-08-22
6,Diana Davis,diana@company.com,Marketing,60000,2023-01-30
"""

        data_dir = env.base_dir / "data"
        data_dir.mkdir()

        raw_data_path = str(data_dir / "employees_raw.csv")
        result = await env.file_ops.write_file(raw_data_path, raw_data)
        assert result is True

        env.log_operation("data_ingested", path=raw_data_path, records=6)

        # Phase 2: Data Validation and Cleaning
        # Read raw data
        raw_content = await env.file_ops.read_file(raw_data_path)
        lines = raw_content.strip().split("\n")

        # Validate structure
        header = lines[0]
        data_lines = lines[1:]

        assert "id,name,email,department,salary,hire_date" in header
        assert len(data_lines) == 6

        # Process and clean data
        cleaned_lines = []
        cleaned_lines.append(header)  # Keep header

        for line in data_lines:
            fields = line.split(",")
            # Clean email field (normalize domain)
            if len(fields) >= 3:
                email = fields[2]
                if "@company.com" in email:
                    fields[2] = email.replace("@company.com", "@newcompany.com")

            cleaned_lines.append(",".join(fields))

        cleaned_data = "\n".join(cleaned_lines)
        cleaned_data_path = str(data_dir / "employees_cleaned.csv")

        result = await env.file_ops.write_file(cleaned_data_path, cleaned_data)
        assert result is True

        env.log_operation("data_cleaned", path=cleaned_data_path)

        # Phase 3: Data Analysis and Report Generation
        # Analyze data to create summary
        cleaned_content = await env.file_ops.read_file(cleaned_data_path)
        cleaned_lines = cleaned_content.strip().split("\n")[1:]  # Skip header

        # Department analysis
        dept_count = {}
        salary_by_dept = {}

        for line in cleaned_lines:
            fields = line.split(",")
            dept = fields[3]
            salary = int(fields[4])

            if dept not in dept_count:
                dept_count[dept] = 0
                salary_by_dept[dept] = []

            dept_count[dept] += 1
            salary_by_dept[dept].append(salary)

        # Generate analysis report
        report = f"""# Employee Data Analysis Report

## Summary
Total Employees: {len(cleaned_lines)}

## Department Distribution
"""

        for dept, count in dept_count.items():
            avg_salary = sum(salary_by_dept[dept]) / len(salary_by_dept[dept])
            report += (
                f"- {dept}: {count} employees, Average Salary: ${avg_salary:,.2f}\n"
            )

        report += """
## Data Quality
- All email addresses updated to new domain
- All salary fields validated as numeric
- No missing required fields detected
"""

        report_path = str(data_dir / "analysis_report.md")
        result = await env.file_ops.write_file(report_path, report)
        assert result is True

        env.log_operation("report_generated", path=report_path)

        # Phase 4: Data Export and Archive
        # Create export directory
        export_dir = env.base_dir / "export" / datetime.now().strftime("%Y%m%d")
        export_dir.mkdir(parents=True)

        # Copy all processed files to export
        files_to_export = [
            ("employees_cleaned.csv", "employees.csv"),
            ("analysis_report.md", "report.md"),
        ]

        for source_name, export_name in files_to_export:
            source_path = str(data_dir / source_name)
            export_path = str(export_dir / export_name)

            content = await env.file_ops.read_file(source_path)
            result = await env.file_ops.write_file(export_path, content)
            assert result is True

            env.log_operation("file_exported", source=source_name, export=export_name)

        # Verify export
        export_entries = await env.file_ops.list_directory(
            str(export_dir), include_details=True
        )
        assert len(export_entries) == 2

        # Verify exported data integrity
        exported_csv_path = str(export_dir / "employees.csv")
        exported_content = await env.file_ops.read_file(exported_csv_path)
        assert "@newcompany.com" in exported_content
        assert exported_content == cleaned_data


class TestErrorRecoveryWorkflows:
    """Test error recovery and resilience workflows."""

    async def test_network_failure_recovery_workflow(self, workflow_env):
        """Test workflow recovery from network/service failures."""
        env = workflow_env

        # Configure retry settings for testing
        retry_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            initial_delay_ms=100,  # Fast for testing
            max_delay_ms=1000,
            backoff_multiplier=2.0,
            jitter=True,
        )

        # Phase 1: Normal Operation
        test_file = str(env.base_dir / "test_resilience.txt")
        initial_content = "Initial content"

        result = await env.file_ops.write_file(test_file, initial_content)
        assert result is True

        env.log_operation("normal_operation", path=test_file)

        # Phase 2: Simulate Service Failures
        failure_count = 0
        original_write = env.file_ops.write_file

        async def failing_write(*args, **kwargs):
            nonlocal failure_count
            failure_count += 1

            if failure_count <= 2:  # Fail first 2 attempts
                env.log_operation("operation_failed", attempt=failure_count)
                raise TransientError("Simulated network failure", retry_delay=0.1)

            # Succeed on 3rd attempt
            env.log_operation("operation_succeeded", attempt=failure_count)
            return await original_write(*args, **kwargs)

        # Patch write_file to simulate failures
        with patch.object(env.file_ops, "write_file", failing_write):

            # This should eventually succeed after retries
            updated_content = "Updated content after failures"
            result = await env.file_ops._execute_with_retry(
                lambda: env.file_ops.write_file(test_file, updated_content),
                retry_config,
            )
            assert result is True

        # Verify the operation eventually succeeded
        final_content = await env.file_ops.read_file(test_file)
        assert final_content == updated_content

        # Verify retry attempts
        assert failure_count == 3  # 2 failures + 1 success

        env.log_operation("recovery_completed", total_attempts=failure_count)

    async def test_rate_limit_recovery_workflow(self, workflow_env):
        """Test recovery from rate limiting."""
        env = workflow_env

        # Temporarily reduce rate limits for testing
        original_max_ops = env.file_ops._max_operations_per_minute
        original_window = env.file_ops._rate_limit_window

        env.file_ops._max_operations_per_minute = 3
        env.file_ops._rate_limit_window = 1  # 1 second window

        try:
            # Phase 1: Rapid Operations to Trigger Rate Limiting
            test_files = []
            for i in range(5):  # More than rate limit
                file_path = str(env.base_dir / f"rate_test_{i}.txt")
                test_files.append(file_path)

            # Perform rapid writes
            operations = []
            for i, file_path in enumerate(test_files):
                operation = env.file_ops.write_file(file_path, f"content {i}")
                operations.append(operation)
                env.log_operation("operation_queued", file_index=i)

            # Some operations should succeed, others should hit rate limit
            results = await asyncio.gather(*operations, return_exceptions=True)

            # Check results
            successful_ops = [r for r in results if r is True]
            failed_ops = [r for r in results if isinstance(r, Exception)]

            # Should have some successes and some rate limit errors
            assert len(successful_ops) > 0
            env.log_operation(
                "rate_limit_results",
                successful=len(successful_ops),
                failed=len(failed_ops),
            )

            # Phase 2: Wait and Retry Failed Operations
            if failed_ops:
                # Wait for rate limit window to reset
                await asyncio.sleep(1.5)

                # Retry failed operations
                retry_operations = []
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        file_path = test_files[i]
                        retry_op = env.file_ops.write_file(
                            file_path, f"retry content {i}"
                        )
                        retry_operations.append(retry_op)
                        env.log_operation("operation_retried", file_index=i)

                if retry_operations:
                    retry_results = await asyncio.gather(
                        *retry_operations, return_exceptions=True
                    )

                    # All retries should succeed after rate limit reset
                    retry_successes = [r for r in retry_results if r is True]
                    env.log_operation(
                        "retry_completed",
                        retry_attempts=len(retry_operations),
                        retry_successes=len(retry_successes),
                    )

        finally:
            # Restore original rate limits
            env.file_ops._max_operations_per_minute = original_max_ops
            env.file_ops._rate_limit_window = original_window

    async def test_partial_failure_recovery_workflow(self, workflow_env):
        """Test recovery from partial operation failures."""
        env = workflow_env

        # Phase 1: Batch Operation Setup
        batch_size = 10
        batch_files = []

        for i in range(batch_size):
            file_path = str(env.base_dir / f"batch_{i:02d}.txt")
            batch_files.append((file_path, f"Batch content {i}"))

        env.log_operation("batch_prepared", size=batch_size)

        # Phase 2: Execute Batch with Some Failures
        failure_indices = {3, 7}  # Simulate failures at indices 3 and 7

        async def selective_write(path: str, content: str, **kwargs):
            # Extract index from filename
            filename = Path(path).name
            index = int(filename.split("_")[1].split(".")[0])

            if index in failure_indices:
                env.log_operation("operation_failed", index=index, path=path)
                raise TransientError(f"Simulated failure for file {index}")

            # Normal operation
            return await env.file_ops.write_file(path, content, **kwargs)

        # Execute batch operations
        batch_results = []
        for i, (file_path, content) in enumerate(batch_files):
            try:
                await selective_write(file_path, content)
                batch_results.append((i, True, None))
                env.log_operation("operation_succeeded", index=i)
            except Exception as e:
                batch_results.append((i, False, e))
                env.log_operation("operation_recorded_failure", index=i, error=str(e))

        # Phase 3: Identify and Retry Failures
        failed_operations = [
            (i, path, content)
            for (i, success, error), (path, content) in zip(
                batch_results, batch_files, strict=False
            )
            if not success
        ]

        assert len(failed_operations) == len(failure_indices)

        env.log_operation("failures_identified", count=len(failed_operations))

        # Retry failed operations
        retry_results = []
        for i, file_path, content in failed_operations:
            try:
                # Direct retry (simulating resolution of transient issue)
                await env.file_ops.write_file(file_path, content)
                retry_results.append((i, True, None))
                env.log_operation("retry_succeeded", index=i)
            except Exception as e:
                retry_results.append((i, False, e))
                env.log_operation("retry_failed", index=i, error=str(e))

        # Phase 4: Verify Final State
        # Check successful operations
        successful_indices = {i for i, success, _ in batch_results if success}
        retried_successful_indices = {i for i, success, _ in retry_results if success}

        all_successful_indices = successful_indices | retried_successful_indices

        # Verify files exist for all successful operations
        for i in all_successful_indices:
            file_path = batch_files[i][0]
            expected_content = batch_files[i][1]

            content = await env.file_ops.read_file(file_path)
            assert content == expected_content

        env.log_operation(
            "recovery_verified",
            total_files=batch_size,
            successful_on_first_try=len(successful_indices),
            successful_on_retry=len(retried_successful_indices),
            final_success_count=len(all_successful_indices),
        )

        # Should have succeeded for all files
        assert len(all_successful_indices) == batch_size


class TestConcurrentWorkflows:
    """Test concurrent workflow execution."""

    async def test_multi_user_document_editing(self, workflow_env):
        """Test concurrent document editing by multiple users."""
        env = workflow_env

        # Setup shared document
        shared_doc_path = str(env.base_dir / "shared_document.md")
        initial_content = """# Shared Document

## Introduction
This document is edited by multiple users concurrently.
"""

        result = await env.file_ops.write_file(shared_doc_path, initial_content)
        assert result is True

        # Simulate multiple users editing different sections
        user_edits = [
            {
                "user": "user1",
                "section": "\n## Section A\nContent from User 1\n",
                "delay": 0.1,
            },
            {
                "user": "user2",
                "section": "\n## Section B\nContent from User 2\n",
                "delay": 0.2,
            },
            {
                "user": "user3",
                "section": "\n## Section C\nContent from User 3\n",
                "delay": 0.15,
            },
        ]

        async def user_edit_workflow(user_edit: dict[str, Any]):
            """Simulate individual user editing workflow."""
            user = user_edit["user"]
            section = user_edit["section"]
            delay = user_edit["delay"]

            env.log_operation("user_edit_start", user=user)

            # Simulate thinking/typing time
            await asyncio.sleep(delay)

            # Read current document
            current_content = await env.file_ops.read_file(shared_doc_path)
            env.log_operation("document_read", user=user, size=len(current_content))

            # Add user's section
            updated_content = current_content + section

            # Write updated document with backup
            result = await env.file_ops.write_file(
                shared_doc_path, updated_content, create_backup=True
            )

            env.log_operation("user_edit_complete", user=user, result=result)
            return result

        # Execute concurrent edits
        edit_tasks = [user_edit_workflow(edit) for edit in user_edits]
        edit_results = await asyncio.gather(*edit_tasks)

        # All edits should succeed
        assert all(edit_results)

        # Verify final document contains all contributions
        final_content = await env.file_ops.read_file(shared_doc_path)

        # Check that content from all users is present
        for user_edit in user_edits:
            user = user_edit["user"]
            # The section should be present (though order may vary due to concurrency)
            assert f"Content from {user.replace('user', 'User ')}" in final_content

        env.log_operation(
            "concurrent_editing_completed",
            users=len(user_edits),
            final_size=len(final_content),
        )

    async def test_parallel_data_processing_workflows(self, workflow_env):
        """Test parallel processing of multiple data workflows."""
        env = workflow_env

        # Setup multiple datasets
        datasets = [
            {
                "name": "sales_data",
                "data": "date,product,amount,region\n2023-01-01,Widget A,1000,North\n2023-01-01,Widget B,1500,South\n2023-01-02,Widget A,800,East\n",
            },
            {
                "name": "customer_data",
                "data": "id,name,email,region\n1,John Doe,john@test.com,North\n2,Jane Smith,jane@test.com,South\n3,Bob Johnson,bob@test.com,East\n",
            },
            {
                "name": "inventory_data",
                "data": "product,stock,location\nWidget A,100,Warehouse1\nWidget B,75,Warehouse1\nWidget C,50,Warehouse2\n",
            },
        ]

        async def process_dataset_workflow(dataset: dict[str, str]):
            """Process individual dataset workflow."""
            name = dataset["name"]
            data = dataset["data"]

            env.log_operation("dataset_processing_start", dataset=name)

            # Phase 1: Save raw data
            raw_path = str(env.base_dir / f"{name}_raw.csv")
            result = await env.file_ops.write_file(raw_path, data)
            assert result is True

            # Phase 2: Process data
            lines = data.strip().split("\n")
            header = lines[0]
            data_lines = lines[1:]

            # Simple processing: add row numbers
            processed_lines = [f"row_id,{header}"]
            for i, line in enumerate(data_lines, 1):
                processed_lines.append(f"{i},{line}")

            processed_data = "\n".join(processed_lines)

            # Phase 3: Save processed data
            processed_path = str(env.base_dir / f"{name}_processed.csv")
            result = await env.file_ops.write_file(processed_path, processed_data)
            assert result is True

            # Phase 4: Generate summary
            summary = f"""# {name.replace('_', ' ').title()} Summary

## Raw Data
- Records: {len(data_lines)}
- Columns: {len(header.split(','))}

## Processing
- Added row IDs
- Validated data format

## Output
- Processed file: {name}_processed.csv
- Processing completed successfully
"""

            summary_path = str(env.base_dir / f"{name}_summary.md")
            result = await env.file_ops.write_file(summary_path, summary)
            assert result is True

            env.log_operation(
                "dataset_processing_complete", dataset=name, records=len(data_lines)
            )

            return {
                "dataset": name,
                "records": len(data_lines),
                "raw_path": raw_path,
                "processed_path": processed_path,
                "summary_path": summary_path,
            }

        # Execute parallel processing
        processing_tasks = [process_dataset_workflow(dataset) for dataset in datasets]
        processing_results = await asyncio.gather(*processing_tasks)

        # Verify all datasets were processed
        assert len(processing_results) == len(datasets)

        # Verify all output files exist and are correct
        for result in processing_results:
            dataset_name = result["dataset"]

            # Check processed file
            processed_content = await env.file_ops.read_file(result["processed_path"])
            assert "row_id," in processed_content
            assert dataset_name.replace("_", " ") in processed_content.lower()

            # Check summary file
            summary_content = await env.file_ops.read_file(result["summary_path"])
            assert "Summary" in summary_content
            assert str(result["records"]) in summary_content

        # Phase 5: Create consolidated report
        consolidated_report = """# Data Processing Report

## Overview
Parallel processing completed for multiple datasets.

## Dataset Summary
"""

        total_records = 0
        for result in processing_results:
            dataset_name = result["dataset"]
            records = result["records"]
            total_records += records

            consolidated_report += f"- {dataset_name}: {records} records\n"

        consolidated_report += f"""
## Totals
- Total Datasets: {len(processing_results)}
- Total Records: {total_records}
- Processing Status: Complete
"""

        report_path = str(env.base_dir / "consolidated_report.md")
        result = await env.file_ops.write_file(report_path, consolidated_report)
        assert result is True

        env.log_operation(
            "parallel_processing_completed",
            datasets=len(datasets),
            total_records=total_records,
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
