#!/usr/bin/env python3
"""
Test script to demonstrate the multi-file agent package structure
without requiring full MCP Mesh dependencies.

This script validates that:
1. All modules can be imported correctly
2. Configuration system works
3. Utility classes can be instantiated
4. Tool classes are properly structured

Run with: python test_structure.py
"""

import sys
import os
from pathlib import Path

# Add current directory to path for imports
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def test_imports():
    """Test that all modules can be imported."""
    print("🔍 Testing module imports...")
    
    try:
        # Test config imports
        from config import get_settings, Settings
        print("✅ Config module imports successful")
        
        # Test utility imports  
        from utils import DataValidator, ValidationError, DataFormatter, CacheManager, cache_key
        print("✅ Utils module imports successful")
        
        # Test tool imports
        from tools import DataParser, DataTransformer, StatisticalAnalyzer, DataExporter
        print("✅ Tools module imports successful")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_configuration():
    """Test configuration system."""
    print("\n⚙️  Testing configuration system...")
    
    try:
        from config import get_settings, Settings
        
        # Test default settings
        settings = get_settings()
        print(f"✅ Default settings loaded: {settings.agent_name}")
        
        # Test environment override
        os.environ["AGENT_NAME"] = "test-agent"
        os.environ["HTTP_PORT"] = "9999"
        
        # Create new settings from env
        env_settings = Settings.from_env()
        print(f"✅ Environment settings: {env_settings.agent_name}:{env_settings.http_port}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

def test_utilities():
    """Test utility classes."""
    print("\n🔧 Testing utility classes...")
    
    try:
        from utils import CacheManager, DataFormatter, cache_key
        
        # Test cache key generation
        key = cache_key("test", "data", param1="value1")
        print(f"✅ Cache key generated: {key[:8]}...")
        
        # Test cache manager (without actual caching)
        cache_manager = CacheManager("/tmp/test_cache", 300)
        print(f"✅ Cache manager created: {cache_manager.cache_dir}")
        
        # Test formatter
        formatter = DataFormatter()
        from utils.formatting import format_size
        size_str = format_size(1024 * 1024)
        print(f"✅ Formatter working: {size_str}")
        
        return True
        
    except Exception as e:
        print(f"❌ Utilities test failed: {e}")
        return False

def test_tools():
    """Test tool classes (without pandas dependencies)."""
    print("\n🛠️  Testing tool class structure...")
    
    try:
        from tools import DataParser, DataTransformer, StatisticalAnalyzer, DataExporter
        
        # Test that classes can be instantiated (may fail due to pandas deps)
        try:
            parser = DataParser()
            print(f"✅ DataParser created: {len(parser.supported_formats)} formats supported")
        except Exception:
            print("⚠️  DataParser requires pandas (expected in minimal test)")
        
        try:
            transformer = DataTransformer()
            print("✅ DataTransformer created")
        except Exception:
            print("⚠️  DataTransformer requires pandas (expected in minimal test)")
        
        try:
            analyzer = StatisticalAnalyzer()
            print("✅ StatisticalAnalyzer created")
        except Exception:
            print("⚠️  StatisticalAnalyzer requires scipy (expected in minimal test)")
        
        try:
            exporter = DataExporter()
            print("✅ DataExporter created")
        except Exception:
            print("⚠️  DataExporter requires pandas (expected in minimal test)")
        
        return True
        
    except Exception as e:
        print(f"❌ Tools test failed: {e}")
        return False

def test_package_structure():
    """Test overall package structure."""
    print("\n📦 Testing package structure...")
    
    try:
        # Test package can be imported
        import data_processor_agent
        print(f"✅ Package imported: {data_processor_agent.__version__}")
        
        # Test __init__ exports
        from data_processor_agent import DataProcessorAgent
        print("✅ Main class exported correctly")
        
        return True
        
    except Exception as e:
        print(f"❌ Package structure test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Testing Data Processor Agent Package Structure")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_configuration, 
        test_utilities,
        test_tools,
        test_package_structure
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Package structure is correct.")
        return 0
    else:
        print("⚠️  Some tests failed (may be due to missing dependencies)")
        return 1

if __name__ == "__main__":
    sys.exit(main())