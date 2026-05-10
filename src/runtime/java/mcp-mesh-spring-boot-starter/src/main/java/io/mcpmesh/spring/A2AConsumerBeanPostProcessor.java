package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.a2a.A2ABearer;
import io.mcpmesh.a2a.A2AClient;
import io.mcpmesh.a2a.A2AConsumer;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.BeanInitializationException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.core.env.Environment;
import org.springframework.util.ReflectionUtils;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Issue #923: scans Spring beans for {@code @A2AConsumer} methods,
 * constructs an {@link A2AClient} per unique
 * {@code (url, skillId, auth, timeoutSeconds)} tuple, and records a
 * per-method binding so {@link MeshToolWrapper} can inject the cached
 * client at the method's {@link A2AClient} parameter slot at invoke
 * time.
 *
 * <p>This processor mirrors the framework-construction shape of
 * Python's {@code @mesh.a2a_consumer} decorator (issue #913):
 * configuration lives on the annotation, not in user-managed
 * {@code static final} fields, and the runtime owns the
 * {@link A2AClient} lifecycle (incl. {@link #shutdown shutdown} on
 * Spring context close).
 *
 * <p><b>Why this is a separate processor:</b> {@link MeshToolBeanPostProcessor}
 * is responsible for {@code @MeshTool} metadata and wrapper construction;
 * binding A2A clients is an orthogonal concern that runs alongside it. The
 * two processors share no state — wrapper-side injection consults
 * {@link #bindingFor(Method)} on dispatch.
 */
public class A2AConsumerBeanPostProcessor implements BeanPostProcessor, Ordered {

    private static final Logger log = LoggerFactory.getLogger(A2AConsumerBeanPostProcessor.class);

    private final Environment environment;

    private final Map<A2AClientKey, A2AClient> clientCache = new ConcurrentHashMap<>();
    private final Map<Method, MethodBinding> bindings = new ConcurrentHashMap<>();

    public A2AConsumerBeanPostProcessor(Environment environment) {
        this.environment = environment;
    }

    /**
     * Run BEFORE {@link MeshToolBeanPostProcessor} (which also visits
     * each user bean) so the {@link MethodBinding} is in place by the
     * time the {@link MeshToolWrapper} is constructed and asks for
     * its A2A injection slot. Lower order = earlier; the default for
     * the tool processor is the framework default ({@code LOWEST_PRECEDENCE}).
     */
    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }

    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) throws BeansException {
        return bean;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> targetClass = AopUtils.getTargetClass(bean);
        ReflectionUtils.doWithMethods(targetClass, method -> {
            A2AConsumer annotation = AnnotationUtils.findAnnotation(method, A2AConsumer.class);
            if (annotation == null) {
                return;
            }
            try {
                processConsumerMethod(targetClass, method, annotation);
            } catch (BeanInitializationException bie) {
                throw bie;
            } catch (RuntimeException re) {
                throw new BeanInitializationException(
                    "Failed to wire @A2AConsumer on " + targetClass.getName()
                        + "#" + method.getName() + ": " + re.getMessage(), re);
            }
        });
        return bean;
    }

    private void processConsumerMethod(Class<?> targetClass, Method method, A2AConsumer annotation) {
        // Hard cutover (#923): the marker-only form (url defaulted to "")
        // is rejected with the exact migration message documented in the
        // issue body. A url that is non-blank at source level but
        // resolves to blank via Spring placeholder substitution gets a
        // distinct message that points at the property, not the migration.
        String rawUrl = annotation.url();
        if (rawUrl == null || rawUrl.isBlank()) {
            throw new BeanInitializationException(
                "@A2AConsumer on method " + method.getName() + "() requires the 'url' field. "
                    + "The marker-only form was removed in #923 — see "
                    + "https://github.com/dhyansraj/mcp-mesh/issues/923 for migration. "
                    + "Set @A2AConsumer(url = \"...\", skillId = \"...\").");
        }

        String authEnv = annotation.authBearerEnv();
        String authToken = annotation.authBearerToken();
        boolean hasEnv = authEnv != null && !authEnv.isBlank();
        boolean hasToken = authToken != null && !authToken.isBlank();
        if (hasEnv && hasToken) {
            throw new BeanInitializationException(
                "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                    + ": authBearerEnv and authBearerToken are mutually exclusive — set zero or one, never both.");
        }

        int timeoutSeconds = annotation.timeoutSeconds();
        if (timeoutSeconds <= 0) {
            throw new BeanInitializationException(
                "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                    + ": timeoutSeconds must be > 0 (got " + timeoutSeconds + ")");
        }

        // Resolve Spring property placeholders so users can write
        // @A2AConsumer(url = "${weather.a2a.url}") and have the property
        // value (env-overridable) flow into the underlying URL.
        String resolvedUrl;
        try {
            resolvedUrl = environment.resolveRequiredPlaceholders(rawUrl);
        } catch (IllegalArgumentException e) {
            throw new BeanInitializationException(
                "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                    + ": failed to resolve url placeholder '" + rawUrl + "': " + e.getMessage(), e);
        }
        if (resolvedUrl == null || resolvedUrl.isBlank()) {
            // rawUrl was non-blank (would have been rejected above
            // otherwise) but resolution yielded empty — typical cause is
            // a placeholder like ${empty.prop:} resolving to "". Point
            // at the property, not the marker-only migration.
            throw new BeanInitializationException(
                "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                    + ": url resolved to empty (raw=" + rawUrl + "). "
                    + "Check that the Spring property is defined and non-blank.");
        }

        // Default skillId to the surrounding @MeshTool capability when
        // the user left it blank — matches the Python decorator's
        // a2a_skill_id=None → capability default. If BOTH are blank,
        // fail fast at boot rather than caching an empty skillId and
        // having the first A2A call fail downstream with an opaque
        // upstream error.
        String skillId = annotation.skillId();
        if (skillId == null || skillId.isBlank()) {
            MeshTool meshTool = AnnotationUtils.findAnnotation(method, MeshTool.class);
            if (meshTool != null && meshTool.capability() != null && !meshTool.capability().isBlank()) {
                skillId = meshTool.capability();
            } else {
                throw new BeanInitializationException(
                    "@A2AConsumer on method " + method.getName() + " requires a non-blank "
                        + "skillId — neither @A2AConsumer(skillId=...) nor @MeshTool(capability=...) "
                        + "carries a value. Set skillId on the @A2AConsumer annotation explicitly.");
            }
        }

        // Locate the (mandatory) A2AClient parameter slot. Without
        // exactly one, the wrapper has no place to inject the client —
        // surface a clear error rather than silently fail at first call.
        int a2aParamIndex = findSingleA2AClientParam(targetClass, method);

        AuthSpec authSpec = hasEnv ? AuthSpec.fromEnv(authEnv)
            : hasToken ? AuthSpec.literal(authToken)
            : AuthSpec.none();

        A2AClientKey key = new A2AClientKey(resolvedUrl, skillId, authSpec, timeoutSeconds);
        A2AClient client = clientCache.computeIfAbsent(key, k -> {
            A2ABearer bearer = k.auth().toBearer();
            A2AClient created = new A2AClient(k.url(), k.skillId(), bearer, Duration.ofSeconds(k.timeoutSeconds()));
            log.info("@A2AConsumer: constructed A2AClient(url={}, skillId={}, auth={}, timeoutSeconds={})",
                k.url(), k.skillId(), k.auth(), k.timeoutSeconds());
            return created;
        });

        bindings.put(method, new MethodBinding(key, a2aParamIndex, client));
        log.debug("@A2AConsumer wired: {}#{} → A2AClient(url={}) at paramIndex={}",
            targetClass.getSimpleName(), method.getName(), resolvedUrl, a2aParamIndex);
    }

    private static int findSingleA2AClientParam(Class<?> targetClass, Method method) {
        Parameter[] params = method.getParameters();
        int found = -1;
        for (int i = 0; i < params.length; i++) {
            if (A2AClient.class.isAssignableFrom(params[i].getType())) {
                if (found >= 0) {
                    throw new BeanInitializationException(
                        "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                            + ": method declares more than one A2AClient parameter; exactly one is required.");
                }
                found = i;
            }
        }
        if (found < 0) {
            throw new BeanInitializationException(
                "@A2AConsumer on " + targetClass.getName() + "#" + method.getName()
                    + ": method must declare exactly one A2AClient parameter — the framework injects the cached client at that slot.");
        }
        return found;
    }

    /**
     * Look up the {@link MethodBinding} for a {@code @A2AConsumer}
     * method. Returns {@code null} when the method was never processed
     * (i.e. has no {@code @A2AConsumer} annotation).
     */
    public MethodBinding bindingFor(Method method) {
        return bindings.get(method);
    }

    /** Test/diagnostics surface: cache size — used by unit tests to assert sharing. */
    public int cacheSize() {
        return clientCache.size();
    }

    /** Test/diagnostics surface: read-only snapshot of currently-bound methods. */
    public Map<Method, MethodBinding> bindings() {
        return Collections.unmodifiableMap(bindings);
    }

    /**
     * Close every cached {@link A2AClient} when the surrounding Spring
     * context shuts down. Replaces the user's manual {@code @PreDestroy}
     * hook in the pre-#923 examples — the framework now owns the
     * client lifecycle from boot to shutdown.
     */
    @PreDestroy
    public void shutdown() {
        for (Map.Entry<A2AClientKey, A2AClient> e : clientCache.entrySet()) {
            try {
                e.getValue().close();
            } catch (Exception ex) {
                // Best-effort — log but don't fail context shutdown.
                log.warn("@A2AConsumer: failed to close A2AClient(url={}) during shutdown",
                    e.getKey().url(), ex);
            }
        }
        clientCache.clear();
        bindings.clear();
    }

    /**
     * Per-method binding captured at boot for the wrapper-side dispatcher.
     *
     * @param key            the cache key the client was registered under
     *                       (kept for diagnostics + test assertions).
     * @param a2aParamIndex  the position of the {@link A2AClient}
     *                       parameter on the method signature.
     * @param client         the cached {@link A2AClient} instance.
     */
    public record MethodBinding(A2AClientKey key, int a2aParamIndex, A2AClient client) {
    }

    /**
     * Cache key distinguishing one {@link A2AClient} configuration from
     * another. Two methods with identical {@code (url, skillId, auth,
     * timeoutSeconds)} tuples share the same client instance — the
     * Java HTTP connection pool is amortised across them.
     */
    public record A2AClientKey(String url, String skillId, AuthSpec auth, int timeoutSeconds) {
        public A2AClientKey {
            Objects.requireNonNull(url, "url");
            Objects.requireNonNull(auth, "auth");
            if (skillId == null) skillId = "";
        }
    }

    /**
     * Internal: serialised form of the optional bearer credential
     * (env-var name OR literal token OR none) used as part of the
     * {@link A2AClientKey} so credentials with different rotation
     * surfaces don't accidentally share a cached client.
     */
    public record AuthSpec(String envName, String literal) {
        private static final AuthSpec NONE = new AuthSpec(null, null);

        public static AuthSpec none() {
            return NONE;
        }

        public static AuthSpec fromEnv(String envName) {
            return new AuthSpec(envName, null);
        }

        public static AuthSpec literal(String literal) {
            return new AuthSpec(null, literal);
        }

        /** Build an {@link A2ABearer} from this spec, or {@code null} when no auth is configured. */
        public A2ABearer toBearer() {
            if (envName != null) return A2ABearer.fromEnv(envName);
            if (literal != null) return A2ABearer.of(literal);
            return null;
        }

        @Override
        public String toString() {
            if (envName != null) return "env:" + envName;
            if (literal != null) return "literal:<redacted>";
            return "none";
        }
    }
}
