"""Reset/Clear all memory storage including embeddings, session logs, and indexes

Usage:
    python reset_memory.py          # Interactive mode (asks for confirmation)
    python reset_memory.py --force  # Non-interactive mode (no confirmation)
    python reset_memory.py -f       # Short form
"""
import os
import shutil
from pathlib import Path
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def reset_memory():
    """Reset all memory storage"""
    
    paths_to_clear = [
        # Session logs and summaries
        Path("memory/session_logs"),
        Path("memory/session_summaries_index"),
        
        # FAISS document embeddings
        Path("mcp_servers/faiss_index"),
        
        # Sandbox execution state
        Path("action/sandbox_state"),
        
        # Summarization indexes (if exists)
        Path("summarization/session_summaries_index"),
    ]
    
    print("=" * 60)
    print("[RESET] Memory Reset Tool")
    print("=" * 60)
    print()
    print("This will delete:")
    print("  - Session logs and summaries")
    print("  - Document embeddings (FAISS index)")
    print("  - Sandbox execution state")
    print("  - All memory indexes")
    print()
    
    # Check for --force flag
    force = '--force' in sys.argv or '-f' in sys.argv
    
    # Ask for confirmation unless --force is used
    if not force:
        response = input("Are you sure you want to reset all memory? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("Reset cancelled.")
            return
    else:
        print("Using --force flag, skipping confirmation...")
    
    print()
    print("Clearing memory...")
    print()
    
    total_deleted = 0
    total_size = 0
    
    for path in paths_to_clear:
        if path.exists():
            try:
                # Calculate size before deletion
                if path.is_file():
                    size = path.stat().st_size
                    path.unlink()
                    total_deleted += 1
                    total_size += size
                    print(f"  [DELETED] {path} ({size / 1024:.2f} KB)")
                elif path.is_dir():
                    # Calculate directory size
                    size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
                    file_count = sum(1 for _ in path.rglob('*') if _.is_file())
                    shutil.rmtree(path)
                    total_deleted += file_count
                    total_size += size
                    print(f"  [DELETED] {path}/ ({file_count} files, {size / 1024:.2f} KB)")
            except Exception as e:
                print(f"  [ERROR] Failed to delete {path}: {e}")
        else:
            print(f"  [SKIP] {path} (does not exist)")
    
    # Also clear any metadata files
    meta_files = [
        Path("memory/session_summaries_index/.index_meta.json"),
        Path("summarization/session_summaries_index/.index_meta.json"),
    ]
    
    for meta_file in meta_files:
        if meta_file.exists():
            try:
                size = meta_file.stat().st_size
                meta_file.unlink()
                total_deleted += 1
                total_size += size
                print(f"  [DELETED] {meta_file} ({size / 1024:.2f} KB)")
            except Exception as e:
                print(f"  [ERROR] Failed to delete {meta_file}: {e}")
    
    print()
    print("=" * 60)
    print(f"[SUCCESS] Memory reset complete!")
    print(f"  - Deleted {total_deleted} files/directories")
    print(f"  - Freed {total_size / (1024 * 1024):.2f} MB")
    print("=" * 60)
    print()
    print("Note: Memory will be rebuilt as you use the application.")
    print("Document embeddings will be regenerated when documents are processed.")

if __name__ == "__main__":
    try:
        reset_memory()
    except KeyboardInterrupt:
        print("\n\nReset cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Reset failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

