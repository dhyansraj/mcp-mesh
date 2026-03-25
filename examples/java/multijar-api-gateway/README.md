# Multi-JAR Type Deserialization Test

Reproduces issue where `McpMeshTool<List<PaymentRecord>>` fails when
`PaymentRecord` lives in a separate JAR module.

## Structure

- **multijar-common-dto** - Plain JAR with shared `PaymentRecord` record
- **multijar-payment-service** - `@MeshTool` agent returning `List<PaymentRecord>`
- **multijar-api-gateway** - `@MeshRoute` REST API consuming via `McpMeshTool<List<PaymentRecord>>`

The key difference from `tc10` (which passes): in `tc10`, the `Employee` record
is defined in the **same module** as the consumer controller. Here, `PaymentRecord`
is in a **separate JAR** (`multijar-common-dto`), which ends up in `BOOT-INF/lib/`.

## Build

```bash
# Build common DTO first (install to local Maven)
cd examples/java/multijar-common-dto
mvn install

# Build payment service
cd ../multijar-payment-service
mvn package -DskipTests

# Build API gateway
cd ../multijar-api-gateway
mvn package -DskipTests
```

## Run

```bash
# Terminal 1: Registry
meshctl start --registry-only --debug

# Terminal 2: Payment service
meshctl start examples/java/multijar-payment-service -d

# Terminal 3: API gateway (Spring Boot, not via meshctl)
cd examples/java/multijar-api-gateway
mvn spring-boot:run

# Terminal 4: Test
curl http://localhost:8080/api/payments
curl http://localhost:8080/api/payments/student/S001
```

Expected: `elementType: "PaymentRecord"`
Bug: `elementType: "LinkedHashMap"` or ClassCastException
