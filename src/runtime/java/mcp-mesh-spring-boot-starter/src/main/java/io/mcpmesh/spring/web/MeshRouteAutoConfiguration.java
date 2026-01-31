package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Lazy;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.List;

/**
 * Spring Boot auto-configuration for @MeshRoute support.
 *
 * <p>This configuration is automatically applied when:
 * <ul>
 *   <li>Spring Web MVC is on the classpath</li>
 *   <li>The application is a web application</li>
 * </ul>
 *
 * <p>It provides:
 * <ul>
 *   <li>{@link MeshRouteRegistry} - stores route metadata</li>
 *   <li>{@link MeshRouteBeanPostProcessor} - discovers @MeshRoute annotations</li>
 *   <li>{@link MeshRouteHandlerInterceptor} - resolves dependencies at request time</li>
 *   <li>{@link MeshInjectArgumentResolver} - enables @MeshInject parameter injection</li>
 * </ul>
 */
@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@ConditionalOnClass(name = "org.springframework.web.servlet.DispatcherServlet")
public class MeshRouteAutoConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MeshRouteAutoConfiguration.class);

    @Bean
    @ConditionalOnMissingBean
    public static MeshRouteRegistry meshRouteRegistry() {
        return new MeshRouteRegistry();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshRouteBeanPostProcessor meshRouteBeanPostProcessor(
            MeshRouteRegistry registry) {
        return new MeshRouteBeanPostProcessor(registry);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshRouteHandlerInterceptor meshRouteHandlerInterceptor(
            MeshRouteRegistry registry,
            ObjectProvider<MeshDependencyInjector> injectorProvider) {
        // Use ObjectProvider to avoid circular dependency issues
        return new MeshRouteHandlerInterceptor(registry, injectorProvider);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshInjectArgumentResolver meshInjectArgumentResolver() {
        return new MeshInjectArgumentResolver();
    }

    /**
     * Separate configuration class for WebMvcConfigurer to avoid circular dependencies.
     */
    @Configuration
    @ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
    static class MeshRouteWebMvcConfigurer implements WebMvcConfigurer {

        private final ObjectProvider<MeshRouteHandlerInterceptor> interceptorProvider;
        private final ObjectProvider<MeshInjectArgumentResolver> argumentResolverProvider;

        MeshRouteWebMvcConfigurer(
                ObjectProvider<MeshRouteHandlerInterceptor> interceptorProvider,
                ObjectProvider<MeshInjectArgumentResolver> argumentResolverProvider) {
            this.interceptorProvider = interceptorProvider;
            this.argumentResolverProvider = argumentResolverProvider;
            log.info("MeshRoute support enabled");
        }

        @Override
        public void addInterceptors(InterceptorRegistry registry) {
            MeshRouteHandlerInterceptor interceptor = interceptorProvider.getIfAvailable();
            if (interceptor != null) {
                registry.addInterceptor(interceptor).addPathPatterns("/**");
                log.debug("Registered MeshRouteHandlerInterceptor");
            }
        }

        @Override
        public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
            MeshInjectArgumentResolver resolver = argumentResolverProvider.getIfAvailable();
            if (resolver != null) {
                resolvers.add(resolver);
                log.debug("Registered MeshInjectArgumentResolver");
            }
        }
    }
}
