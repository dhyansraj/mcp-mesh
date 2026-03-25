package com.example.dto;

import java.math.BigDecimal;
import java.time.LocalDate;

public record PaymentRecord(
    String id,
    String studentId,
    String studentName,
    BigDecimal amount,
    LocalDate dueDate,
    LocalDate paidDate,
    String status,
    String month
) {}
