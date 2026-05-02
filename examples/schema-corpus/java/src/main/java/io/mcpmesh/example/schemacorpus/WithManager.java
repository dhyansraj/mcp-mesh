package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;

/**
 * Pattern 10: Inheritance — Manager extends EmployeeBase, flattened.
 *
 * <p>victools/jsonschema-generator inlines inherited fields by default, so the
 * canonical shape matches Pydantic and Zod (which also flatten inheritance).
 */
public record WithManager(@NotNull Manager person) {

    public static class EmployeeBase {
        @NotNull
        public String name;
        @NotNull
        public String dept;

        public EmployeeBase() {}

        public EmployeeBase(String name, String dept) {
            this.name = name;
            this.dept = dept;
        }
    }

    public static class Manager extends EmployeeBase {
        public int reports;

        public Manager() {}

        public Manager(String name, String dept, int reports) {
            super(name, dept);
            this.reports = reports;
        }
    }
}
