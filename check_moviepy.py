import sys

print(f"--- Python Executable: {sys.executable}")
print(f"--- Python Version: {sys.version}")
print(f"--- System Path:")
for p in sys.path:
    print(f"  - {p}")

print("\n--- Attempting to import moviepy...")

try:
    import moviepy.editor as mp
    print("\nSUCCESS: Successfully imported moviepy.")
    print(f"MoviePy version: {mp.__version__}")
except ImportError as e:
    print(f"\nERROR: Failed to import moviepy.")
    print(f"ImportError: {e}")
except Exception as e:
    print(f"\nERROR: An unexpected error occurred while importing moviepy.")
    print(f"Exception: {e}")
