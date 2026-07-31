package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Scans Spring MVC controllers for @MeshRoute annotations and registers
 * them in the {@link MeshRouteRegistry}.
 *
 * <p>This processor runs during application startup and discovers all
 * controller methods annotated with {@link MeshRoute}, extracting their
 * dependency metadata for use during request handling.
 */
public class MeshRouteBeanPostProcessor implements BeanPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(MeshRouteBeanPostProcessor.class);

    private final MeshRouteRegistry registry;

    public MeshRouteBeanPostProcessor(MeshRouteRegistry registry) {
        this.registry = registry;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        // Only process @RestController or @Controller beans
        if (AnnotationUtils.findAnnotation(targetClass, RestController.class) == null &&
            AnnotationUtils.findAnnotation(targetClass, Controller.class) == null) {
            return bean;
        }

        // Get base path from @RequestMapping on class
        String basePath = getClassBasePath(targetClass);

        // Scan methods for @MeshRoute
        for (Method method : targetClass.getDeclaredMethods()) {
            MeshRoute meshRoute = AnnotationUtils.findAnnotation(method, MeshRoute.class);
            if (meshRoute == null) {
                continue;
            }

            // Get HTTP methods and paths from Spring mapping annotations
            List<MappingInfo> mappings = getMappingInfo(method);
            if (mappings.isEmpty()) {
                log.warn("@MeshRoute on method without request mapping: {}.{}",
                    targetClass.getSimpleName(), method.getName());
                continue;
            }

            // Build dependency specs
            List<MeshRouteRegistry.DependencySpec> deps =
                MeshRouteRegistry.DependencySpec.fromAnnotation(meshRoute);

            // Enrich dependency specs with generic return type info from method parameters
            enrichDependencyReturnTypes(method, deps);

            // Issue #1401: @MeshRoute binds positionally. Fail the boot on a
            // @MeshInject value that contradicts the position, and warn on a
            // handler still shaped for the pre-3.4 name-based binding.
            MeshLegacyBindingDetector.inspectRoute(method, deps);

            // Register each HTTP method/path combination.
            //
            // Issue #1437: the METHOD is the handler's identity. The registry
            // derives the "ClassName.methodName" id from it for logs, but keys
            // on the Method itself — that id omits parameter types, so two
            // overloaded @MeshRoute handlers share it and the interceptor served
            // one of them the other's (positional) dependency list.
            MeshRouteRegistry.RouteMetadata metadata = new MeshRouteRegistry.RouteMetadata(
                method,
                deps,
                meshRoute.description(),
                meshRoute.failOnMissingDependency()
            );

            for (MappingInfo mapping : mappings) {
                String fullPath = normalizePath(basePath + mapping.path);
                registry.register(mapping.httpMethod, fullPath, metadata);
            }
        }

        return bean;
    }

    /**
     * Extract generic type arguments from {@code McpMeshTool} parameters and set
     * them on the {@code DependencySpec} each parameter <b>positionally</b>
     * binds to (issue #1401).
     *
     * <p>The Nth injectable parameter's {@code McpMeshTool<T>} argument becomes
     * the return type of the Nth declared dependency — the same pairing
     * {@link MeshInjectArgumentResolver} uses to hand that parameter its proxy,
     * derived from the same {@link MeshInjectableSlots} enumeration.
     *
     * <p>This has to move with the resolver, not after it. The type set here
     * flows through {@code MeshRouteHandlerInterceptor} into
     * {@code injector.getToolProxy(capability, returnType)}, so it drives
     * response deserialization and the issue #547 schema-match payload. Matching
     * it by name while the proxy is chosen by position would deserialize a
     * reordered handler's response into the wrong type — silently.
     */
    private void enrichDependencyReturnTypes(Method method, List<MeshRouteRegistry.DependencySpec> deps) {
        java.lang.reflect.Type[] genericTypes = method.getGenericParameterTypes();
        List<io.mcpmesh.spring.MeshPositionalBinder.Slot> slots =
            MeshInjectableSlots.routeSlots(method);

        for (int slot = 0; slot < slots.size(); slot++) {
            int position = slots.get(slot).parameterPosition();

            // Extract generic type argument (e.g., GreetResponse from McpMeshTool<GreetResponse>)
            java.lang.reflect.Type returnType = null;
            if (genericTypes[position] instanceof java.lang.reflect.ParameterizedType pt) {
                java.lang.reflect.Type[] typeArgs = pt.getActualTypeArguments();
                if (typeArgs.length > 0) {
                    returnType = typeArgs[0];
                }
            }

            if (returnType == null) {
                continue;
            }

            if (slot >= deps.size()) {
                log.warn("@MeshRoute {}.{}: McpMeshTool parameter {} is injectable slot {}, but "
                        + "only {} dependenc{} declared — its generic type is ignored and the "
                        + "parameter is injected null. dependencies[i] binds to the i-th "
                        + "injectable parameter.",
                    method.getDeclaringClass().getSimpleName(), method.getName(), position, slot,
                    deps.size(), deps.size() == 1 ? "y is" : "ies are");
                continue;
            }
            deps.get(slot).setReturnType(returnType);
        }
    }

    /**
     * Get the base path from class-level @RequestMapping.
     *
     * <p>Issue #1443, one level up: {@link AnnotationUtils#findAnnotation} does
     * not apply {@code @AliasFor}, so a controller annotated with a user-defined
     * composed annotation (meta-annotated {@code @RequestMapping}, overriding
     * {@code path}) surfaced the meta-annotation's empty defaults and the base
     * path silently degraded to {@code ""} — misplacing EVERY route on that
     * controller, not just adding a phantom.
     * {@link AnnotatedElementUtils#findMergedAnnotation} resolves the override.
     */
    private String getClassBasePath(Class<?> clazz) {
        RequestMapping mapping =
            AnnotatedElementUtils.findMergedAnnotation(clazz, RequestMapping.class);
        if (mapping != null && mapping.value().length > 0) {
            return mapping.value()[0];
        }
        if (mapping != null && mapping.path().length > 0) {
            return mapping.path()[0];
        }
        return "";
    }

    /**
     * Extract HTTP method and path from Spring mapping annotations.
     *
     * <p>Every mapping annotation the developer WROTE contributes, and nothing
     * else does. The three sources are consulted independently:
     *
     * <ol>
     *   <li>each of the five HTTP-verb shortcuts, separately — a method may
     *       legally carry more than one ({@code @GetMapping} +
     *       {@code @PostMapping} must yield TWO mappings), and a single
     *       {@code findMergedAnnotation(method, RequestMapping.class)} returns
     *       only ONE merged annotation, so collapsing them would silently drop
     *       a mapping;</li>
     *   <li>a {@code @RequestMapping} <b>directly present</b> on the method,
     *       which contributes on top of any shortcut — that combination
     *       compiles and the developer wrote both;</li>
     *   <li>failing both, a merged {@code @RequestMapping} reached through a
     *       user-defined composed annotation.</li>
     * </ol>
     *
     * <p>Issue #1443: the {@code @RequestMapping} lookup used to be
     * unconditional AND meta-annotation-aware. Each verb shortcut is itself
     * meta-annotated {@code @RequestMapping}, so it matched for every handler —
     * and {@code AnnotationUtils.findAnnotation} does not apply
     * {@code @AliasFor}, so it surfaced the meta-annotation's own empty
     * {@code value()}/{@code path()} and no {@code method()}, which the
     * empty-path/default-GET fallbacks turned into a phantom
     * {@code GET <controller base path>} per handler. Step 3 is now reached only
     * when no annotation the developer wrote has already been read, and step 2
     * reads the direct annotation directly, so a shortcut's meta-annotation is
     * never mistaken for a mapping of its own.
     *
     * <p>{@link AnnotatedElementUtils#findMergedAnnotation} replaces
     * {@link AnnotationUtils#findAnnotation} throughout so {@code @AliasFor} is
     * applied: {@code value} ↔ {@code path} within each annotation, and
     * meta-annotation attribute overrides for composed mapping annotations.
     */
    private List<MappingInfo> getMappingInfo(Method method) {
        List<MappingInfo> mappings = new ArrayList<>();

        // Check @GetMapping
        GetMapping getMapping = AnnotatedElementUtils.findMergedAnnotation(method, GetMapping.class);
        if (getMapping != null) {
            addMappings(mappings, "GET", getMapping.value(), getMapping.path());
        }

        // Check @PostMapping
        PostMapping postMapping = AnnotatedElementUtils.findMergedAnnotation(method, PostMapping.class);
        if (postMapping != null) {
            addMappings(mappings, "POST", postMapping.value(), postMapping.path());
        }

        // Check @PutMapping
        PutMapping putMapping = AnnotatedElementUtils.findMergedAnnotation(method, PutMapping.class);
        if (putMapping != null) {
            addMappings(mappings, "PUT", putMapping.value(), putMapping.path());
        }

        // Check @DeleteMapping
        DeleteMapping deleteMapping = AnnotatedElementUtils.findMergedAnnotation(method, DeleteMapping.class);
        if (deleteMapping != null) {
            addMappings(mappings, "DELETE", deleteMapping.value(), deleteMapping.path());
        }

        // Check @PatchMapping
        PatchMapping patchMapping = AnnotatedElementUtils.findMergedAnnotation(method, PatchMapping.class);
        if (patchMapping != null) {
            addMappings(mappings, "PATCH", patchMapping.value(), patchMapping.path());
        }

        // A @RequestMapping the developer wrote DIRECTLY on the method. Legal
        // alongside a verb shortcut, and then both were written, so both count.
        // getAnnotation() is directly-present-only, so a shortcut's own
        // meta-annotation can never reach here.
        RequestMapping direct = method.getAnnotation(RequestMapping.class);
        if (direct != null) {
            addRequestMappings(mappings, direct);
            return mappings;
        }

        if (!mappings.isEmpty()) {
            // A verb shortcut already described this handler. Anything a merged
            // @RequestMapping lookup would find now is that same shortcut's
            // meta-annotation (issue #1443).
            return mappings;
        }

        // Nothing so far: the handler may carry a user-defined composed
        // annotation that is meta-annotated @RequestMapping. Merging applies its
        // @AliasFor overrides.
        RequestMapping composed =
            AnnotatedElementUtils.findMergedAnnotation(method, RequestMapping.class);
        if (composed != null) {
            addRequestMappings(mappings, composed);
        }

        return mappings;
    }

    /**
     * Expand one {@code @RequestMapping} — which can carry several HTTP methods
     * and several paths at once — into its mappings.
     */
    private void addRequestMappings(List<MappingInfo> mappings, RequestMapping requestMapping) {
        String[] paths = requestMapping.value().length > 0 ?
            requestMapping.value() : requestMapping.path();
        if (paths.length == 0) {
            // A genuine path-less @RequestMapping — the handler is mapped at
            // the controller's base path, which is what Spring MVC does too.
            paths = new String[]{""};
        }

        // Get HTTP methods (default to GET if not specified)
        var methods = requestMapping.method();
        if (methods.length == 0) {
            for (String path : paths) {
                mappings.add(new MappingInfo("GET", path));
            }
        } else {
            for (var httpMethod : methods) {
                for (String path : paths) {
                    mappings.add(new MappingInfo(httpMethod.name(), path));
                }
            }
        }
    }

    private void addMappings(List<MappingInfo> mappings, String httpMethod,
                             String[] values, String[] paths) {
        String[] effectivePaths = values.length > 0 ? values : paths;
        if (effectivePaths.length == 0) {
            effectivePaths = new String[]{""};
        }
        for (String path : effectivePaths) {
            mappings.add(new MappingInfo(httpMethod, path));
        }
    }

    /**
     * Normalize path to ensure consistent format.
     */
    private String normalizePath(String path) {
        if (path == null || path.isEmpty()) {
            return "/";
        }
        // Ensure leading slash
        if (!path.startsWith("/")) {
            path = "/" + path;
        }
        // Remove trailing slash (except for root)
        if (path.length() > 1 && path.endsWith("/")) {
            path = path.substring(0, path.length() - 1);
        }
        // Remove double slashes
        path = path.replaceAll("//+", "/");
        return path;
    }

    /**
     * Simple holder for HTTP method and path.
     */
    private static class MappingInfo {
        final String httpMethod;
        final String path;

        MappingInfo(String httpMethod, String path) {
            this.httpMethod = httpMethod;
            this.path = path;
        }
    }
}
