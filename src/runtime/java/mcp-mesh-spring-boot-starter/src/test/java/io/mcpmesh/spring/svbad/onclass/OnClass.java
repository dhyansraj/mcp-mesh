package io.mcpmesh.spring.svbad.onclass;

import io.mcpmesh.McpMeshService;

/** Boot-fail (MED-4): @McpMeshService on a class rather than an interface. */
public final class OnClass {

    private OnClass() {
    }

    @McpMeshService
    public static class NotAnInterfaceService {
    }
}
