#!/bin/bash

# Quick test script to check if the registry is working

echo "Testing registry after fixes..."

# Test 1: Check if registry is responding on correct port
echo "1. Testing registry health endpoint:"
curl -v http://localhost:8000/health

echo -e "\n\n2. Testing registry root endpoint:"
curl -v http://localhost:8000/

echo -e "\n\n3. Testing registry agents endpoint:"
curl -v http://localhost:8000/agents

echo -e "\n\nDone!"
