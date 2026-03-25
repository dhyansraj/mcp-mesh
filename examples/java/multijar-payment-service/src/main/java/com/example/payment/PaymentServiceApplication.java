package com.example.payment;

import com.example.dto.PaymentRecord;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.stream.Collectors;

@MeshAgent(name = "multijar-payment-service", version = "1.0.0", port = 9010)
@SpringBootApplication
public class PaymentServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(PaymentServiceApplication.class, args);
    }

    @MeshTool(capability = "list_payments", description = "List all payments")
    public List<PaymentRecord> listPayments() {
        return PaymentData.PAYMENTS;
    }

    @MeshTool(capability = "get_payments_by_student", description = "Get payments for a student")
    public List<PaymentRecord> getPaymentsByStudent(
            @Param(value = "studentId", description = "Student ID") String studentId) {
        return PaymentData.PAYMENTS.stream()
            .filter(p -> p.studentId().equals(studentId))
            .collect(Collectors.toList());
    }
}

class PaymentData {
    static final List<PaymentRecord> PAYMENTS = List.of(
        new PaymentRecord("P001", "S001", "Alice", new BigDecimal("150.00"),
            LocalDate.of(2026, 3, 1), LocalDate.of(2026, 3, 1), "PAID", "March"),
        new PaymentRecord("P002", "S001", "Alice", new BigDecimal("150.00"),
            LocalDate.of(2026, 4, 1), null, "PENDING", "April"),
        new PaymentRecord("P003", "S002", "Bob", new BigDecimal("200.00"),
            LocalDate.of(2026, 3, 1), LocalDate.of(2026, 3, 5), "PAID", "March"),
        new PaymentRecord("P004", "S002", "Bob", new BigDecimal("200.00"),
            LocalDate.of(2026, 4, 1), null, "OVERDUE", "April"),
        new PaymentRecord("P005", "S003", "Charlie", new BigDecimal("175.00"),
            LocalDate.of(2026, 3, 1), LocalDate.of(2026, 2, 28), "PAID", "March")
    );
}
