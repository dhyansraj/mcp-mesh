# Schema-Registry Cross-Runtime Test Fixtures (Issue #547)

Test agents for the schema-aware capability-matching feature, mirrored across
Python, TypeScript, and Java. Each language ships three agents:

| Agent          | Capability                  | Output shape | Purpose                                      |
|----------------|-----------------------------|--------------|----------------------------------------------|
| `producer_good`| `employee_lookup`, `[good]` | `Employee`   | Matches consumer's expected schema           |
| `producer_bad` | `employee_lookup`, `[bad]`  | `Hardware`   | Rogue producer; consumer should evict it     |
| `consumer`     | `schema_aware_lookup_<lang>`| —            | `expectedType=Employee`, `match_mode=subset` |

The `Employee` shape (`name: string`, `dept: string`, `salary: number`) is
identical across runtimes. After Rust normalization it canonicalizes to:

```
sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732
```

The `Hardware` shape (`sku`, `model`, `price`) canonicalizes to:

```
sha256:5f1ac9c41f432516a62aebef8841df800fba29342d114eb3813788d16cfa690c
```

## Test matrix

Pairwise consumer ↔ producer combinations (every consumer should wire to every
language's `producer_good` and reject every language's `producer_bad`):

| Consumer ↓ / Producer → | Python good | Python bad | TS good | TS bad | Java good | Java bad |
|-------------------------|-------------|------------|---------|--------|-----------|----------|
| Python `consumer.py`    | wire        | reject     | wire    | reject | wire      | reject   |
| TS `consumer.ts`        | wire        | reject     | wire    | reject | wire      | reject   |
| Java `ConsumerApp`      | wire        | reject     | wire    | reject | wire      | reject   |

## Ports

Different per language so multiple agents can co-run locally.

|            | producer_good | producer_bad | consumer |
|------------|---------------|--------------|----------|
| Python     | 9100          | 9101         | 9102     |
| TypeScript | 9110          | 9111         | 9112     |
| Java       | 9120          | 9121         | 9122     |

## Running locally

Start the registry first (`meshctl start --registry-only`), then any subset of
producers, then a consumer.

### Python
```bash
cd examples/schema/python
python producer_good.py &
python producer_bad.py &
python consumer.py &
meshctl call lookup_with_schema '{"emp_id": "E1"}' --agent consumer-py
```

### TypeScript
```bash
cd examples/schema/typescript
npm install
npm run good &
npm run bad &
npm run consumer &
meshctl call lookup_with_schema '{"emp_id": "E1"}' --agent consumer-ts
```

### Java
```bash
cd examples/schema/java
mvn clean package -DskipTests
java -jar producer-good/target/producer-good-1.0.0-SNAPSHOT.jar &
java -jar producer-bad/target/producer-bad-1.0.0-SNAPSHOT.jar &
java -jar consumer/target/consumer-1.0.0-SNAPSHOT.jar &
meshctl call lookup_with_schema '{"emp_id": "E1"}' --agent consumer-java
```

## Java `@NotNull` note

The Java schema generator (victools) defaults to nullable fields. To produce
the same canonical hash as Python (Pydantic non-null `str`) and TypeScript
(Zod `z.string()`), Java `String` fields must be annotated with
`jakarta.validation.constraints.@NotNull`. Primitives (`double`) are always
non-null. The producer-good and consumer poms therefore include
`spring-boot-starter-validation` to provide the annotation on the classpath.

If strict-mode hash equality with Python/TS still fails after this change,
the SDK's `MeshSchemaSupport` may need to register the
`JakartaValidationModule` so victools surfaces `@NotNull` as schema-level
non-nullability — this is a known follow-up.
