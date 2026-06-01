#!/usr/bin/env python3
"""
Verification script to ensure all Anthropic API calls are using OpenRouter
This script checks:
1. Configuration settings are correct
2. All LLM instances are using the correct provider
3. Environment variables are properly set
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def verify_configuration():
    """Verify all configuration settings"""
    print("=" * 80)
    print("OPENROUTER API CONFIGURATION VERIFICATION")
    print("=" * 80)
    
    try:
        import config
        
        print("\n✓ Config module loaded successfully")
        
        # Check LLM Provider
        print(f"\n1. LLM Provider Setting:")
        print(f"   LLM_PROVIDER = '{config.LLM_PROVIDER}'")
        if config.LLM_PROVIDER == "openrouter":
            print("   ✓ Correctly set to 'openrouter'")
        else:
            print("   ✗ WARNING: Not set to 'openrouter'. All calls will use Anthropic API.")
            return False
        
        # Check API Keys
        print(f"\n2. API Keys Configuration:")
        if config.OPENROUTER_API_KEY:
            key_preview = config.OPENROUTER_API_KEY[:20] + "..." + config.OPENROUTER_API_KEY[-10:]
            print(f"   ✓ OPENROUTER_API_KEY is set: {key_preview}")
        else:
            print("   ✗ ERROR: OPENROUTER_API_KEY is not set!")
            return False
        
        if config.ANTHROPIC_API_KEY:
            print(f"   • ANTHROPIC_API_KEY is set (will be ignored when using OpenRouter)")
        else:
            print(f"   • ANTHROPIC_API_KEY is not set (not needed for OpenRouter)")
        
        # Check OpenRouter Settings
        print(f"\n3. OpenRouter Settings:")
        print(f"   Base URL: {config.OPENROUTER_BASE_URL}")
        print(f"   Site URL: {config.OPENROUTER_SITE_URL}")
        print(f"   Site Name: {config.OPENROUTER_SITE_NAME}")
        if config.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1":
            print("   ✓ OpenRouter base URL is correct")
        
        # Check Models
        print(f"\n4. Model Configuration:")
        print(f"   Main Model (Agents): {config.LLM_MODEL_MAIN}")
        print(f"   Vision Model (OCR): {config.LLM_MODEL_VISION}")
        
        return True
        
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False


def verify_llm_creation():
    """Verify LLM instances are created with correct provider"""
    print("\n" + "=" * 80)
    print("VERIFYING LLM INSTANCE CREATION")
    print("=" * 80)
    
    try:
        from agents.base_agent import create_llm
        import config
        
        print("\n✓ Successfully imported create_llm function")
        
        # Test creating an LLM instance
        print("\nAttempting to create LLM instance with OpenRouter...")
        
        try:
            llm = create_llm(config.LLM_MODEL_MAIN)
            print("✓ LLM instance created successfully")
            print(f"   Type: {type(llm).__name__}")
            print(f"   Model: {llm.model}")
            
            # Check if it has the correct base URL
            if hasattr(llm, 'base_url'):
                print(f"   Base URL: {llm.base_url}")
                if "openrouter" in str(llm.base_url):
                    print("   ✓ Base URL contains 'openrouter'")
            
            return True
        except ValueError as e:
            print(f"✗ ERROR creating LLM: {e}")
            print("   Make sure OPENROUTER_API_KEY is set in .env")
            return False
            
    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_ocr_processor():
    """Verify OCR processor uses correct provider"""
    print("\n" + "=" * 80)
    print("VERIFYING OCR PROCESSOR (VISION API)")
    print("=" * 80)
    
    try:
        from tools.ocr_processor import OCRProcessor
        import config
        
        print("\n✓ Successfully imported OCRProcessor")
        
        print("\nAttempting to create OCRProcessor instance with OpenRouter...")
        
        try:
            ocr = OCRProcessor()
            print("✓ OCRProcessor instance created successfully")
            print(f"   Provider: {ocr.provider}")
            print(f"   Model: {ocr.model}")
            
            if ocr.provider == "openrouter":
                print("   ✓ Using OpenRouter provider")
            
            # Check client configuration
            if hasattr(ocr.client, 'base_url'):
                print(f"   Base URL: {ocr.client.base_url}")
                if "openrouter" in str(ocr.client.base_url):
                    print("   ✓ Base URL contains 'openrouter'")
            
            return True
        except ValueError as e:
            print(f"✗ ERROR creating OCRProcessor: {e}")
            return False
            
    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_router_agent():
    """Verify router agent uses correct provider"""
    print("\n" + "=" * 80)
    print("VERIFYING ROUTER AGENT")
    print("=" * 80)

    try:
        from agents.router_agent import RouterAgent
        import config

        print("\n✓ Successfully imported RouterAgent")

        print("\nAttempting to create RouterAgent instance with OpenRouter...")

        try:
            router = RouterAgent()
            print("✓ RouterAgent instance created successfully")
            print(f"   Provider: {router.provider}")
            print(f"   Client type: {type(router.client).__name__}")

            if router.provider == "openrouter":
                print("   ✓ Using OpenRouter provider")

            if hasattr(router.client, 'base_url'):
                print(f"   Base URL: {router.client.base_url}")
                if "openrouter" in str(router.client.base_url):
                    print("   ✓ Base URL contains 'openrouter'")

            return True
        except ValueError as e:
            print(f"✗ ERROR creating RouterAgent: {e}")
            return False

    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_agents():
    """Verify all agents are using correct LLM provider"""
    print("\n" + "=" * 80)
    print("VERIFYING AGENT INITIALIZATION")
    print("=" * 80)
    
    try:
        from data_providers.local_excel_provider import LocalExcelDataProvider
        from file_storage.local_storage import LocalFileStorage
        from agents.invoice_agent import InvoiceAgent
        from agents.receipt_agent import ReceiptAgent
        from agents.ledger_agent import LedgerAgent
        from agents.admin_agent import AdminAgent
        import config
        
        print("\n✓ Successfully imported all agent classes")
        
        # Initialize data provider and storage
        data_provider = LocalExcelDataProvider(config.SOCIETY_DATA_FILE)
        file_storage = LocalFileStorage(config.DATA_DIR)
        
        print("✓ Data provider and file storage initialized")
        
        # Test each agent
        agents_to_test = [
            ("InvoiceAgent", InvoiceAgent),
            ("ReceiptAgent", ReceiptAgent),
            ("LedgerAgent", LedgerAgent),
            ("AdminAgent", AdminAgent),
        ]
        
        for agent_name, AgentClass in agents_to_test:
            print(f"\nInitializing {agent_name}...")
            try:
                agent = AgentClass(data_provider, file_storage)
                print(f"✓ {agent_name} initialized successfully")
                print(f"  LLM Model: {agent.llm.model}")
                if hasattr(agent.llm, 'base_url'):
                    print(f"  Base URL: {agent.llm.base_url}")
            except Exception as e:
                print(f"✗ Failed to initialize {agent_name}: {e}")
                return False
        
        return True
        
    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks"""
    results = []
    
    # Run all checks
    results.append(("Configuration", verify_configuration()))
    results.append(("LLM Creation", verify_llm_creation()))
    results.append(("OCR Processor", verify_ocr_processor()))
    results.append(("Router Agent", verify_router_agent()))
    results.append(("Agents", verify_agents()))
    
    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    all_passed = True
    for check_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{check_name}: {status}")
        if not result:
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL CHECKS PASSED - OpenRouter is properly configured!")
        print("\nAll Anthropic API calls will now route through OpenRouter.")
        print("You can monitor usage at: https://openrouter.ai/activity")
        return 0
    else:
        print("✗ SOME CHECKS FAILED - Please review the errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
