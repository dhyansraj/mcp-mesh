# MCP Mesh Developer CLI Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the MCP Mesh Developer CLI.

## Table of Contents

- [Quick Diagnostics](#quick-diagnostics)
- [Common Issues](#common-issues)
- [Platform-Specific Issues](#platform-specific-issues)
- [Performance Issues](#performance-issues)
- [Configuration Problems](#configuration-problems)
- [Advanced Debugging](#advanced-debugging)
- [Getting Help](#getting-help)

## Quick Diagnostics

### First Steps

When encountering issues, start with these diagnostic commands:

```bash
# Check overall system status
mcp_mesh_dev status --verbose

# View recent error logs
mcp_mesh_dev logs --level ERROR --lines 100

# Verify configuration
mcp_mesh_dev config show

# Check running processes
mcp_mesh_dev list --json
```

### Health Check Script

Create a quick health check script:

```bash
#!/bin/bash
# health_check.sh

echo "=== MCP Mesh Health Check ==="
echo

echo "1. CLI Version:"
mcp_mesh_dev --version
echo

echo "2. Configuration:"
mcp_mesh_dev config show --format json | head -10
echo

echo "3. Service Status:"
mcp_mesh_dev status 2>/dev/null || echo "ERROR: Status check failed"
echo

echo "4. Running Agents:"
mcp_mesh_dev list 2>/dev/null || echo "ERROR: Agent list failed"
echo

echo "5. Recent Errors:"
mcp_mesh_dev logs --level ERROR --lines 5 2>/dev/null || echo "ERROR: Log access failed"
```

## Common Issues

### 1. Registry Startup Failures

**Symptoms:**

- `mcp_mesh_dev start` fails immediately
- Error messages about port conflicts
- Database connection errors

**Diagnosis:**

```bash
# Check if port is already in use
netstat -tulpn | grep :8080
# or on macOS
lsof -i :8080

# Check database file permissions
ls -la ~/.mcp_mesh/
```

**Solutions:**

**Port Conflict:**

```bash
# Use different port
mcp_mesh_dev start --registry-port 8081

# Or find and stop conflicting process
sudo kill $(lsof -t -i:8080)
```

**Database Issues:**

```bash
# Reset database
mcp_mesh_dev stop
rm ~/.mcp_mesh/dev_registry.db*
mcp_mesh_dev start

# Check permissions
chmod 755 ~/.mcp_mesh/
chmod 644 ~/.mcp_mesh/dev_registry.db
```

**Permission Errors:**

```bash
# Create directory with correct permissions
mkdir -p ~/.mcp_mesh
chmod 755 ~/.mcp_mesh

# Reset configuration
mcp_mesh_dev config reset
```

### 2. Agent Startup Failures

**Symptoms:**

- Agent fails to start
- Agent starts but doesn't register
- Agent crashes immediately

**Diagnosis:**

```bash
# Test agent file directly
python agent_file.py

# Check for syntax errors
python -m py_compile agent_file.py

# Test with debug mode
mcp_mesh_dev start --debug agent_file.py

# Monitor startup logs
mcp_mesh_dev logs --follow --level DEBUG &
mcp_mesh_dev start agent_file.py
```

**Solutions:**

**File Not Found:**

```bash
# Use absolute path
mcp_mesh_dev start /full/path/to/agent.py

# Check current directory
pwd
ls -la agent.py
```

**Python Environment Issues:**

```bash
# Check Python version
python --version

# Check if agent dependencies are installed
pip list | grep required_package

# Use virtual environment
source venv/bin/activate
mcp_mesh_dev start agent.py
```

**Syntax Errors:**

```bash
# Check syntax
python -m py_compile agent.py

# Run with verbose error reporting
python -v agent.py
```

### 3. Agent Registration Problems

**Symptoms:**

- Agent starts but shows as "unregistered"
- Agent appears in process list but not in registry
- Intermittent registration failures

**Diagnosis:**

```bash
# Check agent registration status
mcp_mesh_dev list --json | jq '.[] | {name, registered, status}'

# Monitor registration process
mcp_mesh_dev logs --follow | grep -i register

# Check registry connectivity
curl http://localhost:8080/health 2>/dev/null || echo "Registry not accessible"
```

**Solutions:**

**Network Connectivity:**

```bash
# Test registry endpoint
curl -v http://localhost:8080/agents

# Check firewall settings
sudo ufw status  # Ubuntu
sudo firewall-cmd --list-all  # CentOS/RHEL
```

**Timeout Issues:**

```bash
# Increase startup timeout
mcp_mesh_dev config set startup_timeout 60
mcp_mesh_dev restart-agent agent_name
```

**Registry Issues:**

```bash
# Restart registry
mcp_mesh_dev restart

# Reset registry database
mcp_mesh_dev stop
rm ~/.mcp_mesh/dev_registry.db
mcp_mesh_dev start
```

### 4. Process Management Issues

**Symptoms:**

- Agents don't stop properly
- Orphaned processes remain after shutdown
- Process tracking errors

**Diagnosis:**

```bash
# Check for orphaned processes
ps aux | grep python | grep -v grep

# Check process tracking state
cat ~/.mcp_mesh/processes.json | jq '.'

# Monitor process lifecycle
mcp_mesh_dev logs --follow | grep -E "(start|stop|terminate)"
```

**Solutions:**

**Orphaned Processes:**

```bash
# Force cleanup
mcp_mesh_dev stop --force

# Manual cleanup
pkill -f "python.*agent.py"

# Reset process tracking
rm ~/.mcp_mesh/processes.json
```

**Shutdown Timeout:**

```bash
# Increase shutdown timeout
mcp_mesh_dev config set shutdown_timeout 60
mcp_mesh_dev stop --timeout 60
```

**Process Tracking Corruption:**

```bash
# Reset process state
mcp_mesh_dev stop --force
rm ~/.mcp_mesh/processes.json
mcp_mesh_dev start
```

### 5. Configuration Issues

**Symptoms:**

- Configuration changes don't take effect
- Invalid configuration errors
- Environment variable conflicts

**Diagnosis:**

```bash
# Show effective configuration
mcp_mesh_dev config show --format json

# Check configuration file
cat ~/.mcp_mesh/cli_config.json

# Check environment variables
env | grep MCP_MESH
```

**Solutions:**

**Configuration Precedence:**

```bash
# Clear environment variables
unset $(env | grep MCP_MESH | cut -d= -f1)

# Reset configuration file
mcp_mesh_dev config reset

# Use explicit command-line options
mcp_mesh_dev start --registry-port 8080 --debug
```

**Invalid Values:**

```bash
# Validate configuration
mcp_mesh_dev config show --format json | jq '.'

# Reset to defaults
mcp_mesh_dev config reset

# Set values one by one
mcp_mesh_dev config set registry_port 8080
```

## Platform-Specific Issues

### Linux

**Common Issues:**

1. **Permission Denied Errors:**

```bash
# Fix directory permissions
sudo chown -R $USER:$USER ~/.mcp_mesh
chmod -R 755 ~/.mcp_mesh
```

2. **Systemd Integration:**

```bash
# Create systemd service
cat > ~/.config/systemd/user/mcp-mesh.service << EOF
[Unit]
Description=MCP Mesh Developer CLI
After=network.target

[Service]
Type=forking
ExecStart=/usr/local/bin/mcp_mesh_dev start --background agent.py
ExecStop=/usr/local/bin/mcp_mesh_dev stop
Restart=always

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable mcp-mesh.service
systemctl --user start mcp-mesh.service
```

3. **SELinux Issues:**

```bash
# Check SELinux status
sestatus

# Temporary disable (if needed)
sudo setenforce 0

# Create SELinux policy (recommended)
sudo setsebool -P httpd_can_network_connect 1
```

### macOS

**Common Issues:**

1. **Gatekeeper Warnings:**

```bash
# Allow unsigned binaries (if needed)
sudo spctl --master-disable

# Or add specific exception
sudo spctl --add /path/to/mcp_mesh_dev
```

2. **Path Issues:**

```bash
# Add to PATH in shell profile
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

3. **Homebrew Python Conflicts:**

```bash
# Use system Python
/usr/bin/python3 -m pip install mcp-mesh-runtime

# Or use pyenv
pyenv install 3.11.0
pyenv global 3.11.0
pip install mcp-mesh-runtime
```

### Windows

**Common Issues:**

1. **PowerShell Execution Policy:**

```powershell
# Allow script execution
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

2. **Path Issues:**

```powershell
# Add to PATH
$env:PATH += ";C:\Python39\Scripts"

# Or permanently via System Properties
```

3. **Windows Defender:**

```powershell
# Add exclusion for development directory
Add-MpPreference -ExclusionPath "C:\dev\mcp-mesh"
```

4. **WSL Integration:**

```bash
# Use WSL for development
wsl
cd /mnt/c/dev/mcp-mesh
mcp_mesh_dev start agent.py
```

## Performance Issues

### High CPU Usage

**Diagnosis:**

```bash
# Check resource usage
mcp_mesh_dev status --verbose

# Monitor top processes
top -p $(pgrep -f mcp_mesh_dev)

# Check health check frequency
mcp_mesh_dev config show | grep health_check_interval
```

**Solutions:**

```bash
# Reduce health check frequency
mcp_mesh_dev config set health_check_interval 120

# Disable debug mode
mcp_mesh_dev config set debug_mode false

# Reduce log level
mcp_mesh_dev config set log_level WARNING
```

### High Memory Usage

**Diagnosis:**

```bash
# Check memory usage per process
ps aux --sort=-%mem | head -10

# Monitor over time
watch -n 5 'ps aux | grep python | grep -v grep'

# Check for memory leaks
mcp_mesh_dev logs | grep -i memory
```

**Solutions:**

```bash
# Restart agents periodically
crontab -e
# Add: 0 2 * * * /usr/local/bin/mcp_mesh_dev restart-agent my_agent

# Monitor and alert
#!/bin/bash
MEMORY_USAGE=$(ps aux | grep my_agent | awk '{print $4}')
if (( $(echo "$MEMORY_USAGE > 50.0" | bc -l) )); then
    mcp_mesh_dev restart-agent my_agent
fi
```

### Slow Startup

**Diagnosis:**

```bash
# Measure startup time
time mcp_mesh_dev start agent.py

# Check database size
ls -lh ~/.mcp_mesh/dev_registry.db

# Monitor startup logs
mcp_mesh_dev logs --follow --level DEBUG | grep -i startup
```

**Solutions:**

```bash
# Increase startup timeout
mcp_mesh_dev config set startup_timeout 120

# Clean database
mcp_mesh_dev stop
rm ~/.mcp_mesh/dev_registry.db
mcp_mesh_dev start

# Use SSD for database
mcp_mesh_dev config set db_path /path/to/ssd/registry.db
```

## Configuration Problems

### Environment Variable Conflicts

**Issue:** Command-line options don't work due to environment variables.

**Solution:**

```bash
# Check current environment
env | grep MCP_MESH

# Temporarily clear environment
env -i PATH="$PATH" mcp_mesh_dev start agent.py

# Or unset specific variables
unset MCP_MESH_DEBUG_MODE
unset MCP_MESH_REGISTRY_PORT
```

### Configuration File Corruption

**Issue:** Invalid JSON in configuration file.

**Solution:**

```bash
# Backup current config
cp ~/.mcp_mesh/cli_config.json ~/.mcp_mesh/cli_config.json.backup

# Validate JSON
python -m json.tool ~/.mcp_mesh/cli_config.json

# Reset if invalid
mcp_mesh_dev config reset
```

### Default Port Conflicts

**Issue:** Default port 8080 is already in use.

**Solution:**

```bash
# Find available port
for port in {8081..8090}; do
    if ! netstat -tulpn | grep ":$port "; then
        echo "Port $port is available"
        break
    fi
done

# Set permanent default
mcp_mesh_dev config set registry_port 8081
mcp_mesh_dev config save
```

## Advanced Debugging

### Debug Mode

Enable comprehensive debugging:

```bash
# Enable all debug features
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG
mcp_mesh_dev config set startup_timeout 120

# Start with maximum verbosity
mcp_mesh_dev start --debug agent.py 2>&1 | tee debug.log
```

### Network Debugging

Debug network connectivity issues:

```bash
# Test registry connectivity
curl -v http://localhost:8080/health

# Check network interfaces
ip addr show  # Linux
ifconfig      # macOS

# Monitor network traffic
sudo tcpdump -i lo port 8080  # Monitor localhost traffic

# Test with different IP
mcp_mesh_dev start --registry-host 0.0.0.0 agent.py
```

### Process Debugging

Debug process management issues:

```bash
# Monitor process creation
strace -e trace=clone,execve -f mcp_mesh_dev start agent.py  # Linux
dtruss -f mcp_mesh_dev start agent.py  # macOS

# Monitor file access
strace -e trace=openat -f mcp_mesh_dev start agent.py  # Linux
dtruss -f -n open mcp_mesh_dev start agent.py  # macOS

# Debug signal handling
kill -USR1 $(pgrep -f mcp_mesh_dev)  # Send debug signal
```

### Database Debugging

Debug SQLite database issues:

```bash
# Check database integrity
sqlite3 ~/.mcp_mesh/dev_registry.db "PRAGMA integrity_check;"

# Examine database contents
sqlite3 ~/.mcp_mesh/dev_registry.db ".tables"
sqlite3 ~/.mcp_mesh/dev_registry.db "SELECT * FROM agents;"

# Reset database with backup
mcp_mesh_dev stop
cp ~/.mcp_mesh/dev_registry.db ~/.mcp_mesh/dev_registry.db.backup
rm ~/.mcp_mesh/dev_registry.db
mcp_mesh_dev start
```

### Log Analysis

Analyze logs for patterns:

```bash
# Extract error patterns
mcp_mesh_dev logs --level ERROR | sort | uniq -c | sort -nr

# Timeline analysis
mcp_mesh_dev logs | grep "$(date +%Y-%m-%d)" | head -50

# Agent-specific issues
mcp_mesh_dev logs | grep "agent_name" | grep -i error

# Performance analysis
mcp_mesh_dev logs | grep -E "(timeout|slow|performance)" | tail -20
```

## Getting Help

### Information to Gather

When seeking help, gather this information:

```bash
# System information
uname -a
python --version
mcp_mesh_dev --version

# Configuration
mcp_mesh_dev config show --format json

# Status
mcp_mesh_dev status --verbose --json

# Recent logs
mcp_mesh_dev logs --level ERROR --lines 50

# Process information
mcp_mesh_dev list --json
```

### Log Collection Script

Create a comprehensive log collection script:

```bash
#!/bin/bash
# collect_debug_info.sh

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEBUG_DIR="mcp_mesh_debug_$TIMESTAMP"

mkdir -p "$DEBUG_DIR"

echo "Collecting MCP Mesh debug information..."

# System info
uname -a > "$DEBUG_DIR/system_info.txt"
python --version >> "$DEBUG_DIR/system_info.txt"
mcp_mesh_dev --version >> "$DEBUG_DIR/system_info.txt"

# Configuration
mcp_mesh_dev config show --format json > "$DEBUG_DIR/config.json" 2>&1

# Status
mcp_mesh_dev status --verbose --json > "$DEBUG_DIR/status.json" 2>&1

# Logs
mcp_mesh_dev logs --lines 200 > "$DEBUG_DIR/logs.txt" 2>&1

# Process info
mcp_mesh_dev list --json > "$DEBUG_DIR/agents.json" 2>&1
ps aux | grep -E "(mcp_mesh|python)" > "$DEBUG_DIR/processes.txt"

# Network info
netstat -tulpn | grep -E "(8080|8081|8082)" > "$DEBUG_DIR/network.txt" 2>/dev/null || \
    lsof -i :8080 > "$DEBUG_DIR/network.txt" 2>/dev/null

# File permissions
ls -la ~/.mcp_mesh/ > "$DEBUG_DIR/permissions.txt" 2>&1

# Create archive
tar -czf "mcp_mesh_debug_$TIMESTAMP.tar.gz" "$DEBUG_DIR"
rm -rf "$DEBUG_DIR"

echo "Debug information collected in: mcp_mesh_debug_$TIMESTAMP.tar.gz"
```

### Support Channels

1. **GitHub Issues:** Report bugs and feature requests
2. **Documentation:** Check the latest documentation for updates
3. **Community Forums:** Discuss with other developers
4. **Stack Overflow:** Use tag `mcp-mesh` for questions

### Before Reporting Issues

1. Update to the latest version
2. Check if the issue is reproducible
3. Try with minimal configuration
4. Collect debug information
5. Search existing issues

## Quick Reference

### Emergency Recovery

```bash
# Nuclear option - reset everything
mcp_mesh_dev stop --force
rm -rf ~/.mcp_mesh/
mcp_mesh_dev config reset
mcp_mesh_dev start
```

### Common Commands

```bash
# Status check
mcp_mesh_dev status --verbose

# Full restart
mcp_mesh_dev stop && mcp_mesh_dev start

# Debug startup
mcp_mesh_dev start --debug --log-level DEBUG

# Clean logs
mcp_mesh_dev logs --level ERROR --lines 10
```

### Configuration Reset

```bash
# Reset configuration
mcp_mesh_dev config reset

# Set minimal working config
mcp_mesh_dev config set registry_port 8080
mcp_mesh_dev config set log_level INFO
mcp_mesh_dev config set debug_mode false
```

For more detailed information, see:

- [CLI Reference](CLI_REFERENCE.md)
- [Developer Workflow](DEVELOPER_WORKFLOW.md)
- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
