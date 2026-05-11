package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.RouterFunctions;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * HTTP entry point for A2A producer surfaces (spec §3 + §4).
 *
 * <p>Exposes one {@link RouterFunction} per registered
 * {@link MeshA2ARegistry.SurfaceMetadata}, composed into a single
 * router-function bean by {@link #buildRouterFunction()}. The functional
 * approach sits alongside annotation-based {@code @RestController} mappings
 * in the same DispatcherServlet and only matches the exact paths owned by
 * {@code @MeshA2A} — static resources, error pages, and user controllers
 * are unaffected.
 *
 * <p>Each surface contributes three routes:
 * <ul>
 *   <li>{@code POST {path}} with {@code Accept: application/json}
 *       (or no Accept header) — JSON-RPC entry point; delegates to
 *       {@link MeshA2ADispatcher#dispatch(String, String)}. Handles
 *       {@code tasks/send}, {@code tasks/get}, {@code tasks/cancel}.</li>
 *   <li>{@code POST {path}} with {@code Accept: text/event-stream} — SSE
 *       entry point for {@code tasks/sendSubscribe} and
 *       {@code tasks/resubscribe}; delegates to
 *       {@link MeshA2ASseDispatcher}.</li>
 *   <li>{@code GET {path}/.well-known/agent.json} — agent card; rendered
 *       by {@link MeshA2ACardBuilder#build}. Always reachable without
 *       auth (spec §6.2).</li>
 * </ul>
 *
 * <p>The SSE route is matched FIRST so a client setting
 * {@code Accept: text/event-stream} doesn't fall through to the JSON-RPC
 * branch. Curl-style clients that POST without an Accept header land on
 * the JSON-RPC branch by default — which is what the {@code tasks/send}
 * test fixtures expect.
 */
public class MeshA2ADispatcherController {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ADispatcherController.class);

    private static final String AGENT_CARD_SUFFIX = "/.well-known/agent.json";

    private final MeshA2ARegistry registry;
    private final MeshA2ADispatcher dispatcher;
    private final MeshA2ASseDispatcher sseDispatcher;
    private final MeshA2ACardBuilder cardBuilder;
    private final ObjectProvider<MeshProperties> propertiesProvider;
    private final ObjectProvider<MeshA2APublicUrlCache> publicUrlCacheProvider;

    public MeshA2ADispatcherController(
            MeshA2ARegistry registry,
            MeshA2ADispatcher dispatcher,
            MeshA2ASseDispatcher sseDispatcher,
            MeshA2ACardBuilder cardBuilder,
            ObjectProvider<MeshProperties> propertiesProvider,
            ObjectProvider<MeshA2APublicUrlCache> publicUrlCacheProvider) {
        this.registry = registry;
        this.dispatcher = dispatcher;
        this.sseDispatcher = sseDispatcher;
        this.cardBuilder = cardBuilder;
        this.propertiesProvider = propertiesProvider;
        this.publicUrlCacheProvider = publicUrlCacheProvider;
    }

    /**
     * Build the composed {@link RouterFunction} for every registered surface.
     * Exposed as a Spring bean from {@code MeshAutoConfiguration} — see
     * {@code meshA2ARouterFunction(...)} factory method.
     */
    public RouterFunction<ServerResponse> buildRouterFunction() {
        RouterFunctions.Builder builder = RouterFunctions.route();
        for (MeshA2ARegistry.SurfaceMetadata surface : registry.getAllSurfaces()) {
            String path = surface.path();
            String cardPath = path + AGENT_CARD_SUFFIX;
            // SSE branch FIRST so Accept: text/event-stream wins the
            // route over the plain JSON-RPC branch.
            builder.POST(path,
                accepts(MediaType.TEXT_EVENT_STREAM),
                request -> handleSsePost(surface, request));
            builder.POST(path, request -> handlePost(surface, request));
            builder.GET(cardPath, request -> handleGetCard(surface));
            log.info("@MeshA2A: mounted POST {} (json+sse) and GET {}", path, cardPath);
        }
        return builder.build();
    }

    private static org.springframework.web.servlet.function.RequestPredicate accepts(
            MediaType mediaType) {
        return org.springframework.web.servlet.function.RequestPredicates.accept(mediaType);
    }

    private ServerResponse handlePost(MeshA2ARegistry.SurfaceMetadata surface, ServerRequest request) {
        String body;
        try {
            body = readBody(request);
        } catch (BodyReadException e) {
            // Spec §4.1: failure to read the body is reported to the client as
            // a JSON-RPC Parse error (-32700) with HTTP 400, not a generic 500.
            log.warn("@MeshA2A: failed to read request body for {}: {}",
                surface.path(), e.getMessage());
            String errorJson = parseErrorJson();
            return ServerResponse
                .status(HttpStatus.BAD_REQUEST)
                .contentType(MediaType.APPLICATION_JSON)
                .body(errorJson);
        }
        ResponseEntity<String> response = dispatcher.dispatch(surface.path(), body);
        return ServerResponse
            .status(response.getStatusCode())
            .contentType(MediaType.APPLICATION_JSON)
            .body(response.getBody() == null ? "" : response.getBody());
    }

    /**
     * SSE dispatch — peeks at the JSON-RPC method before promoting the
     * connection to {@code text/event-stream}. For verbs that don't return
     * SSE ({@code tasks/send}, {@code tasks/get}, {@code tasks/cancel}) the
     * controller falls through to the JSON-RPC dispatcher even when the
     * client set {@code Accept: text/event-stream} — matches Python's
     * behavior where the framework dispatches by method, not by Accept.
     */
    private ServerResponse handleSsePost(MeshA2ARegistry.SurfaceMetadata surface, ServerRequest request) {
        String body;
        try {
            body = readBody(request);
        } catch (BodyReadException e) {
            // Same parse-error path as the JSON-RPC branch — SSE clients still
            // get a JSON envelope back for the pre-stream parse failure.
            log.warn("@MeshA2A SSE: failed to read request body for {}: {}",
                surface.path(), e.getMessage());
            String errorJson = parseErrorJson();
            return ServerResponse
                .status(HttpStatus.BAD_REQUEST)
                .contentType(MediaType.APPLICATION_JSON)
                .body(errorJson);
        }
        String method = dispatcher.peekJsonRpcMethod(body);
        MeshA2ADispatcher.SseStreamPlan plan = switch (method == null ? "" : method) {
            case "tasks/sendSubscribe" -> dispatcher.buildSendSubscribeStream(surface.path(), body);
            case "tasks/resubscribe"   -> dispatcher.buildResubscribeStream(body);
            default -> null; // Fall through to JSON-RPC.
        };
        if (plan == null) {
            // Fall through to the JSON-RPC branch — pass the already-read body
            // so we don't try (and fail) to consume the input stream twice.
            return handlePostWithBody(surface, body);
        }
        return sseDispatcher.render(plan);
    }

    /**
     * Read the raw request body as a UTF-8 string directly from the servlet
     * input stream.
     *
     * <p>We bypass {@link ServerRequest#body(Class)} because under Spring
     * Boot 4 / Jackson 3, the framework does not register a
     * {@code HttpMessageConverter<String>} that accepts
     * {@code Content-Type: application/json} for the functional router path —
     * the converter resolver throws and the body read silently fails. The
     * earlier swallow-and-return-empty workaround masked this as
     * "Method not implemented: 'null'" errors for every well-formed
     * {@code tasks/send} request (issue #932).
     *
     * <p>Wrapping in {@link BodyReadException} surfaces I/O failures to the
     * caller, which converts them into a proper {@code -32700 Parse error}
     * response per spec §4.1 instead of swallowing them.
     */
    private static String readBody(ServerRequest request) {
        try {
            byte[] bytes = request.servletRequest().getInputStream().readAllBytes();
            return new String(bytes, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new BodyReadException("Failed to read request body", e);
        }
    }

    /**
     * JSON-RPC dispatch with the body already in hand — used by the SSE
     * branch when it has read the body to peek at the method and then needs
     * to fall through to the sync dispatcher without re-reading the (already
     * consumed) input stream.
     */
    private ServerResponse handlePostWithBody(MeshA2ARegistry.SurfaceMetadata surface, String body) {
        ResponseEntity<String> response = dispatcher.dispatch(surface.path(), body);
        return ServerResponse
            .status(response.getStatusCode())
            .contentType(MediaType.APPLICATION_JSON)
            .body(response.getBody() == null ? "" : response.getBody());
    }

    /** Unchecked wrapper for {@link IOException} during body read so the
     *  router-handler signature (no checked exceptions) stays intact. */
    static final class BodyReadException extends RuntimeException {
        BodyReadException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Build a canonical JSON-RPC parse-error envelope for body-read failures.
     * Hand-rolled (rather than going through the dispatcher's
     * {@code ObjectMapper}) because the message is fixed and constructing a
     * mapper on every error would be wasteful.
     */
    private static String parseErrorJson() {
        return "{\"jsonrpc\":\"2.0\",\"error\":{\"code\":"
            + MeshA2ADispatcher.JSONRPC_PARSE_ERROR
            + ",\"message\":\"Parse error: failed to read request body\"},\"id\":null}";
    }

    private ServerResponse handleGetCard(MeshA2ARegistry.SurfaceMetadata surface) {
        MeshProperties properties = propertiesProvider.getIfAvailable();
        String agentName = properties != null && properties.getAgent() != null
            ? properties.getAgent().getName() : null;
        String agentVersion = properties != null && properties.getAgent() != null
            ? properties.getAgent().getVersion() : null;

        // Public URL resolution priority (spec §3.2 / §8.2):
        //   1. Registry-stamped public URL from the heartbeat-response cache.
        //   2. Local fallback URL built from agent host:port.
        //   3. Omit `url` entirely (never emit empty string).
        String publicUrl = null;
        MeshA2APublicUrlCache cache = publicUrlCacheProvider.getIfAvailable();
        if (cache != null) {
            publicUrl = cache.get(surface.path(), surface.skillId());
        }
        if (publicUrl == null || publicUrl.isEmpty()) {
            String host = properties != null && properties.getAgent() != null
                ? properties.getAgent().getHost() : null;
            int port = properties != null && properties.getAgent() != null
                ? properties.getAgent().getPort() : 0;
            publicUrl = MeshA2ACardBuilder.localFallbackUrl(host, port, surface.path());
        }

        Map<String, Object> card = cardBuilder.build(
            surface, agentName, agentVersion, null, publicUrl);

        return ServerResponse
            .ok()
            .contentType(MediaType.APPLICATION_JSON)
            .body(cardBuilder.toJson(card));
    }
}
