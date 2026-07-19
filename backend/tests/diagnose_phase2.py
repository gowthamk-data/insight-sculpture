"""Phase 2 of API key diagnosis — reproduce the exact test runner sequence."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Step 1: EXACTLY what run_planner_tests.py lines 42-49 does
print("=" * 60)
print("STEP 1: Test runner sets os.environ defaults")
print("=" * 60)
os.environ["APP_NAME"] = "Insight Sculpture"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "true"
os.environ["LLM_PROVIDER"] = "gemini"
# os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "test-key-placeholder")
# os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "test-key-placeholder")
os.environ["LLM_MODEL"] = os.getenv("LLM_MODEL", "models/gemini-3.1-flash-lite")
os.environ["HOST"] = "127.0.0.1"
os.environ["PORT"] = "8000"

print(f"os.environ['GEMINI_API_KEY'] = {repr(os.environ.get('GEMINI_API_KEY'))}")

# Step 2: Now import app.config — which calls load_dotenv(override=False)
# load_dotenv cannot override already-set env vars by default
print()
print("=" * 60)
print("STEP 2: Import app.config (triggers load_dotenv)")
print("=" * 60)
from app.config import get_settings, _BACKEND_DIR, _PROJECT_ROOT

s = get_settings()
print(f"Settings.gemini_api_key = {repr(s.gemini_api_key)}")
print(f"Settings.active_api_key (first 40 chars) = {repr(s.active_api_key[:40])}")

# Step 3: Check what load_dotenv would do with override=True
print()
print("=" * 60)
print("STEP 3: What if load_dotenv used override=True?")
print("=" * 60)
from dotenv import load_dotenv
# Read the .env value directly
env_path = _BACKEND_DIR / '.env'
print(f".env path: {env_path}")
if env_path.exists():
    content = env_path.read_text()
    for line in content.splitlines():
        if line.startswith('GEMINI_API_KEY='):
            real_key = line.split('=', 1)[1]
            print(f"Real .env GEMINI_API_KEY (first 40 chars) = {repr(real_key[:40])}")

# Step 4: Clear and reload to confirm the root cause
print()
print("=" * 60)
print("STEP 4: Clear os.environ and re-load with override=True")
print("=" * 60)
os.environ.pop('GEMINI_API_KEY', None)
os.environ.pop('OPENAI_API_KEY', None)
load_dotenv(_BACKEND_DIR / '.env', override=True)
print(f"After load_dotenv(override=True):")
print(f"  os.environ['GEMINI_API_KEY'] (first 40 chars) = {repr(os.environ.get('GEMINI_API_KEY', 'NOT SET')[:40])}")

print()
print("=" * 60)
print("CONCLUSION")
print("=" * 60)
print("The test runner's line 46:")
print("  os.environ['GEMINI_API_KEY'] = os.getenv('GEMINI_API_KEY', 'test-key-placeholder')")
print("sets GEMINI_API_KEY to 'test-key-placeholder' BEFORE config.py's")
print("load_dotenv() runs. Since load_dotenv defaults to override=False,")
print("the real API key from .env is silently discarded.")
print()
print("The standalone test passes because it does NOT pre-set the env var,")
print("so load_dotenv successfully loads the real key.")
print()
print("The GeminiClient constructor falls through to os.getenv('GEMINI_API_KEY')")
print("which returns 'test-key-placeholder', causing 400 INVALID_ARGUMENT.")