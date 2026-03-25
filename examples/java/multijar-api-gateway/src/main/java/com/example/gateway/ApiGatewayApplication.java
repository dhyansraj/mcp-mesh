package com.example.gateway;

import com.example.dto.PaymentRecord;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@SpringBootApplication
public class ApiGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(ApiGatewayApplication.class, args);
    }
}

/**
 * REST controller consuming mesh capabilities where the DTO (PaymentRecord)
 * lives in a SEPARATE JAR (multijar-common-dto).
 *
 * <p>This is the pattern that fails in real-world multi-module projects:
 * PaymentRecord ends up in BOOT-INF/lib/multijar-common-dto-1.0.0-SNAPSHOT.jar
 * rather than being a class in the same module. The tc10 integration test passes
 * because Employee is defined in the same module as the controller.
 */
@RestController
@RequestMapping("/api")
class PaymentController {

    @GetMapping("/payments")
    @MeshRoute(dependencies = @MeshDependency(capability = "list_payments"))
    public ResponseEntity<Map<String, Object>> listPayments(
            @MeshInject("list_payments") McpMeshTool<List<PaymentRecord>> listPayments) {

        List<PaymentRecord> payments = listPayments.call();

        // This line will throw ClassCastException if deserialized as List<LinkedHashMap>
        BigDecimal total = payments.stream()
            .map(PaymentRecord::amount)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

        String firstStudent = payments.isEmpty() ? "none" : payments.get(0).studentName();

        // Prove it's not LinkedHashMap
        String elementType = payments.isEmpty() ? "empty" : payments.get(0).getClass().getSimpleName();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed-list");
        response.put("count", payments.size());
        response.put("totalAmount", total);
        response.put("firstStudent", firstStudent);
        response.put("elementType", elementType);  // Should be "PaymentRecord", not "LinkedHashMap"
        return ResponseEntity.ok(response);
    }

    @GetMapping("/payments/student/{studentId}")
    @MeshRoute(dependencies = @MeshDependency(capability = "get_payments_by_student"))
    public ResponseEntity<Map<String, Object>> getStudentPayments(
            @PathVariable String studentId,
            @MeshInject("get_payments_by_student") McpMeshTool<List<PaymentRecord>> getPaymentsByStudent) {

        List<PaymentRecord> payments = getPaymentsByStudent.call(Map.of("studentId", studentId));

        BigDecimal total = payments.stream()
            .map(PaymentRecord::amount)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

        String elementType = payments.isEmpty() ? "empty" : payments.get(0).getClass().getSimpleName();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed-list");
        response.put("studentId", studentId);
        response.put("count", payments.size());
        response.put("totalAmount", total);
        response.put("elementType", elementType);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(Map.of("status", "healthy"));
    }
}
