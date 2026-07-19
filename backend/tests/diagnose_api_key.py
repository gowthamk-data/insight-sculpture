"""Diagnostic script to trace the API key resolution path."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 1. Check environment BEFORE any imports
print("=" * 60)
print("ENVIRONMENT BEFORE IMPORT")
print("=" * 60)
print(f"GEMINI_API_KEY from os.environ: {os.environ.get('GEMINI_API_KEY', 'NOT SET')[:20]}...")
print(f"LLM_PROVIDER from os.environ: {os.environ.get('LLM_PROVIDER', 'NOT SET')}")
print(f"LLM_MODEL from os.environ: {os.environ.get('LLM_MODEL', 'NOT SET')}")
print()

# 2. Check what config.py loads
print("=" * 60)
print("CONFIG SETTINGS")
print("=" * 60)
from app.config import get_settings
s = get_settings()
print(f"Settings.gemini_api_key: {s.gemini_api_key[:20] if s.gemini_api_key else None}...")
print(f"Settings.llm_provider: {s.llm_provider}")
print(f"Settings.active_api_key: {s.active_api_key[:20] if s.active_api_key else None}...")
print()

# 3. Check GeminiClient initialization
print("=" * 60)
print("GEMINI CLIENT INIT")
print("=" * 60)
from app.llm.gemini_client import GeminiClient
gc = GeminiClient()
print(f"GeminiClient._api_key: {gc._api_key[:20] if gc._api_key else None}...")
print(f"GeminiClient._model: {gc._model}")
print(f"GeminiClient._client: {gc._client}")
print()

# 4. Check the actual genai.Client that was created
print("=" * 60)
print("GENAI CLIENT DETAILS")
print("=" * 60)
print(f"gc._client._api_key: {gc._client._api_key[:20] if hasattr(gc._client, '_api_key') and gc._client._api_key else 'N/A'}...")
# Try to list models to verify key works
try:
    models = list(gc._client.models.list())
    print(f"Models listable: YES ({len(list(models))} models)")
except Exception as e:
    print(f"Models listable: NO - {type(e).__name__}: {e}")
print()

# 5. Check the planner's call path
print("=" * 60)
print("PLANNER CALL PATH")
print("=" * 60)
from app.llm.planner import AnalysisPlanner
planner = AnalysisPlanner(gc)
print(f"Planner._llm_client: {planner._llm_client}")
print(f"Planner._llm_client._api_key: {planner._llm_client._api_key[:20] if planner._llm_client._api_key else None}...")
print(f"Planner._llm_client._model: {planner._llm_client._model}")
print()

# 6. Check if there are any other GeminiClient or genai.Client instances
print("=" * 60)
print("SEARCH FOR OTHER CLIENT INSTANCES")
print("=" * 60)
import gc as garbage_collector
for obj in garbage_collector.get_objects():
    if type(obj).__name__ == 'GeminiClient' and id(obj) != id(gc):
        print(f"OTHER GeminiClient instance found: {obj}")
        print(f"  _api_key: {obj._api_key[:20] if obj._api_key else None}...")
        print(f"  _model: {obj._model}")
    if type(obj).__name__ == 'Client' and hasattr(obj, '_api_key'):
        if obj._api_key != gc._client._api_key:
            print(f"OTHER genai.Client instance found with DIFFERENT key: {obj}")
            print(f"  _api_key: {obj._api_key[:20] if obj._api_key else None}...")
print()

# 7. Check the .env file loading
print("=" * 60)
print("DOTENV LOADING")
print("=" * 60)
from dotenv import load_dotenv
from pathlib import Path
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
print(f"Backend dir: {_backend_dir}")
print(f"Project root: {_project_root}")
print(f"Backend .env exists: {(_backend_dir / '.env').exists()}")
print(f"Project .env exists: {(_project_root / '.env').exists()}")
if (_backend_dir / '.env').exists():
    content = (_backend_dir / '.env').read_text()
    for line in content.splitlines():
        if 'API_KEY' in line or 'PROVIDER' in line or 'MODEL' in line:
            val = line.split('=')[1] if '=' in line else ''
            print(f"  {line.split('=')[0]}={val[:20]}...")