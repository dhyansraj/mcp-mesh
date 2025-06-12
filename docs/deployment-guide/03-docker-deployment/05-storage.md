# Persistent Storage

> Manage data persistence and stateful operations for containerized MCP Mesh agents

## Overview

While MCP Mesh agents are typically stateless, many real-world scenarios require persistent data storage - from caching and session state to configuration and logs. This guide covers Docker volume management, data persistence strategies, backup approaches, and best practices for stateful agent deployments.

We'll explore different storage drivers, volume types, data migration strategies, and how to ensure data survives container restarts and updates.

## Key Concepts

- **Docker Volumes**: Managed volumes vs bind mounts
- **Volume Drivers**: Local, NFS, cloud storage plugins
- **Data Lifecycle**: Persistence across container lifecycles
- **Backup Strategies**: Protecting agent data
- **Shared Storage**: Multiple agents accessing same data

## Step-by-Step Guide

### Step 1: Understanding Storage Options

Docker provides several storage mechanisms:

```yaml
# docker-compose.yml
version: "3.8"

services:
  # Named volume (recommended)
  agent-with-volume:
    image: mcp-mesh/agent:latest
    volumes:
      - agent_data:/data # Named volume
      - cache_data:/cache

  # Bind mount (for development)
  agent-with-bind:
    image: mcp-mesh/agent:latest
    volumes:
      - ./local-data:/data # Bind mount
      - ./config:/app/config:ro # Read-only mount

  # tmpfs mount (for temporary data)
  agent-with-tmpfs:
    image: mcp-mesh/agent:latest
    tmpfs:
      - /tmp
      - /run
    volumes:
      - type: tmpfs
        target: /cache
        tmpfs:
          size: 100M

volumes:
  agent_data: # Named volume
    driver: local
  cache_data:
    driver: local
```

### Step 2: Configure Persistent Agent Storage

Implement storage for different agent needs:

```yaml
# docker-compose.storage.yml
version: "3.8"

services:
  # Database agent with persistent data
  database-agent:
    image: mcp-mesh/agent:latest
    environment:
      AGENT_FILE: agents/database_agent.py
      DB_PATH: /data/agent.db
    volumes:
      - db_data:/data
      - db_backups:/backups
    # Ensure data directory has correct permissions
    user: "1000:1000"

  # Cache agent with Redis
  cache-agent:
    image: mcp-mesh/agent:latest
    environment:
      AGENT_FILE: agents/cache_agent.py
      REDIS_DATA_DIR: /data
    volumes:
      - redis_data:/data
      - redis_config:/etc/redis:ro

  # File processing agent
  file-agent:
    image: mcp-mesh/agent:latest
    environment:
      AGENT_FILE: agents/file_processor.py
      INPUT_DIR: /data/input
      OUTPUT_DIR: /data/output
      PROCESSING_DIR: /data/processing
    volumes:
      - file_input:/data/input
      - file_output:/data/output
      - file_processing:/data/processing

  # Analytics agent with time-series data
  analytics-agent:
    image: mcp-mesh/agent:latest
    environment:
      AGENT_FILE: agents/analytics_agent.py
      METRICS_PATH: /data/metrics
      RETENTION_DAYS: 30
    volumes:
      - type: volume
        source: metrics_data
        target: /data/metrics
        volume:
          nocopy: true # Don't copy existing data

volumes:
  db_data:
    driver: local
  db_backups:
    driver: local
  redis_data:
    driver: local
  redis_config:
    driver: local
  file_input:
    driver: local
  file_output:
    driver: local
  file_processing:
    driver: local
  metrics_data:
    driver: local
    driver_opts:
      type: none
      device: /mnt/metrics # Mount specific directory
      o: bind
```

### Step 3: Implement Backup and Recovery

Create backup strategies for agent data:

```yaml
# docker-compose.backup.yml
version: "3.8"

services:
  # Backup service
  backup-agent:
    image: mcp-mesh/backup-agent:latest
    environment:
      BACKUP_SCHEDULE: "0 2 * * *" # 2 AM daily
      BACKUP_RETENTION: 7 # Keep 7 days
      S3_BUCKET: ${BACKUP_BUCKET}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
    volumes:
      # Access all volumes that need backup
      - agent_data:/backup/agent_data:ro
      - db_data:/backup/db_data:ro
      - metrics_data:/backup/metrics_data:ro
      - backup_temp:/tmp

  # Volume backup using restic
  restic-backup:
    image: restic/restic:latest
    environment:
      RESTIC_REPOSITORY: s3:s3.amazonaws.com/bucket/backup
      RESTIC_PASSWORD_FILE: /run/secrets/restic_password
    secrets:
      - restic_password
    volumes:
      - agent_data:/data/agent_data:ro
      - ./backup-scripts:/scripts
    command: ["/scripts/backup.sh"]

volumes:
  backup_temp:
    driver: local

secrets:
  restic_password:
    file: ./secrets/restic_password.txt
```

Backup script example:

```bash
#!/bin/bash
# backup-scripts/backup.sh

set -e

echo "Starting backup at $(date)"

# Initialize repository if needed
restic snapshots || restic init

# Backup each volume
for volume in agent_data db_data metrics_data; do
  echo "Backing up $volume..."
  restic backup /data/$volume \
    --tag "$volume" \
    --tag "$(date +%Y-%m-%d)" \
    --host "docker-compose"
done

# Cleanup old snapshots
restic forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --prune

echo "Backup completed at $(date)"
```

### Step 4: Implement Shared Storage

Configure shared storage for agent collaboration:

```yaml
# docker-compose.shared.yml
version: "3.8"

services:
  # NFS server for shared storage
  nfs-server:
    image: itsthenetwork/nfs-server-alpine:latest
    privileged: true
    environment:
      SHARED_DIRECTORY: /exports
    volumes:
      - shared_data:/exports
    ports:
      - "2049:2049"

  # Agents using shared storage
  agent-1:
    image: mcp-mesh/agent:latest
    volumes:
      - type: volume
        source: nfs_volume
        target: /shared
        volume:
          driver: local
          driver_opts:
            type: nfs
            o: addr=nfs-server,vers=4,soft,rw
            device: ":/exports"

  agent-2:
    image: mcp-mesh/agent:latest
    volumes:
      - type: volume
        source: nfs_volume
        target: /shared
        volume:
          driver: local
          driver_opts:
            type: nfs
            o: addr=nfs-server,vers=4,soft,rw
            device: ":/exports"

  # Using cloud storage (MinIO)
  minio:
    image: minio/minio:latest
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    command: server /data --console-address ":9001"

volumes:
  shared_data:
  nfs_volume:
  minio_data:
```

## Configuration Options

| Option               | Description             | Default   | Example        |
| -------------------- | ----------------------- | --------- | -------------- |
| `volume.driver`      | Volume driver to use    | local     | nfs, glusterfs |
| `volume.driver_opts` | Driver-specific options | -         | type: nfs      |
| `volume.external`    | Use existing volume     | false     | true           |
| `tmpfs.size`         | Size of tmpfs mount     | unlimited | 100M           |
| `bind.propagation`   | Bind propagation mode   | rprivate  | shared         |

## Examples

### Example 1: Stateful ML Agent

```yaml
# docker-compose.ml.yml
version: "3.8"

services:
  ml-training-agent:
    image: mcp-mesh/ml-agent:latest
    environment:
      AGENT_FILE: agents/ml_trainer.py
      MODEL_PATH: /models
      DATASET_PATH: /datasets
      CHECKPOINT_PATH: /checkpoints
    volumes:
      # Large datasets on fast storage
      - type: volume
        source: datasets
        target: /datasets
        volume:
          driver: local
          driver_opts:
            type: none
            device: /nvme/datasets
            o: bind

      # Model storage
      - models:/models

      # Temporary checkpoint storage
      - type: tmpfs
        target: /checkpoints
        tmpfs:
          size: 10G

    # GPU access for training
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  datasets:
    external: true
  models:
    driver: local
```

### Example 2: Event Sourcing Storage

```python
# agents/event_store_agent.py
import os
import json
import time
from pathlib import Path
from mcp_mesh import mesh_agent

class EventStore:
    def __init__(self, base_path="/data/events"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def append_event(self, stream, event):
        """Append event to stream with guaranteed ordering"""
        stream_path = self.base_path / stream
        stream_path.mkdir(exist_ok=True)

        # Use timestamp + sequence for ordering
        timestamp = time.time_ns()
        event_file = stream_path / f"{timestamp}.json"

        # Atomic write
        temp_file = event_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump({
                'timestamp': timestamp,
                'event': event
            }, f)

        # Atomic rename
        temp_file.rename(event_file)

        # Sync to ensure durability
        os.sync()

    def read_stream(self, stream, from_timestamp=0):
        """Read events from stream"""
        stream_path = self.base_path / stream
        if not stream_path.exists():
            return []

        events = []
        for event_file in sorted(stream_path.glob('*.json')):
            timestamp = int(event_file.stem)
            if timestamp >= from_timestamp:
                with open(event_file) as f:
                    events.append(json.load(f))

        return events

@mesh_agent(
    capability="event_store",
    persistent_paths=["/data/events"]
)
def store_event(stream: str, event: dict):
    store = EventStore()
    store.append_event(stream, event)
    return {"status": "stored", "stream": stream}
```

## Best Practices

1. **Use Named Volumes**: Easier to manage than bind mounts
2. **Regular Backups**: Automate backup processes
3. **Volume Labels**: Tag volumes with metadata
4. **Separate Data Types**: Different volumes for different data
5. **Monitor Disk Usage**: Set up alerts for volume capacity

## Common Pitfalls

### Pitfall 1: Permission Issues

**Problem**: Container can't write to volume

**Solution**: Set correct ownership:

```dockerfile
# In Dockerfile
RUN useradd -m -u 1000 appuser
USER appuser

# Or in docker-compose.yml
services:
  agent:
    user: "1000:1000"
    volumes:
      - data:/data
```

### Pitfall 2: Data Loss on Volume Delete

**Problem**: Accidentally deleted volume with important data

**Solution**: Use external volumes for critical data:

```yaml
volumes:
  critical_data:
    external: true # Won't be deleted with stack
    name: production_data
```

## Testing

### Volume Testing Script

```bash
#!/bin/bash
# test_volumes.sh

echo "Testing volume persistence..."

# Create test data
docker-compose exec agent sh -c 'echo "test data" > /data/test.txt'

# Restart container
docker-compose restart agent

# Verify data persists
docker-compose exec agent cat /data/test.txt || {
  echo "ERROR: Data not persisted!"
  exit 1
}

# Test backup
docker-compose run --rm backup-agent /scripts/backup.sh

# Simulate disaster - delete volume
docker-compose down -v
docker volume rm myapp_agent_data

# Restore from backup
docker-compose run --rm backup-agent /scripts/restore.sh

# Verify restored data
docker-compose up -d agent
docker-compose exec agent cat /data/test.txt || {
  echo "ERROR: Restore failed!"
  exit 1
}

echo "Volume tests passed!"
```

### Performance Testing

```python
# tests/test_storage_performance.py
import time
import docker

def test_volume_performance():
    """Compare volume performance"""
    client = docker.from_env()

    tests = {
        'bind_mount': './test-data:/data',
        'named_volume': 'test_volume:/data',
        'tmpfs': {'tmpfs': {'/data': 'size=100M'}}
    }

    for mount_type, mount_config in tests.items():
        if mount_type == 'tmpfs':
            container = client.containers.run(
                'alpine',
                'sh -c "dd if=/dev/zero of=/data/test bs=1M count=100"',
                tmpfs=mount_config['tmpfs'],
                detach=True
            )
        else:
            container = client.containers.run(
                'alpine',
                'sh -c "dd if=/dev/zero of=/data/test bs=1M count=100"',
                volumes=[mount_config],
                detach=True
            )

        start = time.time()
        container.wait()
        duration = time.time() - start

        print(f"{mount_type}: {duration:.2f}s")
        container.remove()
```

## Monitoring and Debugging

### Volume Monitoring

```bash
# Check volume usage
docker system df -v

# Inspect volume details
docker volume inspect agent_data

# Monitor disk I/O
docker exec agent iostat -x 1

# Check volume mount inside container
docker exec agent df -h
docker exec agent mount | grep /data
```

### Storage Debugging

```yaml
# docker-compose.debug.yml
services:
  volume-debugger:
    image: busybox
    volumes:
      - agent_data:/debug/agent_data
      - db_data:/debug/db_data
    command: |
      sh -c "
      while true; do
        echo '=== Volume Status ==='
        du -sh /debug/*
        echo '=== Disk Usage ==='
        df -h /debug
        sleep 60
      done
      "
```

## 🔧 Troubleshooting

### Issue 1: Volume Mount Fails

**Symptoms**: "No such file or directory" or permission denied

**Cause**: Path doesn't exist or permission issues

**Solution**:

```bash
# Create directory first
mkdir -p /path/to/data
chmod 755 /path/to/data

# Or use init container
services:
  init-volumes:
    image: busybox
    volumes:
      - data:/data
    command: |
      sh -c "
      mkdir -p /data/subdir
      chmod -R 777 /data
      "
```

### Issue 2: Slow Volume Performance

**Symptoms**: Agent operations are slow

**Cause**: Storage driver overhead

**Solution**:

```yaml
# Use optimal storage driver
volumes:
  fast_data:
    driver: local
    driver_opts:
      type: none
      device: /dev/nvme0n1p1 # Use fast disk
      o: bind
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Cross-Platform Mounts**: Path differences between Windows/Mac/Linux
- **Volume Drivers**: Not all drivers available on all platforms
- **Live Migration**: Moving volumes between hosts is complex
- **Concurrent Access**: Some filesystems don't handle concurrent writes well

## 📝 TODO

- [ ] Add distributed storage examples (GlusterFS, Ceph)
- [ ] Document volume encryption
- [ ] Add disaster recovery procedures
- [ ] Create volume migration tools
- [ ] Add storage quota management

## Summary

You now understand persistent storage for containerized MCP Mesh agents:

Key takeaways:

- 🔑 Multiple storage options for different use cases
- 🔑 Backup and recovery strategies for data protection
- 🔑 Shared storage for agent collaboration
- 🔑 Performance optimization techniques

## Next Steps

You've completed the Docker deployment section! Consider exploring Kubernetes deployment next.

Continue to [Kubernetes Basics](../04-kubernetes-basics.md) →

---

💡 **Tip**: Use `docker volume prune` carefully - add the `-a` flag to see what would be removed first

📚 **Reference**: [Docker Storage Documentation](https://docs.docker.com/storage/)

🧪 **Try It**: Implement a multi-agent system where agents share processed data through a common volume
