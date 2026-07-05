package com.example.serviceview;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

import java.util.Map;

/**
 * uc37 floored service view (RFC #1280 {@code minAvailable}): two methods,
 * floor of two. When EITHER capability loses its provider the whole view is
 * below floor and EVERY facade call must fail with
 * {@code MeshServiceUnavailableException} — including a call to the method
 * whose own provider is still up (tc05's differentiator).
 *
 * <p>Both capabilities are also bound by {@link ReportService} with the same
 * resolved type ({@code Map}), exercising the cross-view shared-capability
 * dedupe: the wire registration must still expand to exactly 3 dependencies.
 */
@McpMeshService(minAvailable = 2)
public interface FlooredService {

    @Selector(capability = "view-cap-alpha")
    Map<String, Object> alphaFloored();

    @Selector(capability = "view-cap-bravo")
    Map<String, Object> bravoFloored();
}
