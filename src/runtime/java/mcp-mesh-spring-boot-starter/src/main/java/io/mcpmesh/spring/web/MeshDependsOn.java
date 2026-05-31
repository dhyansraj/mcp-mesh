package io.mcpmesh.spring.web;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Class-level declaration of mesh capabilities a Spring-managed bean
 * depends on.
 *
 * <p>Use {@code @MeshDependsOn} on any {@code @Component}-derived bean
 * ({@code @Service}, {@code @Repository}, {@code @Component}, a servlet
 * {@code Filter}, a {@code @Scheduled} bean, etc.) when the consumer is
 * not a {@code @MeshRoute}-annotated controller method and therefore can't
 * use {@code @MeshInject} at the parameter level.
 *
 * <p>For every capability declared via this annotation the auto-configuration
 * registers a singleton {@link io.mcpmesh.types.McpMeshTool} bean named by
 * the capability string, so users can inject it the standard Spring way:
 *
 * <h2>Constructor injection</h2>
 * <pre>{@code
 * @Service
 * @MeshDependsOn({
 *     @MeshDependency(capability = "list_holidays"),
 *     @MeshDependency(capability = "get_user_profile")
 * })
 * public class StaffSyncService {
 *     private final McpMeshTool<List<Holiday>> holidays;
 *     private final McpMeshTool<UserProfileResponse> profile;
 *
 *     public StaffSyncService(
 *             @Qualifier("list_holidays") McpMeshTool<List<Holiday>> holidays,
 *             @Qualifier("get_user_profile") McpMeshTool<UserProfileResponse> profile) {
 *         this.holidays = holidays;
 *         this.profile = profile;
 *     }
 * }
 * }</pre>
 *
 * <h2>Field injection</h2>
 * <pre>{@code
 * @Component
 * @MeshDependsOn(@MeshDependency(capability = "list_holidays"))
 * public class HolidayChecker {
 *     @Autowired
 *     @Qualifier("list_holidays")
 *     private McpMeshTool<List<Holiday>> holidays;
 * }
 * }</pre>
 *
 * <h2>Lifecycle semantics</h2>
 *
 * <p>Capabilities declared here flow through the same heartbeat-driven
 * proxy lifecycle as {@code @MeshRoute(dependencies = ...)}:
 *
 * <ul>
 *   <li>Each capability is folded into a synthetic
 *       {@code __mesh_depends_on_deps} tool on the heartbeat envelope so
 *       the registry's resolution mechanism learns about it.</li>
 *   <li>The injected proxy starts in the {@code unavailable} state and
 *       transitions to {@code available} when the registry surfaces a
 *       matching producer. Use {@link io.mcpmesh.types.McpMeshTool#isAvailable()}
 *       to guard calls.</li>
 *   <li>The Spring bean reference stays valid across topology changes —
 *       the proxy's endpoint is rewired transparently by the heartbeat
 *       loop.</li>
 * </ul>
 *
 * <h2>Relation to {@code @MeshInject} / {@code @MeshRoute}</h2>
 *
 * <p>{@code @MeshDependsOn} complements (it does not replace)
 * {@code @MeshInject} on controller-method parameters. Use
 * {@code @MeshRoute(dependencies = ...)} + {@code @MeshInject} for
 * request-scoped wiring inside {@code @RestController} handler methods;
 * use {@code @MeshDependsOn} for anything else.
 *
 * <h2>Deduplication</h2>
 *
 * <p>If the same capability appears via multiple sources ({@code @MeshTool},
 * {@code @MeshRoute}, {@code @MeshA2A}, or {@code @MeshDependsOn}) the
 * first occurrence wins; subsequent declarations are de-duped by
 * capability name and a single {@link io.mcpmesh.types.McpMeshTool} bean
 * is registered.
 *
 * @see MeshDependency
 * @see MeshRoute
 * @see MeshInject
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshDependsOn {

    /**
     * Mesh capabilities this component depends on. Each entry is
     * resolved by capability name with optional tag/version filters,
     * exactly as on {@code @MeshRoute(dependencies = ...)}.
     *
     * @return the declared dependencies (default empty)
     */
    MeshDependency[] value() default {};
}
