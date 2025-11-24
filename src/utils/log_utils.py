import os
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

# Directory where logs are stored
LOGS_DIR = Path("logs")

def cleanup_old_logs(max_age_hours: int = 24):
    """
    Remove log files older than the specified number of hours.
    For JSON log files (like fyersRequests.log), removes old entries from within the file.
    
    Args:
        max_age_hours: Maximum age of log files in hours (default: 24)
    """
    if not LOGS_DIR.exists():
        print(f"Logs directory {LOGS_DIR} does not exist. Skipping cleanup.")
        return
    
    current_time = time.time()
    cutoff_time = current_time - (max_age_hours * 3600)
    cutoff_datetime = datetime.now() - timedelta(hours=max_age_hours)
    
    deleted_count = 0
    deleted_size = 0
    cleaned_files = []
    
    try:
        # Clean up log files in the main logs directory
        for log_file in LOGS_DIR.glob("*.log"):
            try:
                file_mtime = log_file.stat().st_mtime
                
                # Check if this is a JSON log file (like fyersRequests.log)
                if log_file.name in ['fyersRequests.log', 'fyersApi.log']:
                    # Clean old entries from within the file
                    entries_removed = _clean_json_log_file(log_file, cutoff_datetime)
                    if entries_removed > 0:
                        cleaned_files.append((log_file.name, entries_removed))
                
                # If the entire file is old, delete it
                elif file_mtime < cutoff_time:
                    file_size = log_file.stat().st_size
                    log_file.unlink()
                    deleted_count += 1
                    deleted_size += file_size
                    print(f"Deleted old log file: {log_file.name} ({file_size / 1024:.1f} KB)")
                    
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
        
        # Clean up old date-based subdirectories
        for subdir in LOGS_DIR.iterdir():
            if subdir.is_dir():
                try:
                    dir_mtime = subdir.stat().st_mtime
                    if dir_mtime < cutoff_time:
                        # Remove all files in the directory first
                        for file in subdir.rglob("*"):
                            if file.is_file():
                                file_size = file.stat().st_size
                                file.unlink()
                                deleted_size += file_size
                        # Remove the directory
                        subdir.rmdir()
                        deleted_count += 1
                        print(f"Deleted old log directory: {subdir.name}")
                except Exception as e:
                    print(f"Error deleting directory {subdir}: {e}")
        
        # Report results
        if cleaned_files:
            for filename, count in cleaned_files:
                print(f"Cleaned {count} old entries from {filename}")
        
        if deleted_count > 0:
            print(f"✅ Log cleanup complete: Removed {deleted_count} items, freed {deleted_size / (1024 * 1024):.2f} MB")
        elif cleaned_files:
            print(f"✅ Log cleanup complete: Cleaned {sum(c for _, c in cleaned_files)} old entries from log files")
        else:
            print(f"✅ Log cleanup complete: No old logs to remove (keeping logs < {max_age_hours}h old)")
            
    except Exception as e:
        print(f"❌ Error during log cleanup: {e}")


def _clean_json_log_file(log_file: Path, cutoff_datetime: datetime) -> int:
    """
    Clean old entries from a JSON log file.
    Each line is expected to be a JSON object with a 'timestamp' field.
    
    Args:
        log_file: Path to the log file
        cutoff_datetime: Datetime cutoff - entries older than this will be removed
        
    Returns:
        Number of entries removed
    """
    try:
        # Read all lines
        with open(log_file, 'r') as f:
            lines = f.readlines()
        
        original_count = len(lines)
        kept_lines = []
        
        for line in lines:
            try:
                # Parse JSON log entry
                log_entry = json.loads(line.strip())
                timestamp_str = log_entry.get('timestamp', '')
                
                # Parse timestamp (format: "2025-11-15 04:52:36,251+0530")
                # Remove timezone and milliseconds for parsing
                timestamp_clean = timestamp_str.split('+')[0].replace(',', '.')
                log_datetime = datetime.strptime(timestamp_clean, '%Y-%m-%d %H:%M:%S.%f')
                
                # Keep if newer than cutoff
                if log_datetime >= cutoff_datetime:
                    kept_lines.append(line)
                    
            except (json.JSONDecodeError, ValueError, KeyError):
                # If we can't parse it, keep it to be safe
                kept_lines.append(line)
        
        # Write back only the kept lines
        if len(kept_lines) < original_count:
            with open(log_file, 'w') as f:
                f.writelines(kept_lines)
            return original_count - len(kept_lines)
        
        return 0
        
    except Exception as e:
        print(f"Error cleaning {log_file.name}: {e}")
        return 0


def get_log_stats():
    """
    Get statistics about current log files.
    
    Returns:
        dict: Statistics including total size, file count, oldest file age
    """
    if not LOGS_DIR.exists():
        return {"total_size": 0, "file_count": 0, "oldest_age_hours": 0}
    
    total_size = 0
    file_count = 0
    oldest_mtime = time.time()
    
    for log_file in LOGS_DIR.rglob("*.log"):
        if log_file.is_file():
            total_size += log_file.stat().st_size
            file_count += 1
            file_mtime = log_file.stat().st_mtime
            if file_mtime < oldest_mtime:
                oldest_mtime = file_mtime
    
    oldest_age_hours = (time.time() - oldest_mtime) / 3600 if file_count > 0 else 0
    
    return {
        "total_size": total_size,
        "total_size_mb": total_size / (1024 * 1024),
        "file_count": file_count,
        "oldest_age_hours": oldest_age_hours
    }
